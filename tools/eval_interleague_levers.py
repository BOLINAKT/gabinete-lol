"""Reusable harness to validate ML cross-region quality levers CHEAPLY.

Prequential (predict-before-update) interleague log-loss on an OOS season,
using the real EloModel. This is the fast gate we run BEFORE committing a
lever to the expensive full fit — so we never spend ~6h on a change that did
not prove a gain first.

Levers it can toggle (via --config or programmatic CONFIGS):
  - SOS league strength (Bradley-Terry on the interleague graph) → LEAGUE_BASE_POINTS
  - EloParams overrides (dynamic_k_enabled, league_strength_cap_abs, prior weights, ...)

Usage:
  python tools/eval_interleague_levers.py            # runs the default lever sweep
  python tools/eval_interleague_levers.py --oos-year 2026
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mlcore.stats_teams import build_team_games, load_team_rows
import mlcore.tiers as tiers
from mlcore.tiers import tier_for_league
from mlcore.elo import EloModel, EloParams

ROOT = Path(__file__).resolve().parents[1]
INTL = {"EWC", "MSI", "WORLDS", "FST", "IEM", "FIRST STAND"}
DEFAULT_CSVS = [
    "CSV_HISTORICO/2024_LoL_esports_match_data_from_OraclesElixir.csv",
    "CSV_HISTORICO/2025_LoL_esports_match_data_from_OraclesElixir.csv",
    "CSV_DIARIO/2026_LoL_esports_match_data_from_OraclesElixir.csv",
]


def load_games(csvs: list[str]) -> pd.DataFrame:
    frames = []
    for p in csvs:
        fp = p if Path(p).is_absolute() else str(ROOT / p)
        try:
            frames.append(build_team_games(load_team_rows(fp)))
        except Exception as e:
            print(f"skip {p}: {e}")
    df = pd.concat(frames, ignore_index=True)
    dom = df[~df["league"].astype(str).str.upper().isin(INTL)]
    tl = dom.groupby("team")["league"].agg(lambda s: s.astype(str).value_counts().index[0] if len(s) else "")
    df["dl"] = df["team"].map(tl)
    df["ol"] = df["opponent"].map(tl)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["win"] = pd.to_numeric(df["win"], errors="coerce")
    df = df.dropna(subset=["win", "date"])
    g = df[df["team"].astype(str) < df["opponent"].astype(str)].copy().sort_values("date")
    g["yr"] = g["date"].dt.year
    return g


_tier_cache: dict = {}
def _tier(lg: str) -> str:
    if lg not in _tier_cache:
        _tier_cache[lg] = str(tier_for_league(lg) or "OTHER")
    return _tier_cache[lg]


def bradley_terry_league_strength(g: pd.DataFrame, oos_year: int) -> dict:
    """BT (logistic) league strengths from TRAIN (pre-OOS) interleague games."""
    train = g[(g.yr < oos_year) & (g.dl != g.ol) & g.dl.ne("") & g.ol.ne("")]
    leagues = sorted(set(train.dl) | set(train.ol))
    idx = {l: i for i, l in enumerate(leagues)}
    A = np.zeros((len(train), len(leagues)))
    y = train["win"].to_numpy(dtype=float)
    for k, r in enumerate(train.itertuples(index=False)):
        A[k, idx[r.dl]] += 1.0
        A[k, idx[r.ol]] -= 1.0
    theta = np.zeros(len(leagues))
    lr, l2 = 0.5, 1e-3
    for _ in range(4000):
        p = 1.0 / (1.0 + np.exp(-(A @ theta)))
        theta -= lr * (A.T @ (p - y) / max(1, len(y)) + l2 * theta)
    theta -= theta.mean()
    return {l: float(theta[idx[l]]) for l in leagues}


def evaluate(g: pd.DataFrame, *, oos_year: int, league_points: dict | None = None,
             params: EloParams | None = None) -> tuple[float, int]:
    """Prequential interleague log-loss on OOS season. league_points overrides
    LEAGUE_BASE_POINTS during the run (restored after)."""
    saved = dict(tiers.LEAGUE_BASE_POINTS)
    if league_points is not None:
        tiers.LEAGUE_BASE_POINTS.clear()
        tiers.LEAGUE_BASE_POINTS.update(league_points)
    try:
        elo = EloModel(params or EloParams())
        tot, n = 0.0, 0
        for r in g.itertuples(index=False):
            bl, rl = r.dl, r.ol
            if bl and rl and bl != rl:
                if r.yr == oos_year:
                    p = float(elo.p_blue(r.team, r.opponent, blue_league=bl, red_league=rl,
                                         blue_tier=_tier(bl), red_tier=_tier(rl)))
                    p = min(max(p, 1e-6), 1 - 1e-6)
                    y = int(r.win)
                    tot += -(y * math.log(p) + (1 - y) * math.log(1 - p))
                    n += 1
            elo.update(str(r.team), str(r.opponent), int(r.win),
                       blue_league=bl or None, red_league=rl or None,
                       blue_tier=_tier(bl) if bl else None, red_tier=_tier(rl) if rl else None)
        return (tot / max(1, n), n)
    finally:
        tiers.LEAGUE_BASE_POINTS.clear()
        tiers.LEAGUE_BASE_POINTS.update(saved)


def main() -> int:
    ap = argparse.ArgumentParser(description="Cheap interleague quality-lever evaluation (prequential logloss).")
    ap.add_argument("--csv", action="append", default=None, help="CSV path (repeatable).")
    ap.add_argument("--oos-year", type=int, default=2026)
    ap.add_argument("--sos-scale", type=float, default=800.0, help="Points = scale * BT theta.")
    args = ap.parse_args()

    g = load_games(args.csv or DEFAULT_CSVS)
    n_inter = int(((g.dl != g.ol) & g.dl.ne("") & g.ol.ne("")).sum())
    print(f"games={len(g)} interleague_total={n_inter} oos_year={args.oos_year}")

    theta = bradley_terry_league_strength(g, args.oos_year)
    sos_pts = {l: float(args.sos_scale * t) for l, t in theta.items()}
    base = EloParams()

    configs = [
        ("baseline (atual)", None, base),
        ("A: SOS", sos_pts, base),
        ("A+C: SOS + dynamic_k(Glicko)", sos_pts, replace(base, dynamic_k_enabled=True)),
        ("A+B: SOS + cap 90", sos_pts, replace(base, league_strength_cap_abs=90.0)),
        ("A+B+C: SOS + cap90 + dynamic_k", sos_pts, replace(base, league_strength_cap_abs=90.0, dynamic_k_enabled=True)),
    ]
    base_ll = None
    print("\n=== logloss inter-liga OOS (menor = melhor) ===")
    for label, pts, prm in configs:
        ll, n = evaluate(g, oos_year=args.oos_year, league_points=pts, params=prm)
        if base_ll is None:
            base_ll = ll
        delta = ll - base_ll
        print(f"{label:38} logloss={ll:.4f} (n={n})  delta={delta:+.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
