from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.csv_gate_core import (
    detect_series_gap_suspects,
    evaluate_csv_gate_metrics,
    fingerprint_inventory,
    rank_decision,
    summarize_league_changes,
)
from mlcore.tiers import canonical_league


WANTED_COLS = {
    "gameid",
    "participantid",
    "league",
    "date",
    "game",
    "year",
    "teamname",
    "result",
    "side",
    "position",
    "split",
    "playoffs",
    "datacompleteness",
}
REQUIRED_COLS = {"gameid", "participantid", "league", "date", "year", "teamname", "result", "side", "position"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists():
            return {}
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _subprocess_env() -> Dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run_cmd(cmd: List[str], *, timeout: int) -> Dict[str, Any]:
    try:
        cp = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_subprocess_env(),
            timeout=int(timeout),
        )
        return {
            "ok": bool(int(cp.returncode) == 0),
            "returncode": int(cp.returncode),
            "stdout_tail": str(cp.stdout or "")[-4000:],
            "stderr_tail": str(cp.stderr or "")[-4000:],
        }
    except Exception as exc:
        return {
            "ok": False,
            "returncode": 2,
            "stdout_tail": "",
            "stderr_tail": f"{type(exc).__name__}: {exc}",
        }


def _default_csvs(root: Path) -> List[Path]:
    out: List[Path] = []
    for sub in ("CSV_HISTORICO", "CSV_DIARIO"):
        base = root / sub
        if base.exists():
            out.extend(sorted([p for p in base.glob("*.csv") if p.is_file()]))
    return out


def _inventory_records(paths: Iterable[Path]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in paths:
        try:
            stat = path.stat()
        except Exception:
            continue
        rows.append(
            {
                "path": str(path.resolve()),
                "name": path.name,
                "size": int(stat.st_size),
                "mtime_ns": int(stat.st_mtime_ns),
            }
        )
    rows.sort(key=lambda r: str(r.get("path") or ""))
    return rows


def _year_from_filename(path: Path) -> int | None:
    m = re.match(r"^(\d{4})_", str(path.name or ""))
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _load_light_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(
        path,
        low_memory=False,
        usecols=lambda c: str(c or "").strip().lower() in WANTED_COLS,
    )


def _inspect_csvs(
    csv_paths: List[Path],
    *,
    known_raw_leagues: Iterable[str],
    known_canonical_leagues: Iterable[str],
) -> Dict[str, Any]:
    rows_total = 0
    row_key_total = 0
    row_key_dup_total = 0
    date_parse_fail_total = 0
    blank_team_total = 0
    blank_league_total = 0
    year_mismatch_total = 0
    year_col_vs_date_mismatch_total = 0
    missing_required_cols_files = 0
    read_errors: List[str] = []
    files_summary: List[Dict[str, Any]] = []
    raw_leagues_all: List[str] = []
    seen_row_keys: set[str] = set()
    coverage_by_canonical: Dict[str, int] = {}
    daily_series_gap_reports: List[Dict[str, Any]] = []

    for path in csv_paths:
        file_summary: Dict[str, Any] = {"path": str(path.resolve()), "name": path.name}
        try:
            df = _load_light_csv(path)
        except Exception as exc:
            read_errors.append(f"{path.name}:read_error:{type(exc).__name__}:{exc}")
            file_summary["read_error"] = str(exc)
            files_summary.append(file_summary)
            continue

        cols = {str(c).strip().lower(): str(c) for c in df.columns}
        missing = sorted([c for c in REQUIRED_COLS if c not in cols])
        file_summary["rows"] = len(df)
        file_summary["missing_required_cols"] = missing
        if missing:
            missing_required_cols_files += 1

        rows_total += len(df)

        gameid_s = df[cols["gameid"]].fillna("").astype(str).str.strip() if "gameid" in cols else pd.Series([], dtype=str)
        participant_s = df[cols["participantid"]].fillna("").astype(str).str.strip() if "participantid" in cols else pd.Series([], dtype=str)
        if len(gameid_s) and len(participant_s):
            row_keys = (gameid_s + "||" + participant_s).tolist()
            row_key_total += len(row_keys)
            for key in row_keys:
                if key in seen_row_keys:
                    row_key_dup_total += 1
                else:
                    seen_row_keys.add(key)

        team_s = df[cols["teamname"]].fillna("").astype(str).str.strip() if "teamname" in cols else pd.Series([], dtype=str)
        blank_team_total += int((team_s == "").sum()) if len(team_s) else 0

        league_s = df[cols["league"]].fillna("").astype(str).str.strip() if "league" in cols else pd.Series([], dtype=str)
        blank_league_total += int((league_s == "").sum()) if len(league_s) else 0
        raw_leagues = sorted({str(x).strip().upper() for x in league_s.tolist() if str(x).strip()})
        raw_leagues_all.extend(raw_leagues)
        for lg in league_s.tolist():
            raw = str(lg or "").strip()
            if not raw:
                continue
            canon = str(canonical_league(raw) or raw).strip().upper()
            coverage_by_canonical[canon] = int(coverage_by_canonical.get(canon, 0) + 1)

        date_s = df[cols["date"]] if "date" in cols else pd.Series([], dtype=object)
        date_dt = pd.to_datetime(date_s, errors="coerce", utc=False) if len(date_s) else pd.Series([], dtype="datetime64[ns]")
        if len(date_dt):
            date_parse_fail_total += int(date_dt.isna().sum())

        file_year = _year_from_filename(path)
        if len(date_dt):
            date_year = pd.Series(date_dt.dt.year, index=df.index)
            if "year" in cols:
                year_num = pd.to_numeric(df[cols["year"]], errors="coerce")
                mismatch_mask = year_num.notna() & date_year.notna() & (year_num.astype("Int64") != date_year.astype("Int64"))
                year_col_vs_date_mismatch_total += int(mismatch_mask.sum())
            if file_year is not None:
                file_year_mask = date_year.notna() & (date_year.astype("Int64") != int(file_year))
                year_mismatch_total += int(file_year_mask.sum())

        file_summary["raw_leagues"] = raw_leagues[:20]
        file_summary["canonical_leagues"] = sorted({str(canonical_league(x) or x).strip().upper() for x in raw_leagues})[:20]
        if str(path.parent.name).strip().upper() == "CSV_DIARIO":
            daily_series_gap_reports.append(detect_series_gap_suspects(df, source_name=path.name))
        files_summary.append(file_summary)

    league_changes = summarize_league_changes(
        raw_leagues_all,
        known_raw_leagues=known_raw_leagues,
        known_canonical_leagues=known_canonical_leagues,
        canonicalize_fn=canonical_league,
    )
    daily_series_gap_suspect_groups = int(sum(int(item.get("suspect_groups") or 0) for item in daily_series_gap_reports))
    daily_series_gap_suspect_games = int(sum(int(item.get("suspect_games") or 0) for item in daily_series_gap_reports))
    daily_series_gap_examples: List[Dict[str, Any]] = []
    for item in daily_series_gap_reports:
        for row in list(item.get("examples") or []):
            if len(daily_series_gap_examples) >= 25:
                break
            if isinstance(row, dict):
                daily_series_gap_examples.append(dict(row))
        if len(daily_series_gap_examples) >= 25:
            break

    metrics = {
        "rows_total": int(rows_total),
        "row_key_total": int(row_key_total),
        "row_key_dup_total": int(row_key_dup_total),
        "row_key_dup_rate": (float(row_key_dup_total) / float(row_key_total) if row_key_total > 0 else 0.0),
        "date_parse_fail_total": int(date_parse_fail_total),
        "date_parse_fail_rate": (float(date_parse_fail_total) / float(rows_total) if rows_total > 0 else 0.0),
        "blank_team_total": int(blank_team_total),
        "blank_team_rate": (float(blank_team_total) / float(rows_total) if rows_total > 0 else 0.0),
        "blank_league_total": int(blank_league_total),
        "blank_league_rate": (float(blank_league_total) / float(rows_total) if rows_total > 0 else 0.0),
        "year_mismatch_total": int(year_mismatch_total),
        "year_mismatch_rate": (float(year_mismatch_total) / float(rows_total) if rows_total > 0 else 0.0),
        "year_col_vs_date_mismatch_total": int(year_col_vs_date_mismatch_total),
        "year_col_vs_date_mismatch_rate": (float(year_col_vs_date_mismatch_total) / float(rows_total) if rows_total > 0 else 0.0),
        "missing_required_cols_files": int(missing_required_cols_files),
        "new_canonical_count": (len(league_changes.get("new_canonical_leagues") or []) if list(known_canonical_leagues or []) else 0),
        "league_baseline_seeded": bool(list(known_canonical_leagues or [])),
        "daily_series_gap_suspect_groups": int(daily_series_gap_suspect_groups),
        "daily_series_gap_suspect_games": int(daily_series_gap_suspect_games),
    }

    return {
        "metrics": metrics,
        "files": files_summary,
        "read_errors": read_errors[:20],
        "league_changes": league_changes,
        "daily_series_gap_suspects": {
            "groups": int(daily_series_gap_suspect_groups),
            "games": int(daily_series_gap_suspect_games),
            "examples": daily_series_gap_examples,
            "sources": [
                {
                    "source": str(item.get("source") or ""),
                    "suspect_groups": int(item.get("suspect_groups") or 0),
                    "suspect_games": int(item.get("suspect_games") or 0),
                }
                for item in daily_series_gap_reports
            ],
        },
        "coverage_by_canonical": {
            k: int(v) for k, v in sorted(coverage_by_canonical.items(), key=lambda kv: kv[1], reverse=True)[:40]
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="CSV ingest gate with fingerprinting, schema checks, league alias detection and bootstrap probe.")
    ap.add_argument("--csv", action="append", default=[])
    ap.add_argument("--out", default="ops/csv_ingest/csv_ingest_gate_report.json")
    ap.add_argument("--state", default="ops/csv_ingest/csv_ingest_gate_state.json")
    ap.add_argument("--phase1-out", default="phase1_data_contract_report.csv_ingest.json")
    ap.add_argument("--bootstrap-out", default="csv_bootstrap_e2e_report.csv_ingest.json")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--skip-bootstrap", action="store_true")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args()

    csv_paths = [Path(x).expanduser().resolve() for x in (args.csv or [])]
    if not csv_paths:
        csv_paths = _default_csvs(ROOT)

    inventory = _inventory_records(csv_paths)
    fingerprint = fingerprint_inventory(inventory)
    state_path = (ROOT / str(args.state)).resolve()
    out_path = (ROOT / str(args.out)).resolve()
    state = _read_json(state_path)
    known_raw = list(state.get("known_raw_leagues_promoted") or [])
    known_canonical = list(state.get("known_canonical_leagues_promoted") or [])
    last_fp = str(state.get("last_fingerprint") or "")
    last_decision = str(state.get("last_decision") or "")

    if (not bool(args.force)) and last_fp and last_fp == fingerprint:
        rep = {
            "version": "csv_ingest_gate_v1",
            "generated_at": _utc_now(),
            "status": "skipped_no_changes",
            "decision": str(last_decision or "promote"),
            "fingerprint": fingerprint,
            "inventory": inventory,
            "state_path": str(state_path),
        }
        _write_json(out_path, rep)
        print(f"OK: csv ingest gate -> {out_path.name} | status=skipped_no_changes | decision={rep['decision']}")
        return 0 if rep["decision"] == "promote" else (1 if rep["decision"] == "shadow_only" else 2)

    inspection = _inspect_csvs(
        csv_paths,
        known_raw_leagues=known_raw,
        known_canonical_leagues=known_canonical,
    )

    phase1_cmd = [sys.executable, "tools/run_phase1_data_contract.py", "--out", str(args.phase1_out), "--timeout", "600"]
    phase1_res = _run_cmd(phase1_cmd, timeout=min(1800, int(args.timeout)))
    phase1_obj = _read_json(ROOT / str(args.phase1_out))
    phase1_dec = str(phase1_obj.get("decision") or "shadow_only")
    inspection["metrics"]["phase1_decision"] = phase1_dec

    bootstrap_res: Dict[str, Any] = {}
    bootstrap_obj: Dict[str, Any] = {}
    bootstrap_dec = "promote"
    if not bool(args.skip_bootstrap):
        bootstrap_cmd = [
            sys.executable,
            "tools/run_csv_bootstrap_e2e.py",
            "--skip-heavy",
            "--timeout",
            "240",
            "--out",
            str(args.bootstrap_out),
        ]
        bootstrap_res = _run_cmd(bootstrap_cmd, timeout=max(600, int(args.timeout)))
        bootstrap_obj = _read_json(ROOT / str(args.bootstrap_out))
        bootstrap_dec = str(bootstrap_obj.get("decision") or ("promote" if bootstrap_res.get("ok") else "reject"))
    inspection["metrics"]["bootstrap_decision"] = bootstrap_dec

    custom_gate = evaluate_csv_gate_metrics(inspection["metrics"])
    final_decision = custom_gate.get("decision") if isinstance(custom_gate, dict) else "shadow_only"
    if rank_decision(bootstrap_dec) > rank_decision(str(final_decision)):
        final_decision = bootstrap_dec

    reasons = list(custom_gate.get("reasons") or [])
    if phase1_dec not in {"", "promote"} and f"phase1:{phase1_dec}" not in reasons:
        reasons.append(f"phase1:{phase1_dec}")
    if bootstrap_dec not in {"", "promote"}:
        reasons.append(f"bootstrap:{bootstrap_dec}")

    rep = {
        "version": "csv_ingest_gate_v1",
        "generated_at": _utc_now(),
        "status": "evaluated",
        "decision": str(final_decision),
        "reasons": reasons,
        "fingerprint": fingerprint,
        "inventory": inventory,
        "inspection": inspection,
        "custom_gate": custom_gate,
        "phase1": {
            "command": phase1_cmd,
            "run": phase1_res,
            "report_path": str((ROOT / str(args.phase1_out)).resolve()),
            "report": phase1_obj,
        },
        "bootstrap_probe": {
            "enabled": bool(not args.skip_bootstrap),
            "command": (
                [
                    sys.executable,
                    "tools/run_csv_bootstrap_e2e.py",
                    "--skip-heavy",
                    "--timeout",
                    "240",
                    "--out",
                    str(args.bootstrap_out),
                ]
                if not args.skip_bootstrap
                else []
            ),
            "run": bootstrap_res,
            "report_path": (str((ROOT / str(args.bootstrap_out)).resolve()) if not args.skip_bootstrap else ""),
            "report": bootstrap_obj,
        },
        "state_path": str(state_path),
    }

    next_state = dict(state) if isinstance(state, dict) else {}
    next_state.update(
        {
            "updated_at": _utc_now(),
            "last_fingerprint": fingerprint,
            "last_decision": str(final_decision),
            "last_report_path": str(out_path),
            "inventory": inventory,
        }
    )
    if str(final_decision) == "promote":
        lg = inspection.get("league_changes") if isinstance(inspection.get("league_changes"), dict) else {}
        next_state["last_promoted_at"] = _utc_now()
        next_state["known_raw_leagues_promoted"] = list(lg.get("raw_leagues") or [])
        next_state["known_canonical_leagues_promoted"] = list(lg.get("canonical_leagues") or [])
    _write_json(out_path, rep)
    _write_json(state_path, next_state)

    print(
        f"OK: csv ingest gate -> {out_path.name} | decision={final_decision} | "
        f"rows={int((inspection.get('metrics') or {}).get('rows_total') or 0)}"
    )
    return 0 if str(final_decision) == "promote" else (1 if str(final_decision) == "shadow_only" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
