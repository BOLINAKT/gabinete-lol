"""Pure-OOS prequential check for lever C (dynamic_k), BOTH segments.

The faithful artifact scorecard compares two frozen artifacts, but it scores
2026 games that were (mostly) in training — so part of the gain could be
in-sample fit. This script is the honest OOS counterpart: it walks the games in
date order and, for each 2026 game, predicts BEFORE updating (prequential), so
no game is ever scored after the model saw it. It reports inter-league AND
same-league log-loss for base / SOS / SOS+dynamic_k, so we can confirm the
dynamic_k gain generalizes out-of-sample in both segments before deploying.

  python tools/eval_dynamic_k_both_segments.py --oos-year 2026 --sos-scale 400
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mlcore.elo import EloModel, EloParams
from tools.eval_interleague_levers import _tier, load_games, sos_points_from_train


def evaluate_both(g, *, oos_year, league_points=None, params=None):
    """Prequential log-loss split into (inter, same) for the OOS season."""
    elo = EloModel(params or EloParams())
    if league_points:
        elo.league_base_points_map = dict(league_points)
    acc = {"inter": [0.0, 0], "same": [0.0, 0]}
    for r in g.itertuples(index=False):
        bl, rl = r.dl, r.ol
        if bl and rl and r.yr == oos_year:
            p = float(elo.p_blue(r.team, r.opponent, blue_league=bl, red_league=rl,
                                 blue_tier=_tier(bl), red_tier=_tier(rl)))
            p = min(max(p, 1e-6), 1 - 1e-6)
            y = int(r.win)
            seg = "inter" if bl != rl else "same"
            acc[seg][0] += -(y * math.log(p) + (1 - y) * math.log(1 - p))
            acc[seg][1] += 1
        elo.update(str(r.team), str(r.opponent), int(r.win),
                   blue_league=bl or None, red_league=rl or None,
                   blue_tier=_tier(bl) if bl else None, red_tier=_tier(rl) if rl else None)
    return {k: (v[0] / max(1, v[1]), v[1]) for k, v in acc.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description="Prequential OOS check for dynamic_k (both segments).")
    ap.add_argument("--csv", action="append", default=None)
    ap.add_argument("--oos-year", type=int, default=2026)
    ap.add_argument("--sos-scale", type=float, default=400.0)
    args = ap.parse_args()

    g = load_games(args.csv or None) if args.csv else load_games(
        [str(Path(__file__).resolve().parents[1] / p) for p in (
            "CSV_HISTORICO/2024_LoL_esports_match_data_from_OraclesElixir.csv",
            "CSV_HISTORICO/2025_LoL_esports_match_data_from_OraclesElixir.csv",
            "CSV_DIARIO/2026_LoL_esports_match_data_from_OraclesElixir.csv",
        )]
    )
    sos = sos_points_from_train(g, args.oos_year, args.sos_scale)
    base = EloParams()
    configs = [
        ("baseline", None, base),
        ("SOS", sos, base),
        ("SOS + dynamic_k", sos, replace(base, dynamic_k_enabled=True)),
    ]
    print(f"\n=== prequencial OOS {args.oos_year} (logloss; menor=melhor) ===")
    print(f"{'config':18} {'inter':>16} {'same':>16}")
    ref = {}
    for label, pts, prm in configs:
        m = evaluate_both(g, oos_year=args.oos_year, league_points=pts, params=prm)
        if not ref:
            ref = m
        di = m["inter"][0] - ref["inter"][0]
        ds = m["same"][0] - ref["same"][0]
        print(f"{label:18} {m['inter'][0]:.4f} (n={m['inter'][1]:>4}) d={di:+.4f}"
              f"  {m['same'][0]:.4f} (n={m['same'][1]:>4}) d={ds:+.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
