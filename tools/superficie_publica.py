# -*- coding: utf-8 -*-
"""Quem importa o quê de um módulo — a superfície pública REAL, por AST.

Nasceu de um erro meu repetido duas vezes em 16/08/2026: verifiquei com TEXTO o
que precisava de ESTRUTURA. Primeiro contei `# noqa` só na linha citada pelo
pyflakes (em import multi-linha o marcador fica na linha do símbolo, não na do
`from`) e conclui "41 avisos acionáveis" quando eram 5. Depois procurei
re-exports com `grep "modulo import" | grep nome` — que também não casa import
multi-linha — e removi `_days_between_iso`, quebrando a suíte.

Nos dois casos o erro foi na mesma direção: SUBESTIMAR o que já existia e quase
remover algo em uso. E o modo de falha é traiçoeiro: remover um re-export não
quebra onde você mexeu, quebra num ImportError longe dali — às vezes só quando
alguém abre a tela que importa.

Antes de fatiar um módulo, rode isto: transforma "acho que ninguém usa" em
"ninguém usa, verificado".

Uso:  python tools/superficie_publica.py mlcore/state_team_artifact.py
      python tools/superficie_publica.py app_core/line_analysis_tab_core.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
VARRER = ("mlcore", "app_core", "tools")


def modulo_de(path: Path) -> str:
    return path.relative_to(ROOT).with_suffix("").as_posix().replace("/", ".")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.strip().splitlines()[-2])
        return 2
    alvo = Path(sys.argv[1])
    if not alvo.is_absolute():
        alvo = ROOT / alvo
    if not alvo.exists():
        print(f"nao achei: {alvo}")
        return 1
    mod = modulo_de(alvo)
    curto = alvo.stem

    arquivos = [ROOT / "plays_app.py"]
    for pasta in VARRER:
        arquivos += sorted((ROOT / pasta).rglob("*.py"))

    usos: dict[str, list[str]] = {}
    for p in arquivos:
        if p == alvo:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module and (
                    n.module == mod or n.module.endswith("." + curto) or n.module == curto):
                for a in n.names:
                    usos.setdefault(a.name, []).append(str(p.relative_to(ROOT)))
            elif isinstance(n, ast.Import):
                for a in n.names:
                    if a.name.endswith(curto):
                        usos.setdefault("<modulo inteiro>", []).append(str(p.relative_to(ROOT)))

    try:
        meu = ast.parse(alvo.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        print("nao consegui ler o alvo")
        return 1
    definidos = sorted({n.name for n in meu.body
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))})

    print(f"=== {alvo.relative_to(ROOT)} ===")
    print(f"define {len(definidos)} simbolo(s) de topo\n")
    if not usos:
        print("NINGUEM importa deste modulo — fatiar aqui e livre.")
        return 0
    print(f"{'simbolo':<38}{'quem importa':>14}")
    for k in sorted(usos, key=lambda x: -len(usos[x])):
        quem = sorted(set(usos[k]))
        print(f"{k:<38}{len(quem):>14}   {', '.join(q for q in quem[:3])}"
              + (" ..." if len(quem) > 3 else ""))
    externos = set(usos) - set(definidos) - {"<modulo inteiro>"}
    if externos:
        print(f"\nATENCAO — importados DAQUI mas NAO definidos aqui (re-export puro):")
        print("  " + ", ".join(sorted(externos)))
        print("  Estes sao os que somem sem aviso se voce enxugar os imports.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
