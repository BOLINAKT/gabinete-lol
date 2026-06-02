from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mlcore.calibration_diagnostics import run_calibration_diagnostics
from mlcore.walkforward_report import run_walkforward
from mlcore.utils import safe_float as _f


def _resolve_csv_paths(raw_csvs: List[str], mode: str) -> List[str]:
    out: List[str] = []
    for raw in list(raw_csvs or []):
        p = Path(str(raw)).expanduser()
        if not p.is_absolute():
            p = (ROOT / p).resolve()
        if p.is_file():
            out.append(str(p))
        elif p.is_dir():
            for c in sorted(p.glob("*.csv")):
                if c.is_file():
                    out.append(str(c.resolve()))

    if out:
        return sorted(list(dict.fromkeys(out)))

    diario = ROOT / "CSV_DIARIO"
    historico = ROOT / "CSV_HISTORICO"

    if str(mode) == "full":
        cands: List[Path] = []
        if historico.exists():
            cands.extend(sorted([p for p in historico.glob("*.csv") if p.is_file()]))
        if diario.exists():
            cands.extend(sorted([p for p in diario.glob("*.csv") if p.is_file()]))
        return [str(p.resolve()) for p in cands]

    # mode=recent (default): newest CSV from CSV_DIARIO, fallback to any newest CSV.
    if diario.exists():
        cands = sorted([p for p in diario.glob("*.csv") if p.is_file()], key=lambda x: x.stat().st_mtime, reverse=True)
        if cands:
            return [str(cands[0].resolve())]
    any_csv = sorted([p for p in ROOT.glob("*.csv") if p.is_file()], key=lambda x: x.stat().st_mtime, reverse=True)
    if any_csv:
        return [str(any_csv[0].resolve())]
    return []


def _run_tests(timeout_s: int = 900) -> Dict[str, Any]:
    modules = [
        "mlcore.tests.test_tiers_core",
        "mlcore.tests.test_ml_pre_engine_core",
        "mlcore.tests.test_ml_pre_live_pipeline_core",
        "mlcore.tests.test_ml_live_pipeline_core",
        "mlcore.tests.test_hier_calibration_core",
        "mlcore.tests.test_style_matchup_core",
        "mlcore.tests.test_state_strength_core",
        "mlcore.tests.test_series_bo_core",
        "mlcore.tests.test_meta_blend_core",
        "mlcore.tests.test_runtime_tuning_core",
        "mlcore.tests.test_players_layer_weights",
        "mlcore.tests.test_calibration_diagnostics_core",
    ]
    cp = subprocess.run(
        [sys.executable, "-m", "unittest", *modules],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=int(timeout_s),
    )
    text = (cp.stdout or "") + (("\n" + cp.stderr) if cp.stderr else "")
    return {
        "ok": bool(int(cp.returncode) == 0),
        "returncode": int(cp.returncode),
        "modules": modules,
        "detail_tail": str(text[-4000:]),
    }


def _players_context_gate_from_params(params_fitted_path: Path) -> Dict[str, Any]:
    p = Path(params_fitted_path)
    if not p.exists():
        return {"ok": True, "decision": "unknown", "reasons": ["params_fitted_missing"]}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "decision": "unknown", "reasons": [f"params_read_error:{type(exc).__name__}"]}
    if not isinstance(obj, dict):
        return {"ok": False, "decision": "unknown", "reasons": ["params_invalid"]}
    fit = obj.get("players_context_fit") if isinstance(obj.get("players_context_fit"), dict) else {}
    gate = fit.get("gate") if isinstance(fit.get("gate"), dict) else {}
    decision = str(gate.get("decision") or "unknown").strip().lower() or "unknown"
    reasons = [str(x) for x in (gate.get("reasons") or []) if str(x).strip()]
    return {
        "ok": True,
        "decision": decision,
        "reasons": reasons,
        "version": str(fit.get("version") or ""),
        "ablation": (fit.get("ablation") if isinstance(fit.get("ablation"), dict) else {}),
    }


def _decision_from_metrics(*, tests_ok: bool, wf_overall: Dict[str, Any], cal_models: Dict[str, Any]) -> Dict[str, Any]:
    reasons: List[str] = []
    decision = "promote"

    if not bool(tests_ok):
        return {"decision": "reject", "reasons": ["tests_failed"]}

    wf_n = int(wf_overall.get("n_total") or 0)
    wf_ll = _f(wf_overall.get("logloss_mean"))
    wf_br = _f(wf_overall.get("brier_mean"))

    fused = cal_models.get("fused_active") if isinstance(cal_models.get("fused_active"), dict) else {}
    cal_n = int(fused.get("n") or 0)
    cal_ece = _f(fused.get("ece"))
    cal_ll = _f(fused.get("logloss"))
    cal_br = _f(fused.get("brier"))

    if wf_n < 200:
        decision = "shadow_only"
        reasons.append("wf_sample_small")
    if cal_n < 400:
        decision = "shadow_only"
        reasons.append("cal_sample_small")

    if math.isfinite(wf_ll) and wf_ll > 0.705:
        decision = "shadow_only"
        reasons.append("wf_logloss_high")
    if math.isfinite(wf_br) and wf_br > 0.252:
        decision = "shadow_only"
        reasons.append("wf_brier_high")
    if math.isfinite(cal_ece) and cal_ece > 0.040:
        decision = "shadow_only"
        reasons.append("cal_ece_high")
    if math.isfinite(cal_ll) and cal_ll > 0.705:
        decision = "shadow_only"
        reasons.append("cal_logloss_high")
    if math.isfinite(cal_br) and cal_br > 0.252:
        decision = "shadow_only"
        reasons.append("cal_brier_high")

    return {"decision": decision, "reasons": reasons}


def main() -> int:
    ap = argparse.ArgumentParser(description="ML v3 phase-0 baseline gate (tests + walkforward + calibration).")
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--players-artifact", dest="players_artifact", default="players_artifact.json")
    ap.add_argument("--csv", action="append", default=[])
    ap.add_argument("--mode", choices=["recent", "full"], default="recent", help="CSV auto-discovery mode when --csv is not set.")
    ap.add_argument("--out", default="phase0_ml_v3_baseline_report.json")
    ap.add_argument("--params-fitted", default="params_fitted.json")
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--min-train-games", type=int, default=1500)
    ap.add_argument("--k", type=float, default=26.0)
    ap.add_argument("--scale", type=float, default=400.0)
    ap.add_argument("--bins", type=int, default=10)
    ap.add_argument("--min-league-games", type=int, default=120)
    ap.add_argument("--cal-use-microseg-fitted", action="store_true", default=True)
    ap.add_argument("--cal-no-microseg-fitted", dest="cal_use_microseg_fitted", action="store_false")
    ap.add_argument("--cal-microseg-min-n", type=int, default=30)
    ap.add_argument("--cal-microseg-strength", type=float, default=0.60)
    ap.add_argument("--cal-microseg-cap-pp", type=float, default=8.0)
    ap.add_argument("--cal-microseg-hier-decay", type=float, default=0.80)
    args = ap.parse_args()

    artifact = Path(str(args.artifact)).expanduser()
    if not artifact.is_absolute():
        artifact = (ROOT / artifact).resolve()
    players_artifact = Path(str(args.players_artifact)).expanduser()
    if not players_artifact.is_absolute():
        players_artifact = (ROOT / players_artifact).resolve()
    out_path = Path(str(args.out)).expanduser()
    if not out_path.is_absolute():
        out_path = (ROOT / out_path).resolve()
    params_fitted = Path(str(args.params_fitted)).expanduser()
    if not params_fitted.is_absolute():
        params_fitted = (ROOT / params_fitted).resolve()

    csv_paths = _resolve_csv_paths(list(args.csv or []), mode=str(args.mode))
    checks: List[Dict[str, Any]] = []

    checks.append(
        {
            "check": "artifacts_exist",
            "ok": bool(artifact.exists() and players_artifact.exists()),
            "detail": {"artifact": str(artifact), "players_artifact": str(players_artifact)},
        }
    )
    checks.append({"check": "csv_paths_resolved", "ok": bool(csv_paths), "detail": {"count": len(csv_paths), "paths": csv_paths[:10]}})

    tests = {"ok": True, "skipped": True}
    if not bool(args.skip_tests):
        tests = _run_tests(timeout_s=900)
        tests["skipped"] = False
    checks.append({"check": "targeted_tests", "ok": bool(tests.get("ok", False)), "detail": tests})
    players_ctx_gate = _players_context_gate_from_params(params_fitted)
    checks.append(
        {
            "check": "players_context_gate",
            "ok": bool(players_ctx_gate.get("ok", False)),
            "detail": {
                "params_fitted": str(params_fitted),
                "decision": str(players_ctx_gate.get("decision") or "unknown"),
                "reasons": list(players_ctx_gate.get("reasons") or []),
                "version": str(players_ctx_gate.get("version") or ""),
                "ablation": players_ctx_gate.get("ablation") if isinstance(players_ctx_gate.get("ablation"), dict) else {},
            },
        }
    )

    wf: Dict[str, Any] = {}
    cal: Dict[str, Any] = {}
    run_error = None
    try:
        if not csv_paths:
            raise RuntimeError("no_csv_paths")
        if not artifact.exists():
            raise RuntimeError("artifact_missing")
        if not players_artifact.exists():
            raise RuntimeError("players_artifact_missing")
        wf = run_walkforward(
            csv_paths,
            min_train_games=int(args.min_train_games),
            k=float(args.k),
            scale=float(args.scale),
        )
        cal = run_calibration_diagnostics(
            artifact_path=str(artifact),
            players_artifact_path=str(players_artifact),
            csv_paths=csv_paths,
            team_scale=1.0,
            players_scale=1.0,
            bins=int(args.bins),
            min_league_games=int(args.min_league_games),
            params_fitted_path=str(params_fitted),
            use_microseg_fitted=bool(args.cal_use_microseg_fitted),
            microseg_min_n=int(args.cal_microseg_min_n),
            microseg_strength=float(args.cal_microseg_strength),
            microseg_cap_pp=float(args.cal_microseg_cap_pp),
            microseg_hierarchical=True,
            microseg_hier_decay=float(args.cal_microseg_hier_decay),
        )
    except Exception as exc:
        run_error = f"{type(exc).__name__}: {exc}"

    checks.append({"check": "walkforward_run", "ok": bool(isinstance(wf, dict) and (not wf.get("error"))), "detail": wf if wf else run_error})
    checks.append({"check": "calibration_run", "ok": bool(isinstance(cal, dict) and (not cal.get("error"))), "detail": cal if cal else run_error})

    if run_error is not None:
        gate = {"decision": "reject", "reasons": ["runtime_error", str(run_error)]}
    else:
        wf_overall = (wf.get("overall") if isinstance(wf.get("overall"), dict) else {})
        cal_models = (cal.get("models") if isinstance(cal.get("models"), dict) else {})
        gate = _decision_from_metrics(
            tests_ok=bool(tests.get("ok", False)),
            wf_overall=wf_overall,
            cal_models=cal_models,
        )

    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {
            "artifact": str(artifact),
            "players_artifact": str(players_artifact),
            "params_fitted": str(params_fitted),
            "csv_paths": list(csv_paths),
            "mode": str(args.mode),
            "skip_tests": bool(args.skip_tests),
            "min_train_games": int(args.min_train_games),
            "k": float(args.k),
            "scale": float(args.scale),
            "bins": int(args.bins),
            "min_league_games": int(args.min_league_games),
            "cal_use_microseg_fitted": bool(args.cal_use_microseg_fitted),
            "cal_microseg_min_n": int(args.cal_microseg_min_n),
            "cal_microseg_strength": float(args.cal_microseg_strength),
            "cal_microseg_cap_pp": float(args.cal_microseg_cap_pp),
            "cal_microseg_hier_decay": float(args.cal_microseg_hier_decay),
        },
        "checks": checks,
        "walkforward": wf,
        "calibration": cal,
        "players_context_gate": players_ctx_gate,
        "decision": str(gate.get("decision") or "unknown"),
        "reasons": list(gate.get("reasons") or []),
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    dec = str(report.get("decision") or "unknown")
    print(f"OK: phase0 ml v3 baseline -> {out_path.name} | decision={dec}")
    if dec == "promote":
        return 0
    if dec == "shadow_only":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
