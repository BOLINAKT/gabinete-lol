from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mlcore.artifact import MLArtifact
from tools.anchor_regression_suite import _odd_for_case_app
from tools.validate_key_matchups import _odd_for_case


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8-sig"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _case_tolerance_pct(case: Dict[str, Any], default_tol: float) -> float:
    raw = case.get("tolerance_pct", default_tol)
    try:
        val = float(raw)
    except Exception:
        val = float(default_tol)
    if not math.isfinite(val):
        val = float(default_tol)
    return max(0.0, min(1.0, float(val)))


def _decide(ok_count: int, fail_count: int, total: int) -> str:
    if total <= 0:
        return "shadow_only"
    if fail_count == 0:
        return "promote"
    if fail_count <= max(1, int(total * 0.2)):
        return "shadow_only"
    return "reject"


def _evaluate_case(
    case: Dict[str, Any],
    odd_value: float,
    *,
    default_tol_pct: float,
    min_abs_delta: float,
) -> Dict[str, Any]:
    baseline = float(case.get("baseline_odd") or 0.0)
    tol_pct = _case_tolerance_pct(case, default_tol=default_tol_pct)
    delta_abs = abs(float(odd_value) - baseline)
    delta_pct = (delta_abs / baseline) if baseline > 0 else float("inf")
    max_allowed = max(float(min_abs_delta), abs(float(baseline)) * tol_pct)
    ok = bool(math.isfinite(odd_value) and baseline > 0 and delta_abs <= max_allowed)
    return {
        "ok": ok,
        "odd_value": float(odd_value),
        "baseline_odd": float(baseline),
        "delta_abs": float(delta_abs),
        "delta_pct": float(delta_pct),
        "max_allowed_delta_abs": float(max_allowed),
        "tolerance_pct": float(tol_pct),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Delta-based odds guardrail using real app odds or artifact odds.")
    ap.add_argument("--mode", choices=["app", "artifact"], default="app")
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--expectations", default="ops/key_matchup_expectations.json")
    ap.add_argument("--csv", default="", help="Optional CSV override when --mode=app.")
    ap.add_argument("--timeout", type=int, default=300, help="Per-case timeout (s) for --mode=app.")
    ap.add_argument("--default-tolerance-pct", type=float, default=0.12)
    ap.add_argument("--min-abs-delta", type=float, default=0.03)
    ap.add_argument("--out", default="odd_delta_guardrail_report.json")
    args = ap.parse_args()

    os.chdir(ROOT)
    expectations_path = Path(str(args.expectations))
    exp = _read_json(expectations_path)
    cases = list(exp.get("cases", []) or [])

    use_artifact = str(args.mode).strip().lower() == "artifact"
    art = MLArtifact.load_json(str(args.artifact)) if use_artifact else None

    csv_override = str(args.csv or "").strip()
    rows: List[Dict[str, Any]] = []
    ok_count = 0
    fail_count = 0
    for c in cases:
        name = str(c.get("name", "")).strip() or f"{c.get('team_a')} vs {c.get('team_b')}"
        team_a = str(c.get("team_a", ""))
        team_b = str(c.get("team_b", ""))
        market = str(c.get("market", "bo5"))
        side = str(c.get("side", "a"))
        try:
            if use_artifact:
                odd_value = float(_odd_for_case(art, team_a, team_b, market, side))
            else:
                odd_value = float(
                    _odd_for_case_app(
                        ROOT,
                        team_a,
                        team_b,
                        market,
                        side,
                        int(args.timeout),
                        csv_override=(csv_override or None),
                        artifact_override=str(args.artifact),
                    )
                )
            eval_row = _evaluate_case(
                c,
                odd_value,
                default_tol_pct=float(args.default_tolerance_pct),
                min_abs_delta=float(args.min_abs_delta),
            )
            err = ""
        except Exception as exc:
            eval_row = _evaluate_case(
                c,
                float("nan"),
                default_tol_pct=float(args.default_tolerance_pct),
                min_abs_delta=float(args.min_abs_delta),
            )
            eval_row["ok"] = False
            err = str(exc)

        ok = bool(eval_row.get("ok"))
        ok_count += int(ok)
        fail_count += int(not ok)
        rows.append(
            {
                "name": name,
                "team_a": team_a,
                "team_b": team_b,
                "market": market,
                "side": side,
                "ok": ok,
                "error": err,
                **eval_row,
            }
        )

    total = len(rows)
    decision = _decide(ok_count, fail_count, total)
    report = {
        "version": "odd_delta_guardrail_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": str(args.mode),
        "artifact": str(args.artifact),
        "csv_override": csv_override,
        "expectations": str(expectations_path),
        "summary": {
            "total": int(total),
            "ok": int(ok_count),
            "fail": int(fail_count),
            "pass_rate": (float(ok_count) / float(total)) if total else 0.0,
        },
        "decision": decision,
        "cases": rows,
    }
    out_path = ROOT / str(args.out)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"OK: odd delta guardrail saved -> {out_path.name} | "
        f"decision={decision} ok={ok_count}/{total} fail={fail_count}"
    )
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
