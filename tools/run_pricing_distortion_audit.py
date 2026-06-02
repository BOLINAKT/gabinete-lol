from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.pricing_distortion_audit_core import (
    evaluate_pricing_distortion,
    merge_pricing_distortion_cases,
    seed_pricing_distortion_cases,
)
from app_core.streamlit_apptest_core import (
    new_apptest_for_file as core_new_apptest_for_file,
    quiet_streamlit_bare_mode_warnings as core_quiet_streamlit_bare_mode_warnings,
    run_apptest_quiet as core_run_apptest_quiet,
)
from app_core.identity_registry_core import (
    load_identity_registry,
    team_identity_candidates,
    team_identity_league_candidates,
)
from app_core.matchup_league_resolution_core import resolve_runtime_team_leagues
from app_core.ml_league_inference_core import infer_match_league_from_csv, infer_team_league_from_csv
from app_core.ml_league_runtime_core import MAJOR_LEAGUES, norm_league_key, tier_from_league


def _norm(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _pick_option(options: List[str], target: str) -> str | None:
    if target in options:
        return target
    target_norm = _norm(target)
    for value in options:
        if _norm(value) == target_norm:
            return value
    return None


def _ss_get(atx: Any, key: str, default: Any = None) -> Any:
    try:
        return atx.session_state[key]
    except Exception:
        return default


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists():
            return {}
        obj = json.loads(path.read_text(encoding="utf-8-sig"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _csv_sig(path: Path) -> tuple[str, int, int]:
    st = path.stat()
    return (str(path), int(st.st_size), int(st.st_mtime))


def _league_inference_sigs(primary_path: Path, year: Any) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    seen: set[str] = set()

    def _push(path: Path) -> None:
        if not path.exists():
            return
        key = str(path.resolve())
        if key in seen:
            return
        seen.add(key)
        out.append(_csv_sig(path))

    _push(primary_path)
    candidates: list[Path] = []
    for base in [ROOT / "CSV_DIARIO", ROOT / "CSV_HISTORICO"]:
        if base.exists():
            candidates.extend(base.glob("*_LoL_esports_match_data_from_OraclesElixir.csv"))

    def _year_score(path: Path) -> int:
        try:
            return int(str(path.name).split("_", 1)[0])
        except Exception:
            return 0

    try:
        target_year = int(year) if year is not None else 0
    except Exception:
        target_year = 0
    candidates = sorted(
        candidates,
        key=lambda path: (abs(_year_score(path) - target_year) if target_year else 0, -_year_score(path), path.name),
    )
    for path in candidates:
        _push(path)
    return out


def _load_team_games(csv_sig: tuple[str, int, int]) -> pd.DataFrame:
    csv_path = csv_sig[0]
    usecols = ["teamname", "opponentteamname", "league", "year", "participantid"]
    df = pd.read_csv(csv_path, usecols=usecols, low_memory=False)
    if "participantid" in df.columns:
        df = df[df["participantid"].isin([100, 200])].copy()
    return pd.DataFrame(
        {
            "team": df.get("teamname", pd.Series(dtype=str)),
            "opponent": df.get("opponentteamname", pd.Series(dtype=str)),
            "league": df.get("league", pd.Series(dtype=str)),
            "year": pd.to_numeric(df.get("year", pd.Series(dtype=float)), errors="coerce"),
        }
    )


def _build_inferers(primary_csv: Path, *, year: int) -> tuple[Any, Any]:
    inference_sigs = _league_inference_sigs(primary_csv, year)
    registry = load_identity_registry(ROOT / "identity_registry.json")

    def _infer_team(team: str, yy: Any) -> str:
        aliases = team_identity_candidates(registry, team)
        for sig in inference_sigs:
            out = infer_team_league_from_csv(
                sig,
                team,
                yy,
                norm_league_key_fn=norm_league_key,
                major_leagues=MAJOR_LEAGUES,
                team_aliases=aliases,
                fallback_any_year=True,
            )
            if str(out or "").strip():
                return str(out)
        for league in team_identity_league_candidates(registry, team):
            text = str(norm_league_key(league) or league).strip()
            if text:
                return text
        return ""

    def _infer_match(team_a: str, team_b: str, yy: Any) -> str:
        aliases_a = team_identity_candidates(registry, team_a)
        aliases_b = team_identity_candidates(registry, team_b)
        for sig in inference_sigs:
            out = infer_match_league_from_csv(
                sig,
                team_a,
                team_b,
                yy,
                norm_league_key_fn=norm_league_key,
                major_leagues=MAJOR_LEAGUES,
                load_team_games_fn=_load_team_games,
                infer_team_league_fn=lambda _sig, team, season_year: _infer_team(team, season_year),
                team_aliases_a=aliases_a,
                team_aliases_b=aliases_b,
                fallback_any_year=True,
            )
            if str(out or "").strip():
                return str(out)
        return ""

    return _infer_team, _infer_match


def _resolve_leagues(
    *,
    team_a: str,
    team_b: str,
    year: int,
    infer_team_league_fn: Any,
    infer_match_league_fn: Any,
) -> Dict[str, str]:
    resolved = resolve_runtime_team_leagues(
        team_a=str(team_a),
        team_b=str(team_b),
        year=year,
        league_mode="auto",
        fixed_league="",
        infer_team_league_fn=infer_team_league_fn,
        infer_match_league_fn=infer_match_league_fn,
        tier_from_league_fn=tier_from_league,
        team_aliases_fn=lambda team: team_identity_candidates(
            load_identity_registry(ROOT / "identity_registry.json"), team
        ),
    )
    return {
        "league_a": str(resolved.get("league_a") or ""),
        "league_b": str(resolved.get("league_b") or ""),
    }


def _run_case_trace_app(
    *,
    root: Path,
    team_a: str,
    team_b: str,
    bo: int,
    timeout: int,
    csv_override: str | None = None,
    artifact_override: str | None = None,
) -> Dict[str, Any]:
    core_quiet_streamlit_bare_mode_warnings(disable_global_logging=True)
    at = core_new_apptest_for_file(root / "plays_app.py")

    def _run_quiet(timeout_s: int) -> None:
        core_run_apptest_quiet(at, int(timeout_s))

    csv_override_s = str(csv_override or "").strip()
    artifact_override_s = str(artifact_override or "").strip()
    if csv_override_s:
        at.session_state["cfg_auto_paths"] = False
        at.session_state["cfg_csv_override"] = csv_override_s
    if artifact_override_s:
        at.session_state["cfg_auto_paths"] = False
        at.session_state["cfg_artifact_override"] = artifact_override_s
    at.session_state["_probe_skip_csv_bootstrap_gate"] = True
    at.session_state["_csv_bootstrap_hold_screen"] = False
    at.session_state["_csv_bootstrap_done_fp"] = "__pricing_audit__"

    _run_quiet(max(120, int(timeout)))
    if getattr(at, "exception", None):
        return {"ok": False, "error": f"bootstrap_exception:{at.exception[0]}"}

    sels = {s.key: s for s in at.selectbox}
    if "teamA" not in sels or "teamB" not in sels:
        try:
            btn = next((b for b in at.button if str(getattr(b, "key", "") or "") == "csv_bootstrap_continue"), None)
            if btn is not None:
                btn.click()
                _run_quiet(max(120, int(timeout)))
                if getattr(at, "exception", None):
                    return {"ok": False, "error": f"post_bootstrap_exception:{at.exception[0]}"}
                sels = {s.key: s for s in at.selectbox}
        except Exception as exc:
            return {"ok": False, "error": f"csv_bootstrap_continue_failed:{exc}"}

    if "teamA" not in sels or "teamB" not in sels:
        return {"ok": False, "error": "team_selectors_missing"}

    opts_a = [str(x) for x in list(getattr(sels["teamA"], "options", []) or []) if str(x)]
    opts_b = [str(x) for x in list(getattr(sels["teamB"], "options", []) or []) if str(x)]
    actual_a = _pick_option(opts_a, team_a)
    actual_b = _pick_option(opts_b, team_b)
    if not actual_a or not actual_b:
        return {"ok": False, "error": "pair_not_found_in_selectors"}
    if _norm(actual_a) == _norm(actual_b):
        return {"ok": False, "error": "same_team_after_mapping"}

    at.session_state["teamA"] = actual_a
    at.session_state["teamB"] = actual_b
    at.session_state["bo"] = int(bo)
    at.session_state["flow_stage"] = "results"
    at.session_state["_analysis_force_once"] = True
    _run_quiet(max(180, int(timeout)))
    if getattr(at, "exception", None):
        return {"ok": False, "error": f"analysis_exception:{at.exception[0]}"}

    trace = _ss_get(at, "_ml_trace_last", {}) or {}
    if not isinstance(trace, Mapping):
        trace = {}
    trace_ml = trace.get("ml_trace") if isinstance(trace.get("ml_trace"), Mapping) else trace
    return {
        "ok": True,
        "team_a": str(actual_a),
        "team_b": str(actual_b),
        "p_map_used": _ss_get(at, "_p_map_used", float("nan")),
        "p_series_used": _ss_get(at, "_p_series_used", float("nan")),
        "trace": dict(trace_ml) if isinstance(trace_ml, Mapping) else {},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit suspicious pricing compression using the real app pipeline.")
    ap.add_argument("--csv", default=str(ROOT / "CSV_DIARIO" / "2026_LoL_esports_match_data_from_OraclesElixir.csv"))
    ap.add_argument("--artifact", default="", help="Override artifact path inside app probe.")
    ap.add_argument("--cases", default=str(ROOT / "ops" / "pricing_distortion_cases.json"))
    ap.add_argument("--out", default=str(ROOT / "ops" / "monitoring" / "pricing_distortion_audit_report.json"))
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    csv_path = Path(str(args.csv)).expanduser().resolve()
    if not csv_path.exists():
        print(f"[error] csv nao encontrado: {csv_path}")
        return 2

    cases_payload = _read_json(Path(str(args.cases)).expanduser())
    extra_cases = list(cases_payload.get("cases", [])) if isinstance(cases_payload.get("cases"), list) else []
    cases = merge_pricing_distortion_cases(seed_pricing_distortion_cases(), extra_cases)
    if int(args.limit) > 0:
        cases = cases[: int(args.limit)]

    infer_team_league_fn, infer_match_league_fn = _build_inferers(csv_path, year=2026)

    rows: list[dict[str, Any]] = []
    for case in cases:
        run = _run_case_trace_app(
            root=ROOT,
            team_a=str(case.get("team_a") or ""),
            team_b=str(case.get("team_b") or ""),
            bo=int(case.get("bo") or 5),
            timeout=int(args.timeout),
            csv_override=str(csv_path),
            artifact_override=str(args.artifact or "").strip() or None,
        )
        if not bool(run.get("ok", False)):
            rows.append(
                {
                    "name": str(case.get("name") or ""),
                    "team_a": str(case.get("team_a") or ""),
                    "team_b": str(case.get("team_b") or ""),
                    "status": "error",
                    "error": str(run.get("error") or ""),
                }
            )
            continue

        leagues = _resolve_leagues(
            team_a=str(run.get("team_a") or ""),
            team_b=str(run.get("team_b") or ""),
            year=2026,
            infer_team_league_fn=infer_team_league_fn,
            infer_match_league_fn=infer_match_league_fn,
        )
        evaluation = evaluate_pricing_distortion(
            team_a=str(run.get("team_a") or ""),
            team_b=str(run.get("team_b") or ""),
            league_a=str(leagues.get("league_a") or ""),
            league_b=str(leagues.get("league_b") or ""),
            trace_payload=(run.get("trace") if isinstance(run.get("trace"), Mapping) else {}),
        )
        evaluation["name"] = str(case.get("name") or "")
        evaluation["bo"] = int(case.get("bo") or 5)
        evaluation["pipeline_order"] = list((((run.get("trace") or {}).get("pipeline") or {}).get("order", [])))
        rows.append(evaluation)

    suspicious = [row for row in rows if str(row.get("status")) == "review"]
    errors = [row for row in rows if str(row.get("status")) == "error"]
    payload = {
        "version": "pricing_distortion_audit_v1",
        "csv": str(csv_path),
        "artifact_override": str(args.artifact or ""),
        "summary": {
            "total": len(rows),
            "ok": sum(1 for row in rows if str(row.get("status")) == "ok"),
            "review": len(suspicious),
            "error": len(errors),
        },
        "rows": rows,
    }
    out_path = Path(str(args.out)).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if (not suspicious and not errors) else 1


if __name__ == "__main__":
    raise SystemExit(main())
