from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mlcore.artifact import MLArtifact
from mlcore.bo import prob_win_series
from mlcore.utils import prob_to_decimal_odds


@dataclass
class CaseResult:
    name: str
    ok: bool
    team_a: str
    team_b: str
    market: str
    side: str
    odd_value: float
    min_odd: float
    max_odd: float


def _market_prob(p_map: float, market: str) -> float:
    m = str(market).strip().lower()
    if m in ("map", "bo1"):
        return float(p_map)
    if m == "bo3":
        return float(prob_win_series(float(p_map), 3))
    if m == "bo5":
        return float(prob_win_series(float(p_map), 5))
    raise ValueError(f"market invalido: {market}")


def _odd_for_case(art: MLArtifact, team_a: str, team_b: str, market: str, side: str) -> float:
    p_f = float(art.model.p_blue(team_a, team_b))
    p_r = float(art.model.p_blue(team_b, team_a))
    p_cal_f = float(art.calibrator.predict_proba(p_f))
    p_cal_r = float(art.calibrator.predict_proba(p_r))
    p_map_a = float(0.5 * (p_cal_f + (1.0 - p_cal_r)))
    p_market_a = _market_prob(p_map_a, market)
    side_norm = str(side).strip().lower()
    if side_norm in ("a", "team_a"):
        return float(prob_to_decimal_odds(p_market_a))
    if side_norm in ("b", "team_b"):
        return float(prob_to_decimal_odds(1.0 - p_market_a))
    raise ValueError(f"side invalido: {side}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate key matchup odds ranges.")
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--expectations", default="ops/key_matchup_expectations.json")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    art = MLArtifact.load_json(str(args.artifact))
    exp_path = Path(args.expectations)
    try:
        data = json.loads(exp_path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        print(f"[error] Nao consegui ler expectations JSON: {exp_path} ({e})")
        return 2
    cases = list(data.get("cases", []))

    results: list[CaseResult] = []
    for c in cases:
        name = str(c.get("name", "")).strip() or f"{c.get('team_a')} vs {c.get('team_b')}"
        try:
            team_a = str(c["team_a"])
            team_b = str(c["team_b"])
            market = str(c.get("market", "bo5"))
            side = str(c.get("side", "a"))
            min_odd = float(c["min_odd"])
            max_odd = float(c["max_odd"])
            odd_value = _odd_for_case(art, team_a, team_b, market, side)
            ok = float(min_odd) <= float(odd_value) <= float(max_odd)
        except Exception as e:
            print(f"[FAIL] {name} | caso invalido: {e}")
            team_a = str(c.get("team_a", ""))
            team_b = str(c.get("team_b", ""))
            market = str(c.get("market", ""))
            side = str(c.get("side", ""))
            min_odd = float(c.get("min_odd", 0.0) or 0.0)
            max_odd = float(c.get("max_odd", 0.0) or 0.0)
            odd_value = float("nan")
            ok = False
        results.append(
            CaseResult(
                name=name,
                ok=ok,
                team_a=team_a,
                team_b=team_b,
                market=market,
                side=side,
                odd_value=float(odd_value),
                min_odd=float(min_odd),
                max_odd=float(max_odd),
            )
        )

    overall_ok = all(r.ok for r in results)
    report = {
        "artifact": str(args.artifact),
        "expectations": str(args.expectations),
        "overall_ok": overall_ok,
        "cases": [
            {
                "name": r.name,
                "ok": r.ok,
                "team_a": r.team_a,
                "team_b": r.team_b,
                "market": r.market,
                "side": r.side,
                "odd_value": r.odd_value,
                "min_odd": r.min_odd,
                "max_odd": r.max_odd,
            }
            for r in results
        ],
    }

    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    for r in results:
        mark = "OK" if r.ok else "FAIL"
        print(
            f"[{mark}] {r.name} | {r.team_a} vs {r.team_b} | "
            f"{r.market} side={r.side} odd={r.odd_value:.3f} faixa=[{r.min_odd:.3f}, {r.max_odd:.3f}]"
        )

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
