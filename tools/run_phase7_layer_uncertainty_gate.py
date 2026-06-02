from __future__ import annotations

import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "phase7_layer_uncertainty_report.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.layer_uncertainty_core import apply_layer_uncertainty_live


def _run_tests() -> Dict[str, Any]:
    cp = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "mlcore/tests/test_layer_uncertainty_core.py"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=240,
    )
    out = (cp.stdout or "") + (("\n" + cp.stderr) if cp.stderr else "")
    if int(cp.returncode) == 0:
        return {"ok": True, "runner": "pytest", "detail": out[-1000:]}
    if "No module named pytest" in out:
        cu = subprocess.run(
            [sys.executable, "-m", "unittest", "mlcore.tests.test_layer_uncertainty_core"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=240,
        )
        out_u = (cu.stdout or "") + (("\n" + cu.stderr) if cu.stderr else "")
        return {"ok": int(cu.returncode) == 0, "runner": "unittest", "detail": out_u[-1000:]}
    return {"ok": False, "runner": "pytest", "detail": out[-1000:]}


def main() -> int:
    checks: List[Dict[str, Any]] = []
    reasons: List[str] = []
    decision = "promote"

    # 1) tests
    t = _run_tests()
    checks.append({"check": "layer_uncertainty_tests", "ok": bool(t.get("ok")), "detail": t})
    if not bool(t.get("ok")):
        decision = "reject"
        reasons.append("tests_failed")

    # 2) contract checks for per-layer uncertainty and actionability
    out_mid = apply_layer_uncertainty_live(
        p_map_in=0.60,
        p_series_in=0.68,
        bo=5,
        interregional=False,
        playoffs=True,
        patch_status="ok",
        n_team_eff=40,
        n_players_eff=24,
        state_areal_live={"applied": True, "diff_pp": 1.4, "method": "areal"},
        state_alite_live={"applied": True, "diff_pp": 1.0, "method": "alite"},
        style_b_live={"applied": True, "diff_pp": 0.8, "method": "style"},
        rank_sos_live={"applied": True, "diff_pp": 1.1, "method": "sos"},
        roster_continuity_live={"applied": True, "diff_pp": 0.6, "method": "roster"},
        hier_calibration_live={"applied": True, "diff_pp": 0.5, "method": "hier"},
        series_bo_dplite_live={"applied": True, "diff_pp": 1.2, "method": "series"},
        meta_c_live={"applied": True, "diff_pp": 1.8, "method": "meta"},
    )
    ok_contract = (
        isinstance(out_mid, dict)
        and str(out_mid.get("method")) == "layer_uncertainty_v2"
        and isinstance(out_mid.get("layer_scores"), dict)
        and len(out_mid.get("layer_scores") or {}) >= 4
        and isinstance(out_mid.get("dominant_risk_layers"), list)
        and str(out_mid.get("actionability_zone")) in {"low", "medium", "high"}
        and isinstance(out_mid.get("actionability_note"), str)
    )
    checks.append({"check": "contract_v2_fields", "ok": bool(ok_contract), "detail": out_mid})
    if not ok_contract and decision != "reject":
        decision = "shadow_only"
        reasons.append("contract_missing_fields")

    # 3) conservative shrink behavior
    out_low_ev = apply_layer_uncertainty_live(
        p_map_in=0.60,
        p_series_in=0.68,
        bo=3,
        interregional=True,
        playoffs=False,
        patch_status="warn",
        n_team_eff=4,
        n_players_eff=1,
        state_areal_live={"applied": False, "reason": "missing"},
        style_b_live={"applied": False, "reason": "missing"},
        rank_sos_live={"applied": False, "reason": "missing"},
        meta_c_live={"applied": False, "reason": "missing"},
    )
    out_hi_ev = apply_layer_uncertainty_live(
        p_map_in=0.60,
        p_series_in=0.68,
        bo=3,
        interregional=False,
        playoffs=False,
        patch_status="ok",
        n_team_eff=60,
        n_players_eff=32,
        state_areal_live={"applied": True, "diff_pp": 0.2},
        style_b_live={"applied": True, "diff_pp": 0.2},
        rank_sos_live={"applied": True, "diff_pp": 0.2},
        meta_c_live={"applied": True, "diff_pp": 0.3},
    )
    u_low = float(out_low_ev.get("uncertainty_score") or float("nan"))
    u_hi = float(out_hi_ev.get("uncertainty_score") or float("nan"))
    s_low = float(out_low_ev.get("shrink_map") or float("nan"))
    s_hi = float(out_hi_ev.get("shrink_map") or float("nan"))
    ok_cons = (
        math.isfinite(u_low)
        and math.isfinite(u_hi)
        and math.isfinite(s_low)
        and math.isfinite(s_hi)
        and u_low >= u_hi
        and s_low >= s_hi
    )
    checks.append(
        {
            "check": "conservative_by_evidence",
            "ok": bool(ok_cons),
            "detail": {
                "u_low_evidence": u_low,
                "u_high_evidence": u_hi,
                "shrink_low_evidence": s_low,
                "shrink_high_evidence": s_hi,
            },
        }
    )
    if not ok_cons and decision != "reject":
        decision = "shadow_only"
        reasons.append("uncertainty_not_conservative")

    rep = {
        "version": "phase7_layer_uncertainty_gate_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decision": decision,
        "reasons": reasons,
        "summary": {
            "ok": int(sum(1 for c in checks if bool(c.get("ok")))),
            "total": len(checks),
            "method": str(out_mid.get("method") if isinstance(out_mid, dict) else ""),
            "actionability_zone_mid": str(out_mid.get("actionability_zone") if isinstance(out_mid, dict) else ""),
        },
        "checks": checks,
    }
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"OK: phase7 gate -> {OUT.name} | decision={decision} | "
        f"ok={rep['summary']['ok']}/{rep['summary']['total']}"
    )
    return 0 if decision == "promote" else (1 if decision == "shadow_only" else 2)


if __name__ == "__main__":
    raise SystemExit(main())

