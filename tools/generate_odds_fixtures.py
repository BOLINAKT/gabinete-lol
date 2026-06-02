from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mlcore.artifact import MLArtifact
from mlcore.bo import prob_win_series
from mlcore.regression_fixtures import upsert_odds_fixture_snapshot
from mlcore.utils import prob_to_decimal_odds


ANCHORS = [
    ("Team WE", "Top Esports"),
    ("T1", "Gen.G"),
    ("G2 Esports", "Fnatic"),
    ("ThunderTalk Gaming", "LNG Esports"),
]

INTERLEAGUE_ANCHORS = [
    ("Gen.G", "Bilibili Gaming"),
    ("T1", "Top Esports"),
    ("G2 Esports", "paiN Gaming"),
    ("FlyQuest", "CTBC Flying Oyster"),
    ("LOUD", "Team Liquid"),
    ("Cloud9", "PSG Talon"),
    ("Natus Vincere", "Myth Esports"),
    ("Once Upon A Team", "DRX Challengers"),
]


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
        "team_a": team_a,
        "team_b": team_b,
        "p_raw": p_raw,
        "p_map": p_map,
        "odd_map_a": float(prob_to_decimal_odds(p_map)),
        "odd_map_b": float(prob_to_decimal_odds(1.0 - p_map)),
        "p_bo3": p_bo3,
        "odd_bo3_a": float(prob_to_decimal_odds(p_bo3)),
        "odd_bo3_b": float(prob_to_decimal_odds(1.0 - p_bo3)),
        "p_bo5": p_bo5,
        "odd_bo5_a": float(prob_to_decimal_odds(p_bo5)),
        "odd_bo5_b": float(prob_to_decimal_odds(1.0 - p_bo5)),
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _pick_random_pairs(teams: list[str], n: int, seed: int) -> list[tuple[str, str]]:
    rnd = random.Random(seed)
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    while len(pairs) < n:
        a, b = rnd.sample(teams, 2)
        k = tuple(sorted((a, b)))
        if k in seen:
            continue
        seen.add(k)
        pairs.append((a, b))
    return pairs


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate odds regression fixtures from current artifact.")
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--out-small", default="mlcore/tests/fixtures/odds_regression.json")
    ap.add_argument("--out-large", default="mlcore/tests/fixtures/odds_regression_40.json")
    ap.add_argument("--out-interleague", default="mlcore/tests/fixtures/interleague_matchups_regression.json")
    ap.add_argument("--random-count", type=int, default=36)
    ap.add_argument("--seed", type=int, default=20260210)
    ap.add_argument("--min-games", type=int, default=8)
    args = ap.parse_args()

    art_path = Path(str(args.artifact)).expanduser().resolve()
    art = MLArtifact.load_json(str(art_path))
    art_sha = _sha256(art_path)
    teams = sorted([t for t, gp in art.model.games_played.items() if int(gp) >= int(args.min_games)])

    # Small fixture: deterministic anchors that user always tracks.
    small_rows = [_predict(art, a, b) for (a, b) in ANCHORS]

    # Large fixture: anchors + random deterministic set.
    anchor_set = {tuple(sorted((a, b))) for (a, b) in ANCHORS}
    random_pairs = _pick_random_pairs(teams, int(args.random_count), int(args.seed))
    merged_pairs = list(ANCHORS)
    for a, b in random_pairs:
        if tuple(sorted((a, b))) in anchor_set:
            continue
        merged_pairs.append((a, b))
        if len(merged_pairs) >= (len(ANCHORS) + int(args.random_count)):
            break

    large_rows = [_predict(art, a, b) for (a, b) in merged_pairs]

    small_snapshot = {
        "artifact_file": art_path.name,
        "artifact_sha256": art_sha,
        "method": "avg_forward_reverse_calibrated",
        "matchups": small_rows,
    }
    large_snapshot = {
        "artifact_file": art_path.name,
        "artifact_sha256": art_sha,
        "method": "avg_forward_reverse_calibrated",
        "seed": int(args.seed),
        "min_games": int(args.min_games),
        "matchups": large_rows,
    }
    interleague_rows = [_predict(art, a, b) for (a, b) in INTERLEAGUE_ANCHORS]
    interleague_snapshot = {
        "artifact_file": art_path.name,
        "artifact_sha256": art_sha,
        "method": "avg_forward_reverse_calibrated",
        "scope": "interleague_only",
        "matchups": interleague_rows,
    }

    out_small = Path(str(args.out_small)).expanduser()
    out_large = Path(str(args.out_large)).expanduser()
    out_interleague = Path(str(args.out_interleague)).expanduser()
    small_payload = {}
    large_payload = {}
    interleague_payload = {}
    try:
        if out_small.exists():
            small_payload = json.loads(out_small.read_text(encoding="utf-8"))
            if not isinstance(small_payload, dict):
                small_payload = {}
    except Exception:
        small_payload = {}
    try:
        if out_large.exists():
            large_payload = json.loads(out_large.read_text(encoding="utf-8"))
            if not isinstance(large_payload, dict):
                large_payload = {}
    except Exception:
        large_payload = {}
    try:
        if out_interleague.exists():
            interleague_payload = json.loads(out_interleague.read_text(encoding="utf-8"))
            if not isinstance(interleague_payload, dict):
                interleague_payload = {}
    except Exception:
        interleague_payload = {}

    small_out = upsert_odds_fixture_snapshot(
        small_payload,
        artifact_sha256=art_sha,
        snapshot=small_snapshot,
    )
    large_out = upsert_odds_fixture_snapshot(
        large_payload,
        artifact_sha256=art_sha,
        snapshot=large_snapshot,
    )
    interleague_out = upsert_odds_fixture_snapshot(
        interleague_payload,
        artifact_sha256=art_sha,
        snapshot=interleague_snapshot,
    )
    out_small.write_text(json.dumps(small_out, ensure_ascii=False, indent=2), encoding="utf-8")
    out_large.write_text(json.dumps(large_out, ensure_ascii=False, indent=2), encoding="utf-8")
    out_interleague.write_text(json.dumps(interleague_out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] small={args.out_small} ({len(small_rows)} matchups)")
    print(f"[ok] large={args.out_large} ({len(large_rows)} matchups)")
    print(f"[ok] interleague={args.out_interleague} ({len(interleague_rows)} matchups)")


if __name__ == "__main__":
    main()
