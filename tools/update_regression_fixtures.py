from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _run_checked(cmd: list[str], *, cwd: Path) -> None:
    cp = subprocess.run(cmd, cwd=str(cwd), text=True)
    if int(cp.returncode) != 0:
        raise SystemExit(int(cp.returncode))


def main() -> int:
    ap = argparse.ArgumentParser(description="Update all regression fixtures from current local artifacts.")
    ap.add_argument("--root", type=str, default=".", help="Project root.")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    commands = [
        [sys.executable, "tools/update_odds_regression_fixtures.py", "--root", str(root)],
        [sys.executable, "tools/update_players_fusion_regression_fixture.py", "--root", str(root)],
    ]
    for cmd in commands:
        _run_checked(cmd, cwd=root)
    print("Updated all regression fixtures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
