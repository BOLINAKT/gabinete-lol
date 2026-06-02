"""Backfill the picks tracker from the user's betting spreadsheets.

Reads the monthly sheets (01..12) of one or more xlsx files, parses each
LoL single-market bet via app_core.picks_import_core, and writes them into
ops/picks_tracker.json with source="xlsx".

Idempotent: re-running replaces xlsx-sourced picks (matched by deterministic
id) instead of duplicating. Manual picks (source="manual") are preserved.

Usage:
    python tools/import_picks_xlsx.py --dry-run \
        --file "C:/.../PLANILHA APOSTAS 2026 - PESSOAL (1).xlsx" \
        --file "C:/.../PLANILHA APOSTAS 2025 - PESSOAL.xlsx"

    python tools/import_picks_xlsx.py --commit --file ... --file ...
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Force UTF-8 stdout so accents / arrows don't crash on the Windows cp1252 console.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except (AttributeError, ValueError):
    pass

import pandas as pd

from app_core.picks_import_core import parse_pick_row
from app_core.picks_tracker_core import (
    Pick,
    _compute_pick_id,
    load_picks,
    save_picks,
)

TRACKER_PATH = str(ROOT / "ops" / "picks_tracker.json")
HEADER_ROW = 6  # 0-indexed; the monthly sheets put column names on row 7
CORE_COLS = 26


def _monthly_sheets(xl: pd.ExcelFile) -> list[str]:
    return [s for s in xl.sheet_names if str(s).isdigit() and len(str(s)) <= 2]


def _rows_from_file(path: str) -> list[dict]:
    out: list[dict] = []
    xl = pd.ExcelFile(path)
    for sheet in _monthly_sheets(xl):
        try:
            df = pd.read_excel(path, sheet_name=sheet, header=HEADER_ROW).iloc[:, :CORE_COLS]
        except Exception as exc:
            print(f"  [warn] {path} sheet {sheet}: {type(exc).__name__}: {exc}")
            continue
        df = df.dropna(subset=["Data", "Aposta"], how="any")
        for _, r in df.iterrows():
            out.append(r.to_dict())
    return out


def _build_pick(kwargs: dict) -> Pick:
    # Include the map label in the id seed so per-map bets on the same
    # day/matchup/line stay distinct (import-only; tracker id is unchanged).
    mapa = str(kwargs.get("mapa", "") or "")
    pid = _compute_pick_id(
        kwargs["ts"] + ("|" + mapa if mapa else ""),
        kwargs["team_a"], kwargs["team_b"],
        kwargs["metric_key"], kwargs["side_key"], kwargs.get("line"),
    )
    return Pick(
        id=pid,
        ts=kwargs["ts"],
        team_a=kwargs["team_a"], team_b=kwargs["team_b"],
        league=kwargs["league"],
        metric_key=kwargs["metric_key"], side_key=kwargs["side_key"],
        line=kwargs.get("line"),
        odd_casa=float(kwargs.get("odd_casa") or 0.0),
        stake_units=float(kwargs.get("stake_units") or 0.0),
        p_hist=None, edge_hist_pct=None,
        status=kwargs["status"],
        profit_units=kwargs.get("profit_units"),
        resolved_at=None, resolved_gameid=None,
        source="xlsx",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", action="append", required=True, help="xlsx path (repeatable)")
    ap.add_argument("--dry-run", action="store_true", help="parse + report only, no write")
    ap.add_argument("--commit", action="store_true", help="write to tracker json")
    args = ap.parse_args()

    if not args.dry_run and not args.commit:
        print("Especifique --dry-run ou --commit.")
        return 2

    all_rows: list[dict] = []
    for f in args.file:
        if not Path(f).exists():
            print(f"[erro] arquivo não encontrado: {f}")
            return 1
        rows = _rows_from_file(f)
        print(f"{Path(f).name}: {len(rows)} linhas com aposta")
        all_rows.extend(rows)

    parsed: list[dict] = []
    skipped = Counter()
    for r in all_rows:
        pk = parse_pick_row(r)
        if pk is None:
            # Classify why skipped (for the report).
            sport = str(r.get("Esporte", "")).strip().upper()
            if sport != "LOL":
                skipped["não-LoL"] += 1
            else:
                skipped[f"mercado não suportado: {str(r.get('Aposta',''))[:24]}"] += 1
            continue
        parsed.append(pk)

    # Dedup by id (a bet can appear once; keep last).
    by_id: dict[str, Pick] = {}
    for pk in parsed:
        built = _build_pick(pk)
        by_id[built.id] = built
    picks_xlsx = list(by_id.values())

    # Report
    print("\n=== RELATÓRIO ===")
    print(f"Linhas lidas:           {len(all_rows)}")
    print(f"Importaveis (LoL unico): {len(parsed)}  -> {len(picks_xlsx)} unicas")
    n_won = sum(1 for p in picks_xlsx if p.status == "won")
    n_lost = sum(1 for p in picks_xlsx if p.status == "lost")
    n_void = sum(1 for p in picks_xlsx if p.status == "void")
    print(f"  W-L-V: {n_won}-{n_lost}-{n_void}")
    by_market = Counter(p.metric_key for p in picks_xlsx)
    print("  Por mercado:", dict(by_market))
    print("\nPuladas (top 12):")
    for reason, n in skipped.most_common(12):
        print(f"  {n:5} | {reason}")

    if args.dry_run:
        print("\n[dry-run] nada gravado.")
        return 0

    # Commit: preserve manual picks, replace xlsx ones.
    existing = load_picks(TRACKER_PATH)
    manual = [p for p in existing if getattr(p, "source", "manual") != "xlsx"]
    merged = manual + picks_xlsx
    save_picks(TRACKER_PATH, merged)
    print(f"\n[commit] gravado em {TRACKER_PATH}")
    print(f"  manuais preservadas: {len(manual)} · xlsx: {len(picks_xlsx)} · total: {len(merged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
