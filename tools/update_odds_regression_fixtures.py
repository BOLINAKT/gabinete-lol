from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mlcore.artifact import MLArtifact
from mlcore.bo import prob_win_series
from mlcore.regression_fixtures import upsert_odds_fixture_snapshot
from mlcore.utils import prob_to_decimal_odds


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _predict(art: MLArtifact, team_a: str, team_b: str) -> dict:
    p_raw_f = float(art.model.p_blue(team_a, team_b))
    p_raw_r = float(art.model.p_blue(team_b, team_a))
    p_raw = 0.5 * (p_raw_f + (1.0 - p_raw_r))
    p_cal_f = float(art.calibrator.predict_proba(p_raw_f))
    p_cal_r = float(art.calibrator.predict_proba(p_raw_r))
    p_map = 0.5 * (p_cal_f + (1.0 - p_cal_r))
    p_bo3 = float(prob_win_series(p_map, 3))
    p_bo5 = float(prob_win_series(p_map, 5))
    return {
        "team_a": str(team_a),
        "team_b": str(team_b),
        "p_raw": float(p_raw),
        "p_map": float(p_map),
        "odd_map_a": float(prob_to_decimal_odds(p_map)),
        "odd_map_b": float(prob_to_decimal_odds(1.0 - p_map)),
        "p_bo3": float(p_bo3),
        "odd_bo3_a": float(prob_to_decimal_odds(p_bo3)),
        "odd_bo3_b": float(prob_to_decimal_odds(1.0 - p_bo3)),
        "p_bo5": float(p_bo5),
        "odd_bo5_a": float(prob_to_decimal_odds(p_bo5)),
        "odd_bo5_b": float(prob_to_decimal_odds(1.0 - p_bo5)),
    }


def _update_fixture(path: Path, art: MLArtifact, artifact_file: str, artifact_sha256: str) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("matchups", [])
    if not isinstance(rows, list) or len(rows) == 0:
        snaps = data.get("snapshots") if isinstance(data.get("snapshots"), dict) else {}
        latest = str(data.get("latest_artifact_sha256") or "").strip()
        row_src = snaps.get(latest) if latest and isinstance(snaps.get(latest), dict) else None
        if not isinstance(row_src, dict):
            for _v in snaps.values():
                if isinstance(_v, dict) and isinstance(_v.get("matchups"), list) and _v.get("matchups"):
                    row_src = _v
                    break
        rows = list((row_src or {}).get("matchups") or [])

    out_rows = []
    for row in rows:
        ta = str(row.get("team_a", "") or "").strip()
        tb = str(row.get("team_b", "") or "").strip()
        if not ta or not tb:
            continue
        out_rows.append(_predict(art, ta, tb))
    snapshot = {
        "artifact_file": artifact_file,
        "artifact_sha256": artifact_sha256,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "method": "avg_forward_reverse_calibrated",
        "matchups": out_rows,
    }
    data = upsert_odds_fixture_snapshot(data, artifact_sha256=artifact_sha256, snapshot=snapshot)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Update odds regression fixtures from current ml_artifact.json.")
    parser.add_argument("--root", type=str, default=".", help="Project root path.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    artifact_path = root / "ml_artifact.json"
    if not artifact_path.exists():
        raise FileNotFoundError(f"Artifact not found: {artifact_path}")
    fixtures_dir = root / "mlcore" / "tests" / "fixtures"
    files = [
        fixtures_dir / "odds_regression.json",
        fixtures_dir / "odds_regression_40.json",
        fixtures_dir / "key_matchups_regression.json",
        fixtures_dir / "key_matchups_extended_regression.json",
        fixtures_dir / "interleague_matchups_regression.json",
    ]
    for fp in files:
        if not fp.exists():
            raise FileNotFoundError(f"Fixture not found: {fp}")

    art = MLArtifact.load_json(str(artifact_path))
    sha = _sha256(artifact_path)
    for fp in files:
        _update_fixture(fp, art, artifact_path.name, sha)
    print(f"Updated fixtures with artifact sha256={sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
