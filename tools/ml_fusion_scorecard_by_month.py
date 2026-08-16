"""Fusion scorecard por MES — mesma matematica do ml_fusion_scorecard.py,
fatiada por mes do jogo, para ver o comportamento de inicio de season
(poucos jogos por time) vs meio/fim de season.

  python tools/ml_fusion_scorecard_by_month.py            # season 2026
"""
from __future__ import annotations

import argparse
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
    PlayersArtifact,
    compute_delta_and_confidence,
    lineup_for_game,
    load_match_player_rows,
    logit as _logit,
    sigmoid as _sigmoid,
)
from mlcore.tiers import tier_for_league
from mlcore.train_offline import (
    _infer_team_domestic_league_by_year,
    _infer_team_meta_latest,
    _resolve_home_league,
)
from tools.ml_quality_scorecard import _grade_from_logloss, _metrics, default_csvs

ROOT = Path(__file__).resolve().parents[1]


def _safe_year(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Fusion scorecard fatiado por mes.")
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--players", default="players_artifact.json")
    ap.add_argument("--csv", action="append", default=None)
    ap.add_argument("--season", type=int, default=None, help="Default: ano mais recente presente nos dados.")
    args = ap.parse_args()

    csvs = [p if Path(p).is_absolute() else str(ROOT / p) for p in (args.csv or default_csvs())]

    frames = []
    for p in csvs:
        try:
            df = load_oracle_elixir_games(p, keep_playoffs=None)
            if not df.empty:
                frames.append(df)
        except Exception as e:
            print(f"skip {p}: {e}")
    games = pd.concat(frames, ignore_index=True, join="inner")
    games["gameid"] = games["gameid"].astype(str)
    games["date"] = pd.to_datetime(games["date"], errors="coerce")
    games = games.dropna(subset=["date"]).drop_duplicates(subset=["gameid"], keep="last")
    games = games.sort_values(["date", "gameid"]).reset_index(drop=True)

    domestic_by_year = _infer_team_domestic_league_by_year(games)
    team_meta = _infer_team_meta_latest(domestic_by_year)
    player_rows = load_match_player_rows(csvs, keep_playoffs=None)

    art = MLArtifact.load_json(str(args.artifact))
    model = art.model
    pl_meta = dict((art.meta or {}).get("players_layer") or {})
    w_lineup = float(pl_meta.get("w_lineup", 0.0) or 0.0)
    p_art = PlayersArtifact.load_json(str(args.players))

    season = int(args.season) if args.season is not None else int(pd.to_numeric(games["year"], errors="coerce").max())
    by_month: dict[int, list[tuple[float, int]]] = {}
    for r in games.itertuples(index=False):
        if _safe_year(getattr(r, "year", None)) != season:
            continue
        blue, red = str(r.blue), str(r.red)
        try:
            y = int(r.blue_win)
        except (TypeError, ValueError):
            continue
        lg_match = str(getattr(r, "league", "") or "OTHER")
        yy = _safe_year(getattr(r, "year", None))
        bl = _resolve_home_league(team=blue, year=yy, match_league=lg_match,
                                  domestic_by_year=domestic_by_year, team_meta_latest=team_meta)
        rl = _resolve_home_league(team=red, year=yy, match_league=lg_match,
                                  domestic_by_year=domestic_by_year, team_meta_latest=team_meta)
        p0 = float(model.p_blue(blue, red, blue_league=bl, red_league=rl,
                                blue_tier=str(tier_for_league(bl)), red_tier=str(tier_for_league(rl))))

        blue_lineup, red_lineup = lineup_for_game(player_rows, str(r.gameid))
        res = compute_delta_and_confidence(
            p_art, blue_lineup=blue_lineup, red_lineup=red_lineup,
            as_of=pd.to_datetime(r.date).date(), match_league=lg_match,
        )
        d = float(res.get("delta", 0.0) or 0.0)
        cov_tot = float(res.get("coverage_total", 5) or 5.0)
        cov = float(res.get("coverage", 0) or 0.0) / (cov_tot if cov_tot else 5.0)
        fused = float(_sigmoid(_logit(p0) + w_lineup * (d * cov)))

        month = int(pd.to_datetime(r.date).month)
        by_month.setdefault(month, []).append((fused, y))

    print(f"\n=== FUSION por MES - season={season} (w_lineup={w_lineup:.4f}) ===")
    print(f"{'mes':>4} {'n':>6} {'logloss':>9} {'brier':>8} {'ece':>7} {'acc':>7} {'nota':>6}")
    for month in sorted(by_month):
        m = _metrics(by_month[month])
        print(f"{month:>4} {m['n']:>6} {m['logloss']:>9.4f} {m['brier']:>8.4f} "
              f"{m['ece']:>7.4f} {m['acc']:>7.3f} {_grade_from_logloss(m['logloss']):>6.1f}")

    early = [x for mo in (1, 2) for x in by_month.get(mo, [])]
    rest = [x for mo, rows in by_month.items() if mo not in (1, 2) for x in rows]
    for name, rows_seg in (("JAN-FEV (inicio, poucos jogos)", early), ("MAR+ (season andando)", rest)):
        if not rows_seg:
            continue
        m = _metrics(rows_seg)
        print(f"\n{name}: n={m['n']} logloss={m['logloss']:.4f} brier={m['brier']:.4f} "
              f"ece={m['ece']:.4f} acc={m['acc']:.3f} nota={_grade_from_logloss(m['logloss']):.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
