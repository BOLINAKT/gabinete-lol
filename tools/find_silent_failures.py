# -*- coding: utf-8 -*-
"""VARREDURA: código que falha CALADO (16/08/2026).

Motivo: num único dia, quatro ferramentas quebraram por UnicodeEncodeError no
console cp1252 do Windows — train_offline (nome de time em chinês), o gate do TI,
product_scorecard (o símbolo de aviso) e data_scorecard (uma seta "→"). Nenhuma
gritou. A régua de Dados ficou SEMANAS quebrada e o sintoma aparecia apenas como
"nota velha", que não aponta para a causa. E o que a escondia era outro silêncio:
`subprocess.run(capture_output=True)` sem checar o returncode.

Duas famílias, ambas detectáveis mecanicamente:

  1) IMPRIME NÃO-ASCII E NÃO AJUSTA O ENCODING
     Um print com acento/emoji derruba o script inteiro num console cp1252 —
     normalmente no fim, depois do trabalho todo já feito.

  2) RODA SUBPROCESSO E IGNORA O RESULTADO
     subprocess.run(...) cujo retorno não é checado: a falha vira silêncio.

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
ALVOS = ["tools", "mlcore", "app_core"]
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix-encoding", action="store_true",
                    help="insere o ajuste de stdout nos arquivos que precisam")
    args = ap.parse_args()

    risco_enc: list[tuple[Path, str]] = []
    risco_sub: list[tuple[Path, int]] = []
    risco_exc: list[tuple[Path, list]] = []
    risco_coerce: list[tuple[Path, list]] = []
    for pasta in ALVOS:
        for p in sorted((ROOT / pasta).rglob("*.py")):
            if "tests" in p.parts or "__pycache__" in p.parts:
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
