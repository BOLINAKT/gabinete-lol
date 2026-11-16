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
OUT = ROOT / "phase9_players_report.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mlcore.calibration_diagnostics import run_calibration_diagnostics
from mlcore.layer_validation import run_layer_validation
from mlcore.utils import safe_float as _f


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            obj = json.loads(path.read_text(encoding="utf-8"))
            return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}
    return {}


def _norm_dec(v: Any) -> str:
    s = str(v or "").strip().lower()
    return s if s in {"promote", "shadow_only", "reject"} else "unknown"


def _run_tests() -> Dict[str, Any]:
    mod_list = [
        "mlcore.tests.test_players_layer_weights",
        "mlcore.tests.test_ml_pre_engine_core",
        "mlcore.tests.test_ml_pre_pipeline_core",
    ]
    cp = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "mlcore/tests/test_players_layer_weights.py", "mlcore/tests/test_ml_pre_engine_core.py", "mlcore/tests/test_ml_pre_pipeline_core.py"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=600,
    )
    out = (cp.stdout or "") + (("\n" + cp.stderr) if cp.stderr else "")
    if int(cp.returncode) == 0:
        return {"ok": True, "runner": "pytest", "detail": out[-3000:]}
    if "No module named pytest" in out:
        cu = subprocess.run(
            [sys.executable, "-m", "unittest", *mod_list],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=600,
        )
        out_u = (cu.stdout or "") + (("\n" + cu.stderr) if cu.stderr else "")
        return {"ok": int(cu.returncode) == 0, "runner": "unittest", "detail": out_u[-3000:]}
    return {"ok": False, "runner": "pytest", "detail": out[-3000:]}


def _resolve_csv_paths(args_csv: List[str]) -> List[str]:
    out: List[str] = []
    for raw in list(args_csv or []):
        p = Path(str(raw)).expanduser()
        if not p.is_absolute():
            p = (ROOT / p).resolve()
        if p.exists() and p.is_file():
            out.append(str(p))
    if out:
        return out

    for folder in [ROOT / "CSV_DIARIO", ROOT / "CSV"]:
        if folder.exists() and folder.is_dir():
            for p in sorted(folder.glob("*.csv")):
                out.append(str(p.resolve()))
    # Keep deterministic order and avoid accidental duplicates.
    uniq: List[str] = []
    seen = set()
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def _check_non_inferior(name: str, gain: float, tol: float, n: int, min_n: int, metric: str) -> Dict[str, Any]:
    considered = int(n) >= int(min_n)
    ok = (not considered) or (math.isfinite(float(gain)) and float(gain) >= -abs(float(tol)))
    return {
        "check": str(name),
        "ok": bool(ok),
        "detail": {
            "metric": str(metric),
            "gain": (float(gain) if math.isfinite(float(gain)) else None),
            "tol_non_inferior": float(abs(float(tol))),
            "n": int(n),
            "min_n": int(min_n),
            "considered": bool(considered),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 9 gate: players layer validation + calibration diagnostics.")
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--players-artifact", dest="players_artifact", default="players_artifact.json")
    ap.add_argument("--csv", action="append", default=[])
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--skip-runs", action="store_true", help="Only read existing phase9 report from --out.")
    ap.add_argument("--min-train-games", type=int, default=1500)
    ap.add_argument("--min-global-samples", type=int, default=1200)
    ap.add_argument("--min-league-games", type=int, default=100)
    ap.add_argument("--min-leagues-covered", type=int, default=3)
    ap.add_argument("--tol-logloss", type=float, default=0.0015)
    ap.add_argument("--tol-brier", type=float, default=0.0010)
    ap.add_argument("--tol-ece", type=float, default=0.0020)
    ap.add_argument("--ece-improve-min", type=float, default=0.0003)
    args = ap.parse_args()

    out_path = Path(str(args.out)).expanduser()
    if not out_path.is_absolute():
        out_path = (ROOT / out_path).resolve()

    if bool(args.skip_runs):
        rep = _read_json(out_path)
        dec = _norm_dec(rep.get("decision")) if isinstance(rep, dict) else "unknown"
        print(f"OK: phase9 players gate (skip-runs) -> {out_path.name} | decision={dec}")
        return 0 if dec == "promote" else (1 if dec == "shadow_only" else 2)

    artifact_path = Path(str(args.artifact)).expanduser()
    if not artifact_path.is_absolute():
        artifact_path = (ROOT / artifact_path).resolve()
    players_artifact_path = Path(str(args.players_artifact)).expanduser()
    if not players_artifact_path.is_absolute():
        players_artifact_path = (ROOT / players_artifact_path).resolve()

    csv_paths = _resolve_csv_paths(list(args.csv or []))
    checks: List[Dict[str, Any]] = []
    reasons: List[str] = []
    decision = "promote"

    if not bool(args.skip_tests):
        t = _run_tests()
        checks.append({"check": "players_tests", "ok": bool(t.get("ok")), "detail": t})
        if not bool(t.get("ok")):
            decision = "reject"
            reasons.append("tests_failed")
    else:
        checks.append({"check": "players_tests", "ok": True, "detail": "skipped"})

    has_art = bool(artifact_path.exists() and players_artifact_path.exists())
    checks.append(
        {
            "check": "artifacts_exist",
            "ok": bool(has_art),
            "detail": {"artifact": str(artifact_path), "players_artifact": str(players_artifact_path)},
        }
    )
    if not has_art:
        decision = "reject"
        reasons.append("artifacts_missing")

    has_csv = bool(csv_paths)
    checks.append({"check": "csv_paths_resolved", "ok": bool(has_csv), "detail": {"count": len(csv_paths), "paths": csv_paths[:10]}})
    if not has_csv:
        decision = "reject"
        reasons.append("csv_missing")

    rep_lv: Dict[str, Any] = {}
    rep_cd: Dict[str, Any] = {}
    if decision != "reject":
        rep_lv = run_layer_validation(
            artifact_path=str(artifact_path),
            players_artifact_path=str(players_artifact_path),
            csv_paths=csv_paths,
            min_train_games=int(args.min_train_games),
            team_scale=1.0,
            players_scale=1.0,
            min_league_games=int(args.min_league_games),
        )
        if not isinstance(rep_lv, dict) or rep_lv.get("error"):
            checks.append({"check": "layer_validation_run", "ok": False, "detail": rep_lv})
            decision = "reject"
            reasons.append("layer_validation_error")
        else:
            checks.append({"check": "layer_validation_run", "ok": True, "detail": {"n_samples": int(rep_lv.get("n_samples") or 0)}})

    if decision != "reject":
        rep_cd = run_calibration_diagnostics(
            artifact_path=str(artifact_path),
            players_artifact_path=str(players_artifact_path),
            csv_paths=csv_paths,
            team_scale=1.0,
            players_scale=1.0,
            bins=10,
            min_league_games=int(args.min_league_games),
        )
        if not isinstance(rep_cd, dict) or rep_cd.get("error"):
            checks.append({"check": "calibration_diagnostics_run", "ok": False, "detail": rep_cd})
            decision = "reject"
            reasons.append("calibration_diagnostics_error")
        else:
            checks.append({"check": "calibration_diagnostics_run", "ok": True, "detail": {"n_samples": int(rep_cd.get("n_samples") or 0)}})

    n_samples_global = int(rep_lv.get("n_samples") or 0)
    checks.append(
        {
            "check": "global_samples_sufficient",
            "ok": bool(n_samples_global >= int(args.min_global_samples)),
            "detail": {"n_samples": int(n_samples_global), "min_global_samples": int(args.min_global_samples)},
        }
    )
    if n_samples_global < int(args.min_global_samples) and decision != "reject":
        decision = "shadow_only"
        reasons.append("global_samples_low")

    models_lv = rep_lv.get("models") if isinstance(rep_lv.get("models"), dict) else {}
    team_lv = models_lv.get("team_only") if isinstance(models_lv.get("team_only"), dict) else {}
    fused_lv = models_lv.get("fused_active") if isinstance(models_lv.get("fused_active"), dict) else {}
    n_global_lv = int(fused_lv.get("n_total") or team_lv.get("n_total") or n_samples_global)
    gain_ll_global = _f(fused_lv.get("gain_vs_team_logloss"), float("nan"))
    checks.append(
        _check_non_inferior(
            "global_non_inferior_logloss",
            gain=gain_ll_global,
            tol=float(args.tol_logloss),
            n=n_global_lv,
            min_n=int(args.min_global_samples),
            metric="logloss",
        )
    )
    if not bool(checks[-1].get("ok")):
        decision = "reject"
        reasons.append("global_logloss_non_inferior_failed")

    models_cd = rep_cd.get("models") if isinstance(rep_cd.get("models"), dict) else {}
    team_cd = models_cd.get("team_only") if isinstance(models_cd.get("team_only"), dict) else {}
    fused_cd = models_cd.get("fused_active") if isinstance(models_cd.get("fused_active"), dict) else {}
    n_global_cd = int(fused_cd.get("n") or team_cd.get("n") or 0)
    gain_br_global = _f(team_cd.get("brier"), float("nan")) - _f(fused_cd.get("brier"), float("nan"))
    gain_ece_global = _f(team_cd.get("ece"), float("nan")) - _f(fused_cd.get("ece"), float("nan"))
    checks.append(
        _check_non_inferior(
            "global_non_inferior_brier",
            gain=gain_br_global,
            tol=float(args.tol_brier),
            n=n_global_cd,
            min_n=int(args.min_global_samples),
            metric="brier",
        )
    )
    if not bool(checks[-1].get("ok")):
        decision = "reject"
        reasons.append("global_brier_non_inferior_failed")
    checks.append(
        _check_non_inferior(
            "global_non_inferior_ece",
            gain=gain_ece_global,
            tol=float(args.tol_ece),
            n=n_global_cd,
            min_n=int(args.min_global_samples),
            metric="ece",
        )
    )
    if not bool(checks[-1].get("ok")):
        decision = "reject"
        reasons.append("global_ece_non_inferior_failed")

    has_practical_gain = bool(
        (math.isfinite(gain_ll_global) and float(gain_ll_global) > 0.0)
        or (math.isfinite(gain_br_global) and float(gain_br_global) > 0.0)
        or (math.isfinite(gain_ece_global) and float(gain_ece_global) >= float(args.ece_improve_min))
    )
    checks.append(
        {
            "check": "global_practical_gain",
            "ok": bool(has_practical_gain),
            "detail": {
                "gain_logloss": (float(gain_ll_global) if math.isfinite(gain_ll_global) else None),
                "gain_brier": (float(gain_br_global) if math.isfinite(gain_br_global) else None),
                "gain_ece": (float(gain_ece_global) if math.isfinite(gain_ece_global) else None),
                "ece_improve_min": float(args.ece_improve_min),
            },
        }
    )
    if (not has_practical_gain) and decision == "promote":
        decision = "shadow_only"
        reasons.append("global_gain_not_practical")

    by_lg_cd = rep_cd.get("by_league") if isinstance(rep_cd.get("by_league"), dict) else {}
    leagues_eval = sorted([str(k) for k in by_lg_cd.keys()])
    league_fail = 0
    for lg in leagues_eval:
        row_cd = by_lg_cd.get(lg) if isinstance(by_lg_cd.get(lg), dict) else {}
        team_lg_cd = row_cd.get("team_only") if isinstance(row_cd.get("team_only"), dict) else {}
        fused_lg_cd = row_cd.get("fused_active") if isinstance(row_cd.get("fused_active"), dict) else {}
        n_lg = int(fused_lg_cd.get("n") or team_lg_cd.get("n") or 0)
        gain_ll = _f(team_lg_cd.get("logloss"), float("nan")) - _f(fused_lg_cd.get("logloss"), float("nan"))
        ok_ll = (n_lg < int(args.min_league_games)) or (math.isfinite(gain_ll) and gain_ll >= -abs(float(args.tol_logloss)))
        gain_br = _f(team_lg_cd.get("brier"), float("nan")) - _f(fused_lg_cd.get("brier"), float("nan"))
        gain_ece = _f(team_lg_cd.get("ece"), float("nan")) - _f(fused_lg_cd.get("ece"), float("nan"))
        ok_br = (n_lg < int(args.min_league_games)) or (math.isfinite(gain_br) and gain_br >= -abs(float(args.tol_brier)))
        # Per-league ECE is high-variance on smaller slices; kept as diagnostic only (not gated).
        ok_lg = bool(ok_ll and ok_br)
        if not ok_lg and n_lg >= int(args.min_league_games):
            league_fail += 1
        checks.append(
            {
                "check": f"league_non_inferior::{lg}",
                "ok": ok_lg,
                "detail": {
                    "n": int(n_lg),
                    "gain_logloss": (float(gain_ll) if math.isfinite(gain_ll) else None),
                    "gain_brier": (float(gain_br) if math.isfinite(gain_br) else None),
                    "gain_ece": (float(gain_ece) if math.isfinite(gain_ece) else None),
                },
            }
        )

    checks.append(
        {
            "check": "league_coverage",
            "ok": bool(len(leagues_eval) >= int(args.min_leagues_covered)),
            "detail": {"covered": len(leagues_eval), "min": int(args.min_leagues_covered), "leagues": leagues_eval},
        }
    )
    if len(leagues_eval) < int(args.min_leagues_covered) and decision == "promote":
        decision = "shadow_only"
        reasons.append("league_coverage_low")

    checks.append(
        {
            "check": "league_non_inferior_all",
            "ok": bool(league_fail == 0),
            "detail": {"fail_count": int(league_fail), "considered": len(leagues_eval)},
        }
    )
    if league_fail > 0 and decision == "promote":
        decision = "shadow_only"
        reasons.append("league_non_inferior_failed")

    rep = {
        "version": "phase9_players_gate_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decision": str(decision),
        "reasons": reasons,
        "summary": {
            "ok": int(sum(1 for c in checks if bool(c.get("ok")))),
            "total": len(checks),
            "n_samples_global": int(n_samples_global),
            "gain_logloss_global": (float(gain_ll_global) if math.isfinite(gain_ll_global) else None),
            "gain_brier_global": (float(gain_br_global) if math.isfinite(gain_br_global) else None),
            "gain_ece_global": (float(gain_ece_global) if math.isfinite(gain_ece_global) else None),
            "league_covered": len(leagues_eval),
            "league_fail": int(league_fail),
        },
        "thresholds": {
            "min_train_games": int(args.min_train_games),
            "min_global_samples": int(args.min_global_samples),
            "min_league_games": int(args.min_league_games),
            "min_leagues_covered": int(args.min_leagues_covered),
            "tol_logloss": float(args.tol_logloss),
            "tol_brier": float(args.tol_brier),
            "tol_ece": float(args.tol_ece),
            "ece_improve_min": float(args.ece_improve_min),
        },
        "checks": checks,
        "sources": {
            "artifact": str(artifact_path),
            "players_artifact": str(players_artifact_path),
            "csv_paths": csv_paths,
        },
        "layer_validation": rep_lv,
        "calibration_diagnostics": rep_cd,
    }
    out_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"OK: phase9 players gate -> {out_path.name} | decision={decision} | "
        f"ok={rep['summary']['ok']}/{rep['summary']['total']}"
    )
    return 0 if decision == "promote" else (1 if decision == "shadow_only" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
