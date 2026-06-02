from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.matchup_league_resolution_core import (
    build_matchup_integrity_row,
    merge_matchup_audit_cases,
    resolve_runtime_team_leagues,
    seed_default_matchup_audit_cases,
)
from app_core.identity_registry_core import (
    load_identity_registry,
    team_identity_candidates,
    team_identity_league_candidates,
)
from app_core.ml_league_inference_core import infer_match_league_from_csv, infer_team_league_from_csv
from app_core.ml_league_runtime_core import MAJOR_LEAGUES, norm_league_key, tier_from_league


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


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit runtime matchup league resolution against CSV history.")
    ap.add_argument("--csv", default=str(ROOT / "CSV_DIARIO" / "2026_LoL_esports_match_data_from_OraclesElixir.csv"))
    ap.add_argument("--trace", default=str(ROOT / "ml_trace_last.json"))
    ap.add_argument("--out", default=str(ROOT / "ops" / "monitoring" / "matchup_integrity_audit_report.json"))
    args = ap.parse_args()

    csv_path = Path(args.csv)
    trace_path = Path(args.trace)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    inference_sigs = _league_inference_sigs(csv_path, 2026)
    registry = load_identity_registry(ROOT / "identity_registry.json")
    trace_payload: dict[str, Any] = {}
    if trace_path.exists():
        try:
            trace_payload = json.loads(trace_path.read_text(encoding="utf-8"))
        except Exception:
            trace_payload = {}

    trace_matchup = {}
    trace_ml = {}
    if isinstance(trace_payload, dict):
        trace_matchup = dict(trace_payload.get("matchup") or {})
        trace_ml = dict(trace_payload.get("ml_trace") or {})

    cases = merge_matchup_audit_cases(
        seed_default_matchup_audit_cases(),
        [
            {
                "team_a": trace_matchup.get("teamA"),
                "team_b": trace_matchup.get("teamB"),
                "year": 2026,
            }
        ],
    )

    def _infer_team(team: str, year: Any) -> str:
        aliases = team_identity_candidates(registry, team)
        for csv_sig_item in inference_sigs:
            out = infer_team_league_from_csv(
                csv_sig_item,
                team,
                year,
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

    def _infer_match(team_a: str, team_b: str, year: Any) -> str:
        aliases_a = team_identity_candidates(registry, team_a)
        aliases_b = team_identity_candidates(registry, team_b)
        for csv_sig_item in inference_sigs:
            out = infer_match_league_from_csv(
                csv_sig_item,
                team_a,
                team_b,
                year,
                norm_league_key_fn=norm_league_key,
                major_leagues=MAJOR_LEAGUES,
                load_team_games_fn=_load_team_games,
                infer_team_league_fn=lambda _sig, team, yy: _infer_team(team, yy),
                team_aliases_a=aliases_a,
                team_aliases_b=aliases_b,
                fallback_any_year=True,
            )
            if str(out or "").strip():
                return str(out)
        return ""

    rows = []
    for case in cases:
        resolved = resolve_runtime_team_leagues(
            team_a=str(case.get("team_a") or ""),
            team_b=str(case.get("team_b") or ""),
            year=case.get("year"),
            league_mode="auto",
            fixed_league="",
            infer_team_league_fn=_infer_team,
            infer_match_league_fn=_infer_match,
            tier_from_league_fn=tier_from_league,
            team_aliases_fn=lambda team: team_identity_candidates(registry, team),
        )
        tla = ""
        tlb = ""
        if (
            str(trace_matchup.get("teamA") or "") == str(case.get("team_a") or "")
            and str(trace_matchup.get("teamB") or "") == str(case.get("team_b") or "")
        ):
            tla = str((((trace_ml.get("hier_calibration_live") or {}).get("league_a")) or "")).strip()
            tlb = str((((trace_ml.get("hier_calibration_live") or {}).get("league_b")) or "")).strip()
        rows.append(
            build_matchup_integrity_row(
                team_a=str(case.get("team_a") or ""),
                team_b=str(case.get("team_b") or ""),
                league_a=str(resolved.get("league_a") or ""),
                league_b=str(resolved.get("league_b") or ""),
                source=str(resolved.get("source") or ""),
                trace_league_a=tla,
                trace_league_b=tlb,
            )
        )

    payload = {
        "csv": str(csv_path),
        "trace": str(trace_path),
        "rows": rows,
        "review_count": sum(1 for row in rows if str(row.get("status")) == "review"),
        "ok_count": sum(1 for row in rows if str(row.get("status")) == "ok"),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
