"""Generate consolidated model health report (walk-forward + calibration diagnostics).

Usage:
  python tools/model_health_report.py --csv path1.csv --csv path2.csv --artifact ml_artifact.json --players-artifact players_artifact.json --out model_health_report.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    # Supports both: `python -m tools.model_health_report` and `python tools/model_health_report.py`.
    sys.path.insert(0, str(ROOT))

from mlcore.calibration_diagnostics import run_calibration_diagnostics
from mlcore.walkforward_report import run_walkforward


def generate_health_report(
    *,
    csv_paths: List[str],
    artifact_path: str,
    players_artifact_path: str,
    min_train_games: int = 1500,
    k: float = 26.0,
    scale: float = 400.0,
    bins: int = 10,
    min_league_games: int = 250,
    team_scale: float = 1.0,
    players_scale: float = 1.0,
) -> Dict[str, Any]:
    csvs = [str(Path(p).expanduser()) for p in csv_paths]
    try:
        wf = run_walkforward(
            csvs,
            min_train_games=int(min_train_games),
            k=float(k),
            scale=float(scale),
            artifact_path=str(Path(artifact_path).expanduser()),
            players_artifact_path=str(Path(players_artifact_path).expanduser()),
            team_scale=float(team_scale),
            players_scale=float(players_scale),
            bins=int(bins),
            min_league_games=int(min_league_games),
        )
    except Exception as e:
        wf = {"error": f"walkforward_exception: {e}"}

    try:
        cal = run_calibration_diagnostics(
            artifact_path=str(Path(artifact_path).expanduser()),
            players_artifact_path=str(Path(players_artifact_path).expanduser()),
            csv_paths=csvs,
            team_scale=float(team_scale),
            players_scale=float(players_scale),
            bins=int(bins),
            min_league_games=int(min_league_games),
        )
    except Exception as e:
        cal = {"error": f"calibration_exception: {e}"}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {
            "csv_paths": csvs,
            "artifact_path": str(Path(artifact_path).expanduser()),
            "players_artifact_path": str(Path(players_artifact_path).expanduser()),
            "min_train_games": int(min_train_games),
            "k": float(k),
            "scale": float(scale),
            "bins": int(bins),
            "min_league_games": int(min_league_games),
            "team_scale": float(team_scale),
            "players_scale": float(players_scale),
        },
        "walkforward": wf,
        "calibration": cal,
    }


def main() -> None:
    os.chdir(ROOT)
    ap = argparse.ArgumentParser(description="Consolidated model health report.")
    ap.add_argument("--csv", action="append", required=True, help="CSV path (repeat for multiple files).")
    ap.add_argument("--artifact", required=True, help="Path to ml_artifact.json")
    ap.add_argument("--players-artifact", required=True, help="Path to players_artifact.json")
    ap.add_argument("--out", default="model_health_report.json", help="Output JSON path")
    ap.add_argument("--min-train-games", type=int, default=1500)
    ap.add_argument("--k", type=float, default=26.0)
    ap.add_argument("--scale", type=float, default=400.0)
    ap.add_argument("--bins", type=int, default=10)
    ap.add_argument("--min-league-games", type=int, default=250)
    ap.add_argument("--team-scale", type=float, default=1.0)
    ap.add_argument("--players-scale", type=float, default=1.0)
    args = ap.parse_args()

    rep = generate_health_report(
        csv_paths=[str(x) for x in args.csv],
        artifact_path=str(args.artifact),
        players_artifact_path=str(args.players_artifact),
        min_train_games=int(args.min_train_games),
        k=float(args.k),
        scale=float(args.scale),
        bins=int(args.bins),
        min_league_games=int(args.min_league_games),
        team_scale=float(args.team_scale),
        players_scale=float(args.players_scale),
    )
    out = Path(str(args.out)).expanduser()
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[health] saved:", str(out))
    wf_overall = (rep.get("walkforward") or {}).get("overall", {})
    print("[health] walkforward_overall:", json.dumps(wf_overall, ensure_ascii=False))


if __name__ == "__main__":
    main()
