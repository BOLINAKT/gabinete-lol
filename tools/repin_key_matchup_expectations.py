# -*- coding: utf-8 -*-
"""RE-PIN automático das âncoras de confrontos-chave (decisão dele 18/07:
"pode usar as odds que o modelo está me fornecendo").

O gate semântico deixa de ser opinião digitada (as bandas de março/2026
apodreceram caladas por 4 meses e passaram a reprovar QUALQUER candidato,
inclusive a produção) e vira GUARDA DE DERIVA: banda = odd do modelo BOM
atual ± tolerância. Um candidato à promoção só passa se não fugir loucamente
do último estado sadio nos confrontos-chave.

Roda automaticamente após cada promoção validada (promote_baseline) e pode
ser rodado à mão. NUNCA rodar com params/artifact experimentais no lugar —
o pin é sempre do estado que se confia.

Uso: python tools/repin_key_matchup_expectations.py [--tolerance 0.15]
"""
from __future__ import annotations

import argparse
import json
import sys

# Console cp1252 no Windows derruba qualquer print com acento/emoji — e o estouro
# vem no fim, depois do trabalho todo feito. Ver tools/find_silent_failures.py.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.anchor_regression_suite import _odd_for_case_app  # noqa: E402

DEFAULT_TOL = 0.15  # ±15% multiplicativo (bandas de março tinham ~±13%)
ODD_FLOOR = 1.01


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-pina bandas das âncoras a partir do modelo atual (guarda de deriva).")
    ap.add_argument("--expectations", default="ops/key_matchup_expectations.json")
    ap.add_argument("--tolerance", type=float, default=DEFAULT_TOL)
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    path = ROOT / args.expectations
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    cases = list(data.get("cases", []))
    if not cases:
        print("ERRO: arquivo de expectativas sem casos")
        return 1

    tol = max(0.01, float(args.tolerance))
    out_cases = []
    fails = 0
    for c in cases:
        name = str(c.get("name", "")).strip()
        try:
            odd = float(_odd_for_case_app(
                ROOT, str(c["team_a"]), str(c["team_b"]),
                str(c.get("market", "bo5")), str(c.get("side", "a")),
                int(args.timeout),
            ))
            new_c = dict(c)
            new_c["baseline_odd"] = round(odd, 4)
            new_c["min_odd"] = round(max(ODD_FLOOR, odd / (1.0 + tol)), 4)
            new_c["max_odd"] = round(odd * (1.0 + tol), 4)
            out_cases.append(new_c)
            print(f"  {name:36} odd={odd:.3f} -> banda [{new_c['min_odd']:.3f}, {new_c['max_odd']:.3f}]", flush=True)
        except Exception as e:
            fails += 1
            out_cases.append(dict(c))  # mantém banda antiga se o caso falhar
            print(f"  {name:36} FALHOU ({type(e).__name__}: {str(e)[:80]}) — banda antiga mantida", flush=True)

    data["cases"] = out_cases
    data["repin_meta"] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "auto_repin_producao",
        "tolerance": tol,
        "failed_cases": fails,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: re-pin salvo -> {path} ({len(out_cases)} casos, {fails} falhas)")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
