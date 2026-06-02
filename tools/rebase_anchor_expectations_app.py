from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.anchor_regression_suite import _odd_for_case_app


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _tol_for_odd(odd: float, fav_split: float, tol_fav: float, tol_dog: float) -> float:
    return float(tol_fav if float(odd) <= float(fav_split) else tol_dog)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Rebase semantic anchor odd ranges from current app pipeline (A/B/C live)."
    )
    ap.add_argument("--expectations", default="ops/key_matchup_expectations.json")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--tol-fav-pct", type=float, default=0.12, help="Tolerance for favorite odds.")
    ap.add_argument("--tol-dog-pct", type=float, default=0.20, help="Tolerance for underdog odds.")
    ap.add_argument("--fav-split", type=float, default=2.0)
    ap.add_argument("--floor", type=float, default=1.01)
    args = ap.parse_args()

    exp_path = Path(args.expectations)
    data = _load_json(exp_path)
    cases: List[Dict[str, Any]] = list(data.get("cases", []))
    if not cases:
        print(f"[error] sem casos em {exp_path}")
        return 2

    root = Path(__file__).resolve().parents[1]
    updated = 0
    for c in cases:
        try:
            team_a = str(c["team_a"])
            team_b = str(c["team_b"])
            market = str(c.get("market", "bo5"))
            side = str(c.get("side", "a"))
            odd = float(
                _odd_for_case_app(
                    root=root,
                    team_a=team_a,
                    team_b=team_b,
                    market=market,
                    side=side,
                    timeout=int(args.timeout),
                )
            )
            tol = _tol_for_odd(
                odd=odd,
                fav_split=float(args.fav_split),
                tol_fav=float(args.tol_fav_pct),
                tol_dog=float(args.tol_dog_pct),
            )
            min_odd = max(float(args.floor), float(odd) * (1.0 - tol))
            max_odd = float(odd) * (1.0 + tol)
            c["baseline_odd"] = round(float(odd), 3)
            c["min_odd"] = round(float(min_odd), 3)
            c["max_odd"] = round(float(max_odd), 3)
            c["tolerance_pct"] = round(float(tol), 3)
            updated += 1
            print(
                f"[ok] {c.get('name', team_a + ' vs ' + team_b)} -> "
                f"odd={odd:.3f} faixa=[{min_odd:.3f}, {max_odd:.3f}]"
            )
        except Exception as e:
            print(f"[warn] nao atualizei caso {c.get('name', '<sem_nome>')}: {e}")

    data["cases"] = cases
    exp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] expectations rebased: {exp_path} | updated={updated}/{len(cases)}")
    return 0 if updated > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

