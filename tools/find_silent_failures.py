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
import io
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix-encoding", action="store_true",
                    help="insere o ajuste de stdout nos arquivos que precisam")
    args = ap.parse_args()

    risco_enc: list[tuple[Path, str]] = []
    risco_sub: list[tuple[Path, int]] = []
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

    print(f"=== 1) IMPRIME NÃO-ASCII SEM AJUSTAR O ENCODING: {len(risco_enc)} arquivo(s) ===")
    for p, ch in risco_enc:
        print(f"  {p.relative_to(ROOT)}   (ex.: {ch!r})")
    print(f"\n=== 2) SUBPROCESSO COM SAÍDA CAPTURADA E RESULTADO IGNORADO: {len(risco_sub)} ===")
    for p, n in risco_sub:
        print(f"  {p.relative_to(ROOT)}   ({n} chamada(s))")

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
