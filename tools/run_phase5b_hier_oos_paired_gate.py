from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from mlcore.utils import safe_float as _f
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPARE = ROOT / "hier_calibration_pre_post_compare.json"
DEFAULT_BASELINE = ROOT / "ml_confidence_baseline.json"
OUT = ROOT / "phase5b_hier_oos_paired_report.json"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            obj = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                return obj
    except Exception:
        pass
    return {}


def _check_non_inferior(
    *,
    name: str,
    gain: float,
    tol: float,
    metric_label: str,
    min_n: int,
    n: int,
) -> Dict[str, Any]:
    considered = int(n) >= int(min_n)
    ok = (not considered) or (gain >= -abs(float(tol)))
    return {
        "check": name,
        "ok": bool(ok),
        "detail": {
            "metric": str(metric_label),
            "gain": (float(gain) if math.isfinite(gain) else None),
            "tol_non_inferior": float(abs(float(tol))),
            "considered": bool(considered),
            "n": int(n),
            "min_n": int(min_n),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 5B gate: paired OOS compare for hier calibration (pre-like vs post).")
    ap.add_argument("--compare", default=str(DEFAULT_COMPARE), help="Path to hier_calibration_pre_post_compare.json")
    ap.add_argument("--baseline", default=str(DEFAULT_BASELINE), help="Path to ml_confidence_baseline.json")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    compare_path = Path(str(args.compare)).expanduser()
    baseline_path = Path(str(args.baseline)).expanduser()
    out_path = Path(str(args.out)).expanduser()

    cmp = _read_json(compare_path)
    base = _read_json(baseline_path)
    checks: List[Dict[str, Any]] = []
    reasons: List[str] = []
    decision = "promote"

    ok_cmp = bool(cmp)
    checks.append({"check": "compare_report_exists", "ok": ok_cmp, "detail": str(compare_path)})
    if not ok_cmp:
        decision = "reject"
        reasons.append("compare_report_missing_or_invalid")

    ok_base = bool(base)
    checks.append({"check": "baseline_exists", "ok": ok_base, "detail": str(baseline_path)})
    if not ok_base:
        decision = "reject"
        reasons.append("baseline_missing_or_invalid")

    g = cmp.get("global") if isinstance(cmp.get("global"), dict) else {}
    rows_total = int(cmp.get("rows_total") or 0)
    th = base.get("thresholds") if isinstance(base.get("thresholds"), dict) else {}
    tol_ll = max(1e-6, min(0.02, _f(th.get("oos_logloss_tol"), 0.0015)))
    tol_br = max(1e-6, min(0.02, _f(th.get("oos_brier_tol"), 0.0010)))
    tol_ece = max(1e-6, min(0.02, _f(th.get("oos_ece_tol"), 0.0015)))
    min_rows_global = max(400, int(_f(th.get("oos_min_rows_global"), 1800.0)))

    gain_ll = _f(g.get("gain_logloss"))
    gain_br = _f(g.get("gain_brier"))
    gain_ece = _f(g.get("gain_ece"))
    n_global = int(((g.get("post") or {}).get("n")) if isinstance(g.get("post"), dict) else rows_total)

    checks.append(
        {
            "check": "rows_global_sufficient",
            "ok": bool(n_global >= min_rows_global),
            "detail": {"n_global": int(n_global), "min_rows_global": int(min_rows_global)},
        }
    )

    checks.append(
        _check_non_inferior(
            name="global_non_inferior_logloss",
            gain=gain_ll,
            tol=tol_ll,
            metric_label="logloss",
            min_n=min_rows_global,
            n=n_global,
        )
    )
    checks.append(
        _check_non_inferior(
            name="global_non_inferior_brier",
            gain=gain_br,
            tol=tol_br,
            metric_label="brier",
            min_n=min_rows_global,
            n=n_global,
        )
    )
    checks.append(
        _check_non_inferior(
            name="global_non_inferior_ece",
            gain=gain_ece,
            tol=tol_ece,
            metric_label="ece",
            min_n=min_rows_global,
            n=n_global,
        )
    )

    # Require at least one practical improvement if sample is sufficient.
    # This avoids promoting a no-op configuration.
    improve_ece_min = max(0.0, min(0.01, _f(th.get("oos_ece_improve_min"), 0.0005)))
    has_practical_gain = bool(
        (math.isfinite(gain_ll) and gain_ll > 0.0)
        or (math.isfinite(gain_br) and gain_br > 0.0)
        or (math.isfinite(gain_ece) and gain_ece >= improve_ece_min)
    )
    checks.append(
        {
            "check": "global_has_practical_gain",
            "ok": bool((n_global < min_rows_global) or has_practical_gain),
            "detail": {
                "gain_logloss": (float(gain_ll) if math.isfinite(gain_ll) else None),
                "gain_brier": (float(gain_br) if math.isfinite(gain_br) else None),
                "gain_ece": (float(gain_ece) if math.isfinite(gain_ece) else None),
                "ece_improve_min": float(improve_ece_min),
            },
        }
    )

    by_cls = cmp.get("by_segment_class") if isinstance(cmp.get("by_segment_class"), dict) else {}
    seg_specs = [
        ("same_major", 300),
        ("same_minor", 180),
    ]
    seg_tol_mult = max(1.0, min(2.0, _f(th.get("oos_segment_tol_mult"), 1.40)))
    for seg_name, seg_min_n in seg_specs:
        row = by_cls.get(seg_name) if isinstance(by_cls.get(seg_name), dict) else {}
        n_seg = int(row.get("n") or 0)
        gll = _f(row.get("gain_logloss"))
        gbr = _f(row.get("gain_brier"))
        ge = _f(row.get("gain_ece"))
        checks.append(
            _check_non_inferior(
                name=f"{seg_name}_non_inferior_logloss",
                gain=gll,
                tol=float(tol_ll * seg_tol_mult),
                metric_label="logloss",
                min_n=int(seg_min_n),
                n=n_seg,
            )
        )
        checks.append(
            _check_non_inferior(
                name=f"{seg_name}_non_inferior_brier",
                gain=gbr,
                tol=float(tol_br * seg_tol_mult),
                metric_label="brier",
                min_n=int(seg_min_n),
                n=n_seg,
            )
        )
        checks.append(
            _check_non_inferior(
                name=f"{seg_name}_non_inferior_ece",
                gain=ge,
                tol=float(tol_ece * seg_tol_mult),
                metric_label="ece",
                min_n=int(seg_min_n),
                n=n_seg,
            )
        )

    ok_count = int(sum(1 for c in checks if bool(c.get("ok"))))
    total_count = len(checks)
    hard_fail = any(
        (not bool(c.get("ok")))
        and str(c.get("check") or "").startswith("global_non_inferior_")
        for c in checks
    )
    soft_fail = any(not bool(c.get("ok")) for c in checks) and (not hard_fail)

    if hard_fail:
        decision = "reject"
        reasons.append("global_non_inferior_failed")
    elif soft_fail:
        decision = "shadow_only"
        reasons.append("segment_or_gain_guard_failed")
    else:
        decision = "promote"

    rep = {
        "version": "phase5b_hier_oos_paired_gate_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decision": str(decision),
        "reasons": reasons,
        "summary": {
            "ok": int(ok_count),
            "total": int(total_count),
            "rows_total": int(rows_total),
            "rows_global": int(n_global),
            "gain_logloss": (float(gain_ll) if math.isfinite(gain_ll) else None),
            "gain_brier": (float(gain_br) if math.isfinite(gain_br) else None),
            "gain_ece": (float(gain_ece) if math.isfinite(gain_ece) else None),
        },
        "thresholds": {
            "oos_logloss_tol": float(tol_ll),
            "oos_brier_tol": float(tol_br),
            "oos_ece_tol": float(tol_ece),
            "oos_min_rows_global": int(min_rows_global),
            "oos_segment_tol_mult": float(seg_tol_mult),
            "oos_ece_improve_min": float(improve_ece_min),
        },
        "checks": checks,
    }
    out_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"OK: phase5b paired gate -> {out_path.name} | decision={decision} | "
        f"ok={ok_count}/{total_count}"
    )
    return 0 if decision == "promote" else (1 if decision == "shadow_only" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
