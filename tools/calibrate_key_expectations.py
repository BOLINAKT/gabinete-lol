from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mlcore.artifact import MLArtifact
from mlcore.bo import prob_win_series
from mlcore.utils import prob_to_decimal_odds


def _market_prob(p_map: float, market: str) -> float:
    m = str(market).strip().lower()
    if m in ("map", "bo1"):
        return float(p_map)
    if m == "bo3":
        return float(prob_win_series(float(p_map), 3))
    if m == "bo5":
        return float(prob_win_series(float(p_map), 5))
    raise ValueError(f"market invalido: {market}")


def _calc_odd(art: MLArtifact, team_a: str, team_b: str, market: str, side: str) -> float:
    p_f = float(art.model.p_blue(team_a, team_b))
    p_r = float(art.model.p_blue(team_b, team_a))
    p_cal_f = float(art.calibrator.predict_proba(p_f))
    p_cal_r = float(art.calibrator.predict_proba(p_r))
    p_map_a = float(0.5 * (p_cal_f + (1.0 - p_cal_r)))
    p_market_a = _market_prob(p_map_a, market)
    s = str(side).strip().lower()
    if s in ("a", "team_a"):
        return float(prob_to_decimal_odds(p_market_a))
    if s in ("b", "team_b"):
        return float(prob_to_decimal_odds(1.0 - p_market_a))
    raise ValueError(f"side invalido: {side}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Calibrate key matchup expectations from current artifact.")
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--expectations", default="ops/key_matchup_expectations.json")
    ap.add_argument("--tol-fav-pct", type=float, default=0.12, help="Percent tolerance for favorites (odd <= split).")
    ap.add_argument("--tol-dog-pct", type=float, default=0.20, help="Percent tolerance for underdogs (odd > split).")
    ap.add_argument("--fav-split", type=float, default=2.0, help="Odd threshold to separate favorite vs dog.")
    ap.add_argument("--floor", type=float, default=1.01, help="Minimum allowed odd bound.")
    args = ap.parse_args()

    exp_path = Path(args.expectations)
    try:
        data = json.loads(exp_path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        print(f"[error] Nao consegui ler expectations JSON: {exp_path} ({e})")
        return 2
    cases = list(data.get("cases", []))
    art = MLArtifact.load_json(str(args.artifact))

    for c in cases:
        try:
            team_a = str(c["team_a"])
            team_b = str(c["team_b"])
            market = str(c.get("market", "bo5"))
            side = str(c.get("side", "a"))
            odd = _calc_odd(art, team_a, team_b, market, side)
            tol = float(args.tol_fav_pct if odd <= float(args.fav_split) else args.tol_dog_pct)
            min_odd = max(float(args.floor), float(odd) * (1.0 - tol))
            max_odd = float(odd) * (1.0 + tol)
            c["min_odd"] = round(min_odd, 3)
            c["max_odd"] = round(max_odd, 3)
            c["baseline_odd"] = round(float(odd), 3)
            c["tolerance_pct"] = round(float(tol), 3)
            print(
                f"[ok] {c.get('name', team_a + ' vs ' + team_b)} -> "
                f"odd={odd:.3f} faixa=[{min_odd:.3f}, {max_odd:.3f}] tol={tol:.1%}"
            )
        except Exception as e:
            print(f"[warn] caso ignorado por erro: {c.get('name', '<sem_nome>')} ({e})")

    exp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] expectations updated: {exp_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
