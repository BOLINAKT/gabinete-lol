"""Refresh expected snapshots in ml_parity_golden fixture."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mlcore.tests.test_ml_parity_golden import TestMlParityGolden


def _refresh_fixture(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    harness = TestMlParityGolden()
    harness.fixture_path = path
    harness.fixture = payload
    harness.tol = float(payload.get("tolerance", 1e-8) or 1e-8)

    for row in payload.get("scenarios", []):
        if not isinstance(row, dict):
            continue
        out = harness._run_scenario(row)
        row["expected"] = harness._extract_snapshot(out)

    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh ml parity golden fixture snapshots.")
    parser.add_argument(
        "--fixture",
        default="mlcore/tests/fixtures/ml_parity_golden.json",
        help="Fixture path to refresh.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check whether fixture is up to date; do not write.",
    )
    args = parser.parse_args()

    fixture_path = Path(args.fixture).resolve()
    if not fixture_path.exists():
        raise FileNotFoundError(f"Fixture not found: {fixture_path}")

    updated = _refresh_fixture(fixture_path)
    current = fixture_path.read_text(encoding="utf-8")

    if args.check:
        if current != updated:
            print("ml_parity_golden fixture is stale. Run without --check to refresh.")
            return 1
        print("ml_parity_golden fixture is up to date.")
        return 0

    fixture_path.write_text(updated, encoding="utf-8")
    print(f"Updated fixture: {fixture_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
