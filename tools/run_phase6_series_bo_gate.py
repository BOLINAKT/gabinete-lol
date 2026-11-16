from __future__ import annotations

import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "phase6_series_bo_report.json"
PARAMS = ROOT / "params_fitted.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.series_bo_core import apply_series_bo_dplite_live, enforce_series_economic_coherence
from mlcore.bo import p_series_from_pmap, prob_win_series


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _scenario(name: str, **kwargs: Any) -> Dict[str, Any]:
    out = apply_series_bo_dplite_live(**kwargs)
    return {"name": name, "out": out}


def main() -> int:
    checks: List[Dict[str, Any]] = []
    reasons: List[str] = []
    decision = "promote"
    params_fit = _read_json(PARAMS)

    # 0) params_fitted must provide Series BO tuning config
    sbo_cfg = params_fit.get("series_bo_dplite_tuning") if isinstance(params_fit, dict) else {}
    sbo_global = (sbo_cfg.get("global") if isinstance(sbo_cfg, dict) else {}) or {}
    bo3_ok = isinstance(sbo_global.get("bo3"), dict) and bool((sbo_global.get("bo3") or {}))
    bo5_ok = isinstance(sbo_global.get("bo5"), dict) and bool((sbo_global.get("bo5") or {}))
    ok_cfg = bool(isinstance(sbo_cfg, dict) and bo3_ok and bo5_ok and not sbo_cfg.get("error"))
    checks.append(
        {
            "check": "params_series_bo_dplite_tuning_present",
            "ok": ok_cfg,
            "detail": {
                "params_path": str(PARAMS),
                "has_cfg": isinstance(sbo_cfg, dict),
                "bo3_present": bool(bo3_ok),
                "bo5_present": bool(bo5_ok),
                "version": (sbo_cfg.get("version") if isinstance(sbo_cfg, dict) else None),
            },
        }
    )
    if not ok_cfg:
        decision = "shadow_only"
        reasons.append("series_bo_tuning_missing_in_params")

    # 1) unit tests for core
    cp = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "mlcore/tests/test_series_bo_core.py"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=240,
    )
    out_py = (cp.stdout or "") + (("\n" + cp.stderr) if cp.stderr else "")
    ok_pytest = int(cp.returncode) == 0
    if not ok_pytest and "No module named pytest" in out_py:
        cp_u = subprocess.run(
            [sys.executable, "-m", "unittest", "mlcore.tests.test_series_bo_core"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=240,
        )
        out_u = (cp_u.stdout or "") + (("\n" + cp_u.stderr) if cp_u.stderr else "")
        ok_u = int(cp_u.returncode) == 0
        checks.append(
            {
                "check": "unittest_series_bo_core_fallback",
                "ok": ok_u,
                "detail": out_u[-1000:],
            }
        )
        if not ok_u:
            decision = "reject"
            reasons.append("series_core_tests_failed")
    else:
        checks.append({"check": "pytest_series_bo_core", "ok": ok_pytest, "detail": out_py[-1000:]})
        if not ok_pytest:
            decision = "reject"
            reasons.append("series_core_tests_failed")

    # 2) scenario checks (bounds / method / caps / direction sanity)
    s_base = _scenario(
        "bo5_same_league",
        p_map=0.58,
        p_series_in=float(prob_win_series(0.58, 5)),
        bo=5,
        same_league=True,
        interregional=False,
        playoffs=True,
        side_bias_pp=2.5,
        style_volatility=0.15,
        layer_confidence_score=72.0,
        n_team_eff=48,
        n_players_eff=26,
        league_hint="LCK",
        tuning_cfg=sbo_cfg,
    )["out"]
    ok_base = (
        isinstance(s_base, dict)
        and str(s_base.get("method")) in {"series_bo_v5_live"}
        and str(s_base.get("anchor_mode")) == "dp_sideaware_v5"
        and isinstance(s_base.get("dp"), dict)
        and math.isfinite(float(s_base.get("p_after", float("nan")) or float("nan")))
        and 0.0 < float(s_base.get("p_after")) < 1.0
    )
    checks.append({"check": "base_method_and_bounds", "ok": bool(ok_base), "detail": s_base})
    if not ok_base and decision != "reject":
        decision = "shadow_only"
        reasons.append("base_invalid")

    _dp = dict(s_base.get("dp") or {})
    _mp = dict(_dp.get("map_play_prob") or {})
    _wm = dict(_dp.get("map_win_if_played") or {})
    _exp = _dp.get("expected_maps")
    _dec = _dp.get("decider_reach_prob")
    ok_diag = (
        math.isfinite(float(_exp or float("nan")))
        and 3.0 <= float(_exp) <= 5.0
        and math.isfinite(float(_dec or float("nan")))
        and 0.0 <= float(_dec) <= 1.0
        and math.isfinite(float(_dp.get("decider_side_revert") or float("nan")))
        and 0.0 <= float(_dp.get("decider_side_revert") or 0.0) <= 1.0
        and math.isfinite(float(_dp.get("series_corr_sigma") or float("nan")))
        and 0.0 <= float(_dp.get("series_corr_sigma") or 0.0) <= 0.35
        and all(k in _mp for k in ("m1", "m2", "m3", "m4", "m5"))
        and all(k in _wm for k in ("m1", "m2", "m3", "m4", "m5"))
        and abs(float(_mp.get("m1") or 0.0) - 1.0) <= 1e-9
        and float(_mp.get("m1") or 0.0) >= float(_mp.get("m2") or 0.0) >= float(_mp.get("m3") or 0.0)
        and float(_mp.get("m3") or 0.0) >= float(_mp.get("m4") or 0.0) >= float(_mp.get("m5") or 0.0)
        and abs(float(_mp.get("m5") or 0.0) - float(_dec or 0.0)) <= 1e-9
    )
    checks.append(
        {
            "check": "dynamic_diag_map_by_map",
            "ok": bool(ok_diag),
            "detail": {
                "expected_maps": _exp,
                "decider_reach_prob": _dec,
                "map_play_prob": _mp,
                "map_win_if_played": _wm,
            },
        }
    )
    if not ok_diag and decision != "reject":
        decision = "shadow_only"
        reasons.append("dynamic_diag_invalid")

    s_same = _scenario(
        "same_league",
        p_map=0.62,
        p_series_in=0.72,
        bo=5,
        same_league=True,
        interregional=False,
        playoffs=False,
        side_bias_pp=3.0,
        style_volatility=0.10,
        layer_confidence_score=80.0,
        n_team_eff=60,
        n_players_eff=35,
        league_hint="LPL",
        tuning_cfg=sbo_cfg,
    )["out"]
    s_inter = _scenario(
        "interregional",
        p_map=0.62,
        p_series_in=0.72,
        bo=5,
        same_league=False,
        interregional=True,
        playoffs=False,
        side_bias_pp=3.0,
        style_volatility=0.10,
        layer_confidence_score=80.0,
        n_team_eff=60,
        n_players_eff=35,
        league_hint="LPL",
        tuning_cfg=sbo_cfg,
    )["out"]
    ok_damp = (
        float(s_inter.get("weight", 0.0) or 0.0) <= float(s_same.get("weight", 0.0) or 0.0) + 1e-12
        and float(s_inter.get("cap_pp", 0.0) or 0.0) <= float(s_same.get("cap_pp", 0.0) or 0.0) + 1e-12
    )
    checks.append(
        {
            "check": "interregional_damp",
            "ok": bool(ok_damp),
            "detail": {
                "same_weight": s_same.get("weight"),
                "inter_weight": s_inter.get("weight"),
                "same_cap": s_same.get("cap_pp"),
                "inter_cap": s_inter.get("cap_pp"),
            },
        }
    )
    if not ok_damp and decision != "reject":
        decision = "shadow_only"
        reasons.append("interregional_not_damped")

    # 3) economic coherence guard (BO coherence and max drift)
    coh_fav = enforce_series_economic_coherence(
        p_map=0.58,
        p_series=0.52,
        bo=5,
    )
    p_bo3_ref = float(p_series_from_pmap(0.58, 3))
    p_after_fav = float(coh_fav.get("p_series_after") or float("nan"))
    ok_coh_fav = (
        bool(coh_fav.get("applied"))
        and math.isfinite(p_after_fav)
        and p_after_fav >= (max(0.58, p_bo3_ref) - 1e-9)
    )
    checks.append(
        {
            "check": "economic_coherence_favorite_direction",
            "ok": bool(ok_coh_fav),
            "detail": {**coh_fav, "p_bo3_ref": p_bo3_ref},
        }
    )
    if not ok_coh_fav and decision != "reject":
        decision = "shadow_only"
        reasons.append("economic_coherence_favorite_invalid")

    coh_cap = enforce_series_economic_coherence(
        p_map=0.52,
        p_series=0.90,
        bo=3,
        max_dev_pp=8.0,
    )
    p_after_cap = float(coh_cap.get("p_series_after") or float("nan"))
    p_target_cap = float(coh_cap.get("p_target") or float("nan"))
    ok_coh_cap = (
        bool(coh_cap.get("applied"))
        and math.isfinite(p_after_cap)
        and math.isfinite(p_target_cap)
        and abs(p_after_cap - p_target_cap) <= 0.080001
    )
    checks.append(
        {
            "check": "economic_coherence_max_drift_cap",
            "ok": bool(ok_coh_cap),
            "detail": coh_cap,
        }
    )
    if not ok_coh_cap and decision != "reject":
        decision = "shadow_only"
        reasons.append("economic_coherence_cap_invalid")

    # 4) consistency with bo1 noop and cap
    s_bo1 = _scenario(
        "bo1_noop",
        p_map=0.56,
        p_series_in=0.56,
        bo=1,
        same_league=True,
        interregional=False,
    )["out"]
    ok_bo1 = (not bool(s_bo1.get("applied", False))) and str(s_bo1.get("reason")) == "bo1_noop"
    checks.append({"check": "bo1_noop", "ok": bool(ok_bo1), "detail": s_bo1})
    if not ok_bo1 and decision != "reject":
        decision = "shadow_only"
        reasons.append("bo1_behavior_invalid")

    rep = {
        "version": "phase6_series_bo_gate_v3",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decision": decision,
        "reasons": reasons,
        "summary": {
            "ok": int(sum(1 for c in checks if bool(c.get("ok")))),
            "total": len(checks),
            "method": str(s_base.get("method") if isinstance(s_base, dict) else ""),
            "anchor_mode": str(s_base.get("anchor_mode") if isinstance(s_base, dict) else ""),
            "expected_maps": (_dp.get("expected_maps") if isinstance(_dp, dict) else None),
            "decider_reach_prob": (_dp.get("decider_reach_prob") if isinstance(_dp, dict) else None),
        },
        "checks": checks,
    }
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"OK: phase6 gate -> {OUT.name} | decision={decision} | "
        f"ok={rep['summary']['ok']}/{rep['summary']['total']}"
    )
    return 0 if decision == "promote" else (1 if decision == "shadow_only" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
