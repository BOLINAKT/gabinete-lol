# -*- coding: utf-8 -*-
"""VARREDURA: código que falha CALADO (16/08/2026).

Motivo: num único dia, quatro ferramentas quebraram por UnicodeEncodeError no
console cp1252 do Windows — train_offline (nome de time em chinês), o gate do TI,
product_scorecard (o símbolo de aviso) e data_scorecard (uma seta "→"). Nenhuma
gritou. A régua de Dados ficou SEMANAS quebrada e o sintoma aparecia apenas como
"nota velha", que não aponta para a causa. E o que a escondia era outro silêncio:
`subprocess.run(capture_output=True)` sem checar o returncode.

CINCO famílias, todas detectáveis mecanicamente. (O texto aqui dizia DUAS
até 08/09/2026: o próprio arquivo tinha apodrecido, e ninguém notou porque
docstring não é executado.)

  1) IMPRIME NÃO-ASCII E NÃO AJUSTA O ENCODING
     Um print com acento/emoji derruba o script inteiro num console cp1252 —
     normalmente no fim, depois do trabalho todo já feito.

  2) RODA SUBPROCESSO E IGNORA O RESULTADO
     subprocess.run(...) cujo retorno não é checado: a falha vira silêncio.

  3) EXCEÇÃO ENGOLIDA (`except ...: pass`)
     Nem todo caso é bug — às vezes engolir é a decisão certa. Por isso
     REPORTA com linha e tipo, para julgar caso a caso.

  4) coerce + fillna — DADO RUIM VIRA NÚMERO REAL
     O coerce transforma o ilegível em NaN e o fillna troca por um valor
     plausível. Junto, "a coluna mudou de formato" vira "todo mundo com 0".

  5) getattr COM DEFAULT LENDO CAMPO DE OUTRA CAMADA  (08/09/2026)
     `getattr(x, "nome", 0.0)` de um objeto que não tem esse campo devolve
     0.0 calado, para sempre. Foi assim que a camada de jogadores sumiu da
     nota oficial (dívida D5): o replay lia `delta_players_eff` de um
     `Sample` que não tem delta nenhum. Só conta default PLAUSÍVEL — com
     `None` o idioma é correto, porque obriga quem chama a tratar.

Uso:  python tools/find_silent_failures.py [--fix-encoding]
Saída: lista de arquivos, e com --fix-encoding insere o ajuste de stdout.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
# --root permite varrer OUTRO repositorio (o do Dota nasceu como clone deste e
# nunca passou pela varredura). Pastas inexistentes sao ignoradas: o Dota nao
# tem tools/, e tem modulos soltos na raiz que o LoL nao tem.
ALVOS = ["tools", "mlcore", "app_core", "."]
RECONFIG = re.compile(r"stdout\.reconfigure|PYTHONIOENCODING|codecs\.getwriter")

AJUSTE = '''
# Console cp1252 no Windows derruba qualquer print com acento/emoji — e o estouro
# vem no fim, depois do trabalho todo feito. Ver tools/find_silent_failures.py.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass
'''


def tem_script_de_terminal(src: str) -> bool:
    """Só interessa quem imprime para o terminal (tem __main__ ou print de topo)."""
    return '__main__' in src or "\nprint(" in src or src.startswith("print(")


def nao_ascii_em_literal(tree: ast.AST) -> str | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for ch in node.value:
                if ord(ch) > 127:
                    return ch
    return None


def subprocesso_ignorado(tree: ast.AST) -> int:
    """subprocess.run(...) como statement solto = resultado jogado fora."""
    n = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        f = call.func
        nome = ""
        if isinstance(f, ast.Attribute):
            nome = f.attr
            if isinstance(f.value, ast.Name):
                nome = f"{f.value.id}.{f.attr}"
        if nome in {"subprocess.run", "subprocess.call", "run"}:
            # so conta quando captura a saida (a falha fica REALMENTE invisivel)
            if any(k.arg in {"capture_output", "stdout", "stderr"} for k in call.keywords):
                n += 1
    return n


def excecao_engolida(tree: ast.AST) -> list[tuple[int, str]]:
    """`except ...: pass` — o erro acontece e ninguem fica sabendo.

    Nem todo caso e bug: as vezes engolir e a decisao certa (limpeza best-effort,
    bloco de UI que nao pode derrubar a aba). Por isso a ferramenta REPORTA com
    linha e tipo, para julgar caso a caso — o problema e engolir sem querer.
    """
    achados = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        corpo = [n for n in node.body if not isinstance(n, ast.Pass)]
        if corpo:
            continue   # faz alguma coisa (loga, devolve, re-levanta)
        tipo = "except:"
        if node.type is not None:
            try:
                tipo = f"except {ast.unparse(node.type)}:"
            except (AttributeError, ValueError):
                tipo = "except <?>:"
        achados.append((node.lineno, tipo))
    return achados


def coerce_com_fillna(tree: ast.AST) -> list[int]:
    """to_numeric(errors="coerce").fillna(N) — dado ruim vira NUMERO DE VERDADE.

    O coerce transforma o que nao da pra ler em NaN; o fillna troca esse NaN por
    um valor plausivel. Junto, isso converte "coluna mudou de formato" em "todo
    mundo com 0", que o modelo consome como se fosse medicao real. Perde-se ate
    a chance de perceber pelo NaN.
    """
    linhas = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr == "fillna"):
            continue
        # o alvo do fillna e um to_numeric(..., errors="coerce")?
        alvo = f.value
        if isinstance(alvo, ast.Call) and isinstance(alvo.func, ast.Attribute) \
                and alvo.func.attr == "to_numeric":
            if any(k.arg == "errors" and isinstance(k.value, ast.Constant)
                   and k.value.value == "coerce" for k in alvo.keywords):
                linhas.append(node.lineno)
    return linhas



def getattr_com_default(tree: ast.AST) -> list[tuple[int, str]]:
    """`getattr(x, "nome", default)` — leitura que NUNCA falha, mesmo errada.

    Familia acrescentada em 08/09/2026, pela divida D5. O replay lia
    `getattr(s, "delta_players_eff", 0.0)` de um objeto `Sample` que NAO TEM
    campo de delta nenhum. O default 0.0 voltava calado, em 100% dos jogos, e
    a nota oficial passou a medir o Elo sozinho sem ninguem saber.

    O `getattr` com default e a versao do `except: pass` para leitura de
    atributo: em vez de estourar, devolve algo plausivel para sempre.
    "Errors should never pass silently" e "e melhor falhar rapido do que
    esconder um erro que causa bug la na frente".
    https://pybit.es/articles/python-errors-should-not-pass-silently/
    (conferida abrindo a pagina em 08/09/2026)
    """
    fora = []
    for no in ast.walk(tree):
        if (isinstance(no, ast.Call) and isinstance(no.func, ast.Name)
                and no.func.id == "getattr" and len(no.args) == 3
                and isinstance(no.args[1], ast.Constant)
                and isinstance(no.args[1].value, str)):
            # SO conta default PLAUSIVEL. `None` e o idioma CERTO: nao e um
            # valor de dado, entao obriga quem chama a tratar -- e o codigo ao
            # lado normalmente faz `if x is not None`. Perigoso e 0.0, "" ou
            # 0, que entram na conta fingindo ser medicao. Foi 0.0 que apagou
            # a camada de jogadores da nota oficial por meses (divida D5).
            padrao = no.args[2]
            if isinstance(padrao, ast.Constant) and padrao.value is None:
                continue
            fora.append((getattr(no, "lineno", 0), no.args[1].value))
    return fora


def _nomes_de_campo(raiz, pastas):
    """Onde cada nome de atributo APARECE, por pasta de topo.

    Separa `getattr` que le algo da propria camada (normal) de `getattr` que
    le a forma de OUTRA camada — o caso da D5: mlcore lendo um campo que so
    existe em app_core."""
    onde = {}
    for pasta in pastas:
        base = raiz / pasta
        if not base.exists():
            continue
        arqs = sorted(base.glob("*.py")) if pasta == "." else sorted(base.rglob("*.py"))
        for q in arqs:
            if "__pycache__" in q.parts or "backups" in q.parts:
                continue
            try:
                t = ast.parse(q.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            topo = q.relative_to(raiz).parts[0]
            for no in ast.walk(t):
                nome = None
                if isinstance(no, ast.Attribute):
                    nome = no.attr
                elif isinstance(no, ast.AnnAssign) and isinstance(no.target, ast.Name):
                    nome = no.target.id
                if nome:
                    onde.setdefault(nome, set()).add(topo)
    return onde


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix-encoding", action="store_true",
                    help="insere o ajuste de stdout nos arquivos que precisam")
    ap.add_argument("--root", default=None,
                    help="varre outro repositorio (ex.: ../GabineteDOTA)")
    args = ap.parse_args()
    global ROOT
    if args.root:
        ROOT = Path(args.root).resolve()
        print(f"[raiz] {ROOT}")

    risco_enc: list[tuple[Path, str]] = []
    risco_sub: list[tuple[Path, int]] = []
    risco_exc: list[tuple[Path, list]] = []
    risco_coerce: list[tuple[Path, list]] = []
    risco_getattr: list[tuple[Path, list]] = []
    onde_aparece = _nomes_de_campo(ROOT, ALVOS)
    for pasta in ALVOS:
        base = ROOT / pasta
        if not base.exists():
            continue
        arquivos = sorted(base.glob("*.py")) if pasta == "." else sorted(base.rglob("*.py"))
        for p in arquivos:
            if ("tests" in p.parts or "__pycache__" in p.parts
                    or "backups" in p.parts or "_recovered" in p.parts):
                continue
            try:
                src = p.read_text(encoding="utf-8")
                tree = ast.parse(src)
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            if tem_script_de_terminal(src) and not RECONFIG.search(src):
                ch = nao_ascii_em_literal(tree)
                if ch:
                    risco_enc.append((p, ch))
            n = subprocesso_ignorado(tree)
            if n:
                risco_sub.append((p, n))
            eng = excecao_engolida(tree)
            if eng:
                risco_exc.append((p, eng))
            co = coerce_com_fillna(tree)
            if co:
                risco_coerce.append((p, co))
            # So interessa o getattr que le a forma de OUTRA camada: dentro da
            # propria pasta e uso normal. Foi assim que a D5 passou -- mlcore
            # lendo um campo que so existe em app_core.
            minha = p.relative_to(ROOT).parts[0]
            ga = [(ln, nm) for ln, nm in getattr_com_default(tree)
                  if onde_aparece.get(nm) and minha not in onde_aparece[nm]]
            if ga:
                risco_getattr.append((p, ga))

    print(f"=== 1) IMPRIME NÃO-ASCII SEM AJUSTAR O ENCODING: {len(risco_enc)} arquivo(s) ===")
    for p, ch in risco_enc:
        print(f"  {p.relative_to(ROOT)}   (ex.: {ch!r})")
    print(f"\n=== 2) SUBPROCESSO COM SAÍDA CAPTURADA E RESULTADO IGNORADO: {len(risco_sub)} ===")
    for p, n in risco_sub:
        print(f"  {p.relative_to(ROOT)}   ({n} chamada(s))")

    # O CAMINHO DO MODELO pesa mais: ali o silencio vira probabilidade errada,
    # nao tela feia. Por isso mlcore vem separado e primeiro.
    def _nucleo(t):
        return str(t[0].relative_to(ROOT)).startswith("mlcore")

    tot_exc = sum(len(v) for _, v in risco_exc)
    print(f"\n=== 3) EXCEÇÃO ENGOLIDA (`except: pass`): {tot_exc} em {len(risco_exc)} arquivo(s) ===")
    print("    (nem todo caso é bug — julgar. O que importa é engolir SEM QUERER.)")
    for grupo, rot in ((sorted(filter(_nucleo, risco_exc), key=lambda t: -len(t[1])), "NÚCLEO DO MODELO"),
                       (sorted([t for t in risco_exc if not _nucleo(t)], key=lambda t: -len(t[1])), "resto")):
        if not grupo:
            continue
        print(f"  -- {rot} --")
        for p, v in grupo[:10]:
            linhas = ", ".join(str(l) for l, _ in v[:6])
            print(f"    {str(p.relative_to(ROOT)):<46} {len(v):>3}x  linhas {linhas}")

    tot_co = sum(len(v) for _, v in risco_coerce)
    print(f"\n=== 4) coerce + fillna — DADO RUIM VIRA NÚMERO REAL: {tot_co} em {len(risco_coerce)} ===")
    for p, v in sorted(risco_coerce, key=lambda t: -len(t[1]))[:12]:
        print(f"  {str(p.relative_to(ROOT)):<46} {len(v):>3}x  linhas "
              + ", ".join(str(l) for l in v[:6]))

    if args.fix_encoding and risco_enc:
        n_ok = 0
        for p, _ in risco_enc:
            src = p.read_text(encoding="utf-8")
            m = re.search(r"^import sys$", src, re.M)
            if not m:
                print(f"  [pulado] {p.name}: não achei 'import sys' no topo")
                continue
            i = src.find("\n", m.end())
            p.write_text(src[:i + 1] + AJUSTE + src[i + 1:], encoding="utf-8")
            n_ok += 1
        print(f"\n[--fix-encoding] ajustados: {n_ok}")

    if not risco_enc and not risco_sub:
        print("\nlimpo — nada falhando calado por estes dois padrões.")
    tot_ga = sum(len(v) for _, v in risco_getattr)
    print(f"\n=== 5) getattr COM DEFAULT lendo campo de OUTRA camada: "
          f"{tot_ga} em {len(risco_getattr)} ===")
    print("    (o caso da divida D5: o default volta calado quando o campo nao"
          " existe naquele objeto)")
    # ORDENAR POR RISCO, NAO POR VOLUME (08/09/2026). A primeira versao deste
    # relatorio mostrava os 12 MAIORES por contagem — e o caso que originou a
    # familia inteira (o `delta_players_eff` do replay, uma ocorrencia so)
    # ficava de fora. A ferramenta ACHOU e ESCONDEU. Contagem alta em arquivo
    # de tela e ruido; UMA ocorrencia no nucleo de medicao apaga uma nota.
    _PESO = {"mlcore": 0, "tools": 1}   # medicao primeiro; o resto depois

    def _risco(item):
        q, v = item
        return (_PESO.get(q.relative_to(ROOT).parts[0], 2), -len(v), str(q))

    for q, v in sorted(risco_getattr, key=_risco):
        nomes = ", ".join(sorted({nm for _, nm in v})[:4])
        linhas = ", ".join(str(ln) for ln, _ in sorted(v)[:4])
        print(f"  {str(q.relative_to(ROOT)):<46} {len(v)}x  L{linhas}  {nomes}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
