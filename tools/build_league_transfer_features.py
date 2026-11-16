from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app_core.identity_registry_core import load_identity_registry
from mlcore.league_transfer_builder import build_league_transfer_features_from_csvs


def _default_csvs(root: Path) -> list[Path]:
    return [
        root / "CSV_HISTORICO" / "2024_LoL_esports_match_data_from_OraclesElixir.csv",
        root / "CSV_HISTORICO" / "2025_LoL_esports_match_data_from_OraclesElixir.csv",
        root / "CSV_DIARIO" / "2026_LoL_esports_match_data_from_OraclesElixir.csv",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build league transfer features artifact.")
    parser.add_argument("--root", default=".", help="Repo root.")
    parser.add_argument("--csv", action="append", default=[], help="Oracle CSV path. Repeat for multiple files.")
    parser.add_argument("--identity-registry", default="identity_registry.json", help="Identity registry path.")
    parser.add_argument("--out", default="league_transfer_features.json", help="Output JSON path.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    csv_paths = [Path(path).resolve() for path in (args.csv or [])]
    if not csv_paths:
        csv_paths = [path.resolve() for path in _default_csvs(root) if path.exists()]
    identity_path = Path(args.identity_registry)
    if not identity_path.is_absolute():
        identity_path = (root / identity_path).resolve()
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = (root / out_path).resolve()

    payload = build_league_transfer_features_from_csvs(
        csv_paths,
        identity_registry=load_identity_registry(identity_path),
    )
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out_path), "meta": payload.get("meta", {})}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
