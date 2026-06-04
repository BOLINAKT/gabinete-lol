"""Checa se a máquina está pronta pra rodar o app — e diz EXATAMENTE o que falta.

Roda PRIMEIRO numa máquina nova (a do seu amigo). Em vez do app crashar com erro
críptico, este check lista, com ✅/❌, o que está ok e o que falta, e como
resolver cada coisa. Usa só a biblioteca padrão pra conseguir rodar mesmo antes
de instalar as dependências.

  python tools/setup_check.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Garante saída sem crash em qualquer console (cp1252/UTF-8/etc.) — esta é uma
# ferramenta de portabilidade, então ela mesma não pode quebrar por encoding.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]

# pacote (pip) -> módulo de import (quando diferem)
DEPS = {
    "altair": "altair", "click": "click", "matplotlib": "matplotlib",
    "numpy": "numpy", "pandas": "pandas", "pillow": "PIL",
    "python-dateutil": "dateutil", "pytz": "pytz", "requests": "requests",
    "scikit-image": "skimage", "scikit-learn": "sklearn", "scipy": "scipy",
    "streamlit": "streamlit", "tqdm": "tqdm",
}

# Arquivos de runtime que NÃO vão no git (modelo + dados). Sem eles o app sobe
# "sem cérebro". (critico=True derruba o check.)
RUNTIME = [
    ("ml_artifact.json", True, "o modelo (Elo+calibrador). Receba o bundle de release OU rode tools/atualizar_modelo.py."),
    ("players_artifact.json", True, "camada de players. Vem junto do bundle / do atualizar_modelo."),
    ("params_fitted.json", False, "pesos de fusão (opcional; o app funciona sem, com defaults)."),
]
CSV_DIRS = [("CSV_HISTORICO", "CSVs de temporadas passadas"), ("CSV_DIARIO", "CSV da temporada atual")]


def _ok(b: bool) -> str:
    # ASCII de propósito: emoji quebra no console cp1252 do Windows (justamente a
    # máquina-alvo). Marcadores ASCII funcionam em qualquer terminal.
    return "[ok]" if b else "[--]"


def main() -> int:
    print(f"\n=== SETUP CHECK — {ROOT.name} ===")
    problems: list[str] = []

    # 1) Python
    vmaj, vmin = sys.version_info[:2]
    py_ok = (vmaj == 3 and vmin >= 11)
    print(f"{_ok(py_ok)} Python {vmaj}.{vmin} (recomendado 3.13; mínimo 3.11)")
    if not py_ok:
        problems.append("Instale Python 3.13 (veja .python-version).")

    # 2) Dependências
    print("\nDependências (requirements.txt):")
    missing = []
    for pkg, mod in sorted(DEPS.items()):
        present = importlib.util.find_spec(mod) is not None
        print(f"  {_ok(present)} {pkg}")
        if not present:
            missing.append(pkg)
    if missing:
        problems.append(f"Faltam libs: {', '.join(missing)}. Rode: pip install -r requirements.txt")

    # 3) Modelo + dados (runtime, fora do git)
    print("\nModelo + dados (não vão no git — precisam do bundle de release):")
    for name, critical, hint in RUNTIME:
        present = (ROOT / name).exists()
        print(f"  {_ok(present)} {name}" + ("" if present else f"  → {hint}"))
        if critical and not present:
            problems.append(f"Falta {name}: {hint}")

    for d, desc in CSV_DIRS:
        p = ROOT / d
        n = len(list(p.glob("*.csv"))) if p.is_dir() else 0
        present = n > 0
        print(f"  {_ok(present)} {d}/ ({n} CSV) — {desc}" + ("" if present else "  → receba os CSVs no bundle de release."))
        if not present:
            problems.append(f"Falta {d}/ com CSVs: {desc}.")

    # Veredito
    print("\n" + "=" * 56)
    if not problems:
        print("[ok] TUDO PRONTO. Rode o app:  streamlit run plays_app.py")
        return 0
    print("[--] FALTAM COISAS — resolva e rode de novo:")
    for i, p in enumerate(problems, 1):
        print(f"  {i}. {p}")
    print("\n(Detalhes do setup completo em SETUP.md.)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
