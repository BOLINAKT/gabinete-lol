from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mlcore.league_context import is_explicit_interregional_league_label, league_macro_key
from mlcore.tiers import LEAGUE_BASE_POINTS, LEAGUE_TO_TIER, canonical_league, tier_for_league


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _default_csvs() -> List[Path]:
    out: List[Path] = []
    for sub in ("CSV_HISTORICO", "CSV_DIARIO"):
        base = ROOT / sub
        if base.exists():
            out.extend(sorted([p for p in base.glob("*.csv") if p.is_file()]))
    return out


def _collect_counts(csv_paths: List[Path]) -> Dict[str, Dict[str, int]]:
    counts: Dict[str, Dict[str, int]] = {}
    for path in csv_paths:
        try:
            df = pd.read_csv(path, low_memory=False, usecols=lambda c: str(c or "").strip().lower() == "league")
        except Exception:
            continue
        if "league" not in {str(c).strip().lower() for c in df.columns}:
            continue
        league_col = next(c for c in df.columns if str(c).strip().lower() == "league")
        vc = df[league_col].fillna("").astype(str).str.strip().str.upper().value_counts()
        for raw, n in vc.to_dict().items():
            if not raw:
                continue
            row = counts.setdefault(str(raw), {"rows": 0, "files": 0})
            row["rows"] = int(row.get("rows", 0) + int(n))
            row["files"] = int(row.get("files", 0) + 1)
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit observed league catalog from CSVs against canonical/tier/macro mapping.")
    ap.add_argument("--csv", action="append", default=[])
    ap.add_argument("--out", default="ops/csv_ingest/league_catalog_audit.json")
    args = ap.parse_args()

    csv_paths = [Path(x).expanduser().resolve() for x in (args.csv or [])]
    if not csv_paths:
        csv_paths = _default_csvs()

    counts = _collect_counts(csv_paths)
    rows: List[Dict[str, Any]] = []
    fallback_count = 0
    interregional_count = 0

    for raw in sorted(counts.keys()):
        canonical = str(canonical_league(raw) or raw).strip().upper()
        tier = str(tier_for_league(raw) or "")
        macro = str(league_macro_key(raw, unknown="OTHER") or "OTHER")
        explicit_inter = bool(is_explicit_interregional_league_label(raw))
        if explicit_inter:
            interregional_count += 1
        uses_direct_tier_map = bool(canonical in LEAGUE_TO_TIER)
        uses_base_points = bool(canonical in LEAGUE_BASE_POINTS)
        uses_fallback_tier = bool(not uses_direct_tier_map)
        if uses_fallback_tier:
            fallback_count += 1
        rows.append(
            {
                "raw": str(raw),
                "canonical": canonical,
                "rows": int((counts.get(raw) or {}).get("rows") or 0),
                "files": int((counts.get(raw) or {}).get("files") or 0),
                "tier": tier,
                "macro": macro,
                "explicit_interregional": explicit_inter,
                "uses_direct_tier_map": uses_direct_tier_map,
                "uses_fallback_tier": uses_fallback_tier,
                "has_explicit_base_points": uses_base_points,
            }
        )

    rows.sort(key=lambda r: (-int(r.get("rows") or 0), str(r.get("raw") or "")))
    out = {
        "version": "league_catalog_audit_v1",
        "generated_at": _utc_now(),
        "csvs": [str(p) for p in csv_paths],
        "summary": {
            "raw_leagues": len(rows),
            "fallback_tier_leagues": int(fallback_count),
            "explicit_interregional_leagues": int(interregional_count),
        },
        "rows": rows,
    }

    out_path = (ROOT / str(args.out)).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"OK: league catalog audit -> {out_path.name} | "
        f"raw={len(rows)} fallback={int(fallback_count)} interregional={int(interregional_count)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
