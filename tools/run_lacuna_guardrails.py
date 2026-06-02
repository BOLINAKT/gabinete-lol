from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            obj = json.loads(path.read_text(encoding="utf-8"))
            return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}
    return {}


def _default_csvs(root: Path) -> List[Path]:
    out: List[Path] = []
    for sub in ("CSV_DIARIO", "CSV_HISTORICO"):
        d = root / sub
        if d.exists():
            out.extend(sorted([p for p in d.glob("*.csv") if p.is_file()]))
    return out


def _norm_dec(v: Any) -> str:
    s = str(v or "").strip().lower()
    return s if s in {"promote", "shadow_only", "reject"} else "unknown"


def _rank(dec: str) -> int:
    return {"promote": 0, "shadow_only": 1, "reject": 2, "unknown": 1}.get(dec, 1)


def _run_cmd(args: List[str], timeout: int = 300) -> Tuple[int, str]:
    try:
        cp = subprocess.run(
            args,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=int(timeout),
        )
        out = (str(cp.stdout or "") + ("\n" + str(cp.stderr or "") if cp.stderr else "")).strip()
        return int(cp.returncode), (out or "-")
    except Exception as e:
        return 2, f"exception:{type(e).__name__}:{e}"


def _read_decision(path: Path, *, nested_key: str = "") -> str:
    rep = _read_json(path)
    if not rep:
        return "unknown"
    if nested_key:
        try:
            node: Any = rep
            for k in str(nested_key).split("."):
                if not isinstance(node, dict):
                    return "unknown"
                node = node.get(k)
            return _norm_dec(node)
        except Exception:
            return "unknown"
    return _norm_dec(rep.get("decision"))


def _coverage_report(csv_paths: List[Path]) -> Dict[str, Any]:
    leagues: Dict[str, int] = {}
    team_rows = 0
    blank_teams = 0
    rows_total = 0
    files_read = 0
    errors: List[str] = []

    for p in csv_paths:
        try:
            df = pd.read_csv(p, low_memory=False)
        except Exception as e:
            errors.append(f"{p.name}:read_error:{e}")
            continue
        files_read += 1
        rows_total += len(df)
        cols_l = {str(c).lower(): str(c) for c in df.columns}
        lg_col = cols_l.get("league")
        if lg_col:
            vc = df[lg_col].fillna("").astype(str).str.strip().str.upper().value_counts()
            for k, v in vc.to_dict().items():
                if not k:
                    continue
                leagues[k] = int(leagues.get(k, 0) + int(v))
        # Oracle layout (blue/red) or team layout (team/opponent)
        t_blue = cols_l.get("blue")
        t_red = cols_l.get("red")
        t_team = cols_l.get("team")
        t_opp = cols_l.get("opponent")
        t_teamname = cols_l.get("teamname")
        if t_blue and t_red:
            b = df[t_blue].fillna("").astype(str).str.strip()
            r = df[t_red].fillna("").astype(str).str.strip()
            team_rows += int(len(df) * 2)
            blank_teams += int((b == "").sum() + (r == "").sum())
        elif t_team and t_opp:
            a = df[t_team].fillna("").astype(str).str.strip()
            b = df[t_opp].fillna("").astype(str).str.strip()
            team_rows += int(len(df) * 2)
            blank_teams += int((a == "").sum() + (b == "").sum())
        elif t_teamname:
            a = df[t_teamname].fillna("").astype(str).str.strip()
            team_rows += len(df)
            blank_teams += int((a == "").sum())

    league_count = len(leagues)
    low_sample_leagues = int(sum(1 for _k, v in leagues.items() if int(v) < 30))
    blank_team_rate = (float(blank_teams) / float(team_rows)) if team_rows > 0 else 0.0

    decision = "promote"
    reasons: List[str] = []
    if errors:
        decision = "shadow_only"
        reasons.append("csv_read_errors_present")
    if league_count < 10:
        decision = "shadow_only"
        reasons.append("league_coverage_low")
    if blank_team_rate > 0.001:
        decision = "reject"
        reasons.append("blank_team_rate_high")
    elif low_sample_leagues > 10 and decision == "promote":
        decision = "shadow_only"
        reasons.append("many_low_sample_leagues")

    return {
        "decision": decision,
        "reasons": reasons,
        "summary": {
            "files_read": int(files_read),
            "files_total": len(csv_paths),
            "rows_total": int(rows_total),
            "league_count": int(league_count),
            "low_sample_leagues_lt30": int(low_sample_leagues),
            "team_rows": int(team_rows),
            "blank_teams": int(blank_teams),
            "blank_team_rate": float(blank_team_rate),
        },
        "top_leagues": sorted(
            [{"league": k, "rows": int(v)} for k, v in leagues.items()],
            key=lambda x: int(x["rows"]),
            reverse=True,
        )[:30],
        "errors": errors[:20],
    }


def _artifact_freshness(root: Path, csv_paths: List[Path]) -> Dict[str, Any]:
    ml_art = root / "ml_artifact.json"
    pl_art = root / "players_artifact.json"
    params = root / "params_fitted.json"
    newest_csv = max([p.stat().st_mtime for p in csv_paths], default=0.0)

    def _age_hours(p: Path) -> float | None:
        try:
            if p.exists():
                return (max(0.0, newest_csv - p.stat().st_mtime)) / 3600.0
        except Exception:
            return None
        return None

    ml_age = _age_hours(ml_art)
    pl_age = _age_hours(pl_art)
    pa_age = _age_hours(params)

    decision = "promote"
    reasons: List[str] = []
    if not ml_art.exists() or not params.exists():
        decision = "reject"
        reasons.append("core_artifacts_missing")
    if pl_art.exists() is False:
        if decision != "reject":
            decision = "shadow_only"
        reasons.append("players_artifact_missing")

    # If CSV is newer than artifacts by many hours, require at least shadow-only.
    stale_hours = [x for x in [ml_age, pl_age, pa_age] if x is not None]
    max_stale = max(stale_hours) if stale_hours else None
    if max_stale is not None and max_stale > 6.0 and decision == "promote":
        decision = "shadow_only"
        reasons.append("artifacts_stale_vs_csv")

    return {
        "decision": decision,
        "reasons": reasons,
        "summary": {
            "ml_artifact_exists": ml_art.exists(),
            "players_artifact_exists": pl_art.exists(),
            "params_fitted_exists": params.exists(),
            "age_vs_newest_csv_hours": {
                "ml_artifact": ml_age,
                "players_artifact": pl_age,
                "params_fitted": pa_age,
            },
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Unified lacuna guardrails (single promotion decision).")
    ap.add_argument("--out", default="lacuna_guardrail_report.json")
    ap.add_argument("--skip-runs", action="store_true", help="Do not execute anchor/leakage scripts; only read existing JSONs.")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument(
        "--strict-phase-coverage",
        action="store_true",
        help="Require all phase reports (1.2/2/3/4/5/6/7/8) and enforce phase decisions in final gate.",
    )
    args = ap.parse_args()

    csv_paths = _default_csvs(ROOT)

    logs: List[str] = []
    if not args.skip_runs:
        rc_a, lg_a = _run_cmd([sys.executable, "tools/anchor_regression_suite.py", "--mode", "app"], timeout=args.timeout)
        logs.append(f"$ anchor_regression_suite rc={rc_a}\n{lg_a}")
        rc_l, lg_l = _run_cmd([sys.executable, "tools/check_data_leakage_and_labels.py"], timeout=args.timeout)
        logs.append(f"$ check_data_leakage_and_labels rc={rc_l}\n{lg_l}")

    bt = _read_json(ROOT / "backtest_pipeline_abc_by_league_report.json")
    ar = _read_json(ROOT / "anchor_regression_report.json")
    lr = _read_json(ROOT / "data_leakage_label_report.json")
    cov = _coverage_report(csv_paths)
    art = _artifact_freshness(ROOT, csv_paths)

    dec_bt = _norm_dec(((bt.get("promotion_decision") or {}) if isinstance(bt, dict) else {}).get("decision"))
    dec_ar = _norm_dec(ar.get("decision") if isinstance(ar, dict) else "")
    dec_lr = _norm_dec(lr.get("decision") if isinstance(lr, dict) else "")
    dec_cov = _norm_dec(cov.get("decision"))
    dec_art = _norm_dec(art.get("decision"))

    parts = {
        "stop_rules_backtest": dec_bt,
        "anchors_app": dec_ar,
        "leakage_labels": dec_lr,
        "coverage_aliases": dec_cov,
        "artifact_freshness": dec_art,
    }
    phase_sources = {
        "phase12_roster": ROOT / "phase12_roster_continuity_report.json",
        "phase2_areal": ROOT / "phase2_areal_report.json",
        "phase2b_areal_tuning": ROOT / "phase2b_areal_tuning_report.json",
        "phase3_breal": ROOT / "phase3_breal_report.json",
        "phase4_ranksos": ROOT / "phase4_ranksos_report.json",
        "phase4b_marginal_tuning": ROOT / "phase4b_marginal_tuning_report.json",
        "phase5_hier_calibration": ROOT / "phase5_hier_calibration_report.json",
        "phase6_series_bo": ROOT / "phase6_series_bo_report.json",
        "phase7_layer_uncertainty": ROOT / "phase7_layer_uncertainty_report.json",
        # phase8 is an operational aggregator that consumes this guardrail.
        # Keep it visible in report, but never enforce it in strict final gate
        # to avoid circular shadow_only deadlock (phase8 <-> lacuna).
        "phase8_operations": ROOT / "phase8_operations_report.json",
    }
    phase_parts: Dict[str, str] = {}
    missing_phase_reports: List[str] = []
    for k, p in phase_sources.items():
        if p.exists():
            phase_parts[k] = _read_decision(p)
        else:
            missing_phase_reports.append(str(p.name))
    # Optional phase decisions:
    # - default (permissive): informational only, do not alter consolidated decision.
    # - strict mode: enforce both coverage and phase decisions into final gate.
    if bool(args.strict_phase_coverage):
        for _k, _v in phase_parts.items():
            if str(_k) == "phase8_operations":
                continue
            parts[_k] = _v

    final = "unknown"
    if parts:
        final = max(parts.values(), key=_rank)

    reasons: List[str] = []
    for name, dec in parts.items():
        if dec != "promote":
            reasons.append(f"{name}:{dec}")
    if bool(args.strict_phase_coverage) and missing_phase_reports:
        if _rank(final) < _rank("shadow_only"):
            final = "shadow_only"
        reasons.append("missing_phase_reports_strict")

    report = {
        "version": "lacuna_guardrail_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decision": final,
        "reasons": reasons,
        "parts": parts,
        "phase_parts": phase_parts,
        "missing_phase_reports": missing_phase_reports,
        "strict_phase_coverage": bool(args.strict_phase_coverage),
        "coverage": cov,
        "artifact_freshness": art,
        "sources": {
            "backtest_report": "backtest_pipeline_abc_by_league_report.json",
            "anchor_report": "anchor_regression_report.json",
            "leakage_report": "data_leakage_label_report.json",
            "phase_reports": {k: str(v.name) for k, v in phase_sources.items()},
        },
        "run_log": "\n\n".join(logs),
    }

    out = ROOT / str(args.out)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"OK: lacuna guardrail -> {out.name} | decision={final} | "
        f"bt={dec_bt} ar={dec_ar} leak={dec_lr} cov={dec_cov} art={dec_art}"
    )
    return 0 if final == "promote" else (1 if final == "shadow_only" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
