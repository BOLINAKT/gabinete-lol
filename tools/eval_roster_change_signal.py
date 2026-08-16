"""Feasibility probe for lever D (roster change).

Question: do games right after a roster change carry prediction error that the
CURRENT model (Elo + players) fails to absorb? If post-change games are clearly
worse-calibrated than stable games, lever D (regress team rating toward league
base on roster change) has headroom. If the players layer already handles it,
park D. This only MEASURES — it doesn't change anything.

  python tools/eval_roster_change_signal.py --season 2026
"""
from __future__ import annotations

import argparse
import math
import sys

# Console cp1252 no Windows derruba qualquer print com acento/emoji — e o estouro
# vem no fim, depois do trabalho todo feito. Ver tools/find_silent_failures.py.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mlcore.artifact import MLArtifact
from mlcore.io_oracle import load_oracle_elixir_games
from mlcore.players_layer import (
    PlayersArtifact, compute_delta_and_confidence, lineup_for_game,
    load_match_player_rows, logit as _logit, sigmoid as _sigmoid,
)
from mlcore.tiers import tier_for_league
from mlcore.train_offline import (
    _infer_team_domestic_league_by_year, _infer_team_meta_latest, _resolve_home_league,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSVS = [
    "CSV_HISTORICO/2024_LoL_esports_match_data_from_OraclesElixir.csv",
    "CSV_HISTORICO/2025_LoL_esports_match_data_from_OraclesElixir.csv",
    "CSV_DIARIO/2026_LoL_esports_match_data_from_OraclesElixir.csv",
]
LANES = ("Top", "Jungle", "Mid", "Bot", "Support")


def _ll(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def _changed(prev, cur, thresh=2):
    """True if >= thresh of 5 lane players differ from the team's previous game."""
    if not prev:
        return False
    diff = sum(1 for ln in LANES if str(prev.get(ln, "")) != str(cur.get(ln, "")))
    return diff >= thresh


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--players", default="players_artifact.json")
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()

    csvs = [str(ROOT / p) for p in DEFAULT_CSVS]
    frames = [load_oracle_elixir_games(p, keep_playoffs=None) for p in csvs]
    games = pd.concat([f for f in frames if not f.empty], ignore_index=True, join="inner")
    games["gameid"] = games["gameid"].astype(str)
    games["date"] = pd.to_datetime(games["date"], errors="coerce")
    games = games.dropna(subset=["date"]).drop_duplicates(subset=["gameid"], keep="last")
    games = games.sort_values(["date", "gameid"]).reset_index(drop=True)

    dby = _infer_team_domestic_league_by_year(games)
    tmeta = _infer_team_meta_latest(dby)
    prows = load_match_player_rows(csvs, keep_playoffs=None)
    art = MLArtifact.load_json(str(args.artifact)); model = art.model
    w = float((art.meta or {}).get("players_layer", {}).get("w_lineup", 0.0) or 0.0)
    part = PlayersArtifact.load_json(str(args.players))

    last_lineup: dict[str, dict] = {}
    buckets = {"changed": [0.0, 0], "stable": [0.0, 0]}  # fused logloss
    elo_buckets = {"changed": [0.0, 0], "stable": [0.0, 0]}
    for r in games.itertuples(index=False):
        blue, red, gid = str(r.blue), str(r.red), str(r.gameid)
        try:
            y = int(r.blue_win)
            yy = int(r.year)
        except (TypeError, ValueError):
            continue
        bl_lu, rl_lu = lineup_for_game(prows, gid)
        b_chg = _changed(last_lineup.get(blue), bl_lu)
        r_chg = _changed(last_lineup.get(red), rl_lu)
        if bl_lu:
            last_lineup[blue] = bl_lu
        if rl_lu:
            last_lineup[red] = rl_lu
        if yy != args.season:
            continue
        lg = str(getattr(r, "league", "") or "OTHER")
        bl = _resolve_home_league(team=blue, year=yy, match_league=lg, domestic_by_year=dby, team_meta_latest=tmeta)
        rl = _resolve_home_league(team=red, year=yy, match_league=lg, domestic_by_year=dby, team_meta_latest=tmeta)
        p0 = float(model.p_blue(blue, red, blue_league=bl, red_league=rl,
                                blue_tier=str(tier_for_league(bl)), red_tier=str(tier_for_league(rl))))
        res = compute_delta_and_confidence(part, blue_lineup=bl_lu, red_lineup=rl_lu,
                                           as_of=pd.to_datetime(r.date).date(), match_league=lg)
        cov_tot = float(res.get("coverage_total", 5) or 5.0)
        d_eff = float(res.get("delta", 0.0) or 0.0) * (float(res.get("coverage", 0) or 0.0) / (cov_tot or 5.0))
        fused = float(_sigmoid(_logit(p0) + w * d_eff))
        key = "changed" if (b_chg or r_chg) else "stable"
        buckets[key][0] += _ll(fused, y); buckets[key][1] += 1
        elo_buckets[key][0] += _ll(p0, y); elo_buckets[key][1] += 1

    print(f"\n=== roster-change signal {args.season} (logloss; menor=melhor) ===")
    print(f"{'bucket':10} {'n':>5} {'Elo':>9} {'Fusao':>9}")
    for k in ("stable", "changed"):
        ne = elo_buckets[k][1]; nf = buckets[k][1]
        e = elo_buckets[k][0] / max(1, ne); f = buckets[k][0] / max(1, nf)
        print(f"{k:10} {nf:>5} {e:>9.4f} {f:>9.4f}")
    print("\nLeitura: se 'changed' tem logloss bem PIOR que 'stable' na Fusao, lever D tem espaco.")
    print("Se a Fusao ja nivela changed~stable, a camada de players ja absorve -> park D.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
