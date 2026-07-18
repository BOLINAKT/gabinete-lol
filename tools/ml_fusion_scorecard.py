"""Fusion scorecard - measures the REAL product: Elo + players (w_lineup).

The Elo scorecard (ml_quality_scorecard.py) grades only the Elo core
(model.p_blue). But the team odds the app actually serves come from the FUSED
prediction: sigmoid(logit(elo_p) + w_lineup * delta_players). This script
replays every game of a season through that exact fused path (same league
inference and players math as train_offline) and reports Elo-only vs Fused
metrics, split inter-league / same-league, so we can see whether — and where —
the players layer actually improves what you bet on.

  python tools/ml_fusion_scorecard.py            # live artifacts, season 2026
"""
from __future__ import annotations

import argparse
import sys
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
    ap = argparse.ArgumentParser(description="Fusion (Elo+players) quality scorecard.")
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
    elo_inter, elo_same, fus_inter, fus_same = [], [], [], []
    n_delta_nonzero = 0
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
        d_eff = d * cov
        if abs(d_eff) > 1e-9:
            n_delta_nonzero += 1
        fused = float(_sigmoid(_logit(p0) + w_lineup * d_eff))

        if bl != rl:
            elo_inter.append((p0, y)); fus_inter.append((fused, y))
        else:
            elo_same.append((p0, y)); fus_same.append((fused, y))

    print(f"\n=== FUSION SCORECARD (Elo+players) - {args.artifact} + {args.players} - season={season} ===")
    print(f"w_lineup={w_lineup:.4f} | jogos com delta!=0: {n_delta_nonzero}")
    print(f"{'segmento':12} {'n':>5} {'modelo':>8} {'logloss':>9} {'brier':>8} {'ece':>7} {'acc':>7} {'nota':>6}")
    rows = [
        ("inter-liga", elo_inter, fus_inter),
        ("mesma-liga", elo_same, fus_same),
        ("GERAL", elo_inter + elo_same, fus_inter + fus_same),
    ]
    fused_blend = {}
    for name, elo_rows, fus_rows in rows:
        me, mf = _metrics(elo_rows), _metrics(fus_rows)
        print(f"{name:12} {me['n']:>5} {'Elo':>8} {me['logloss']:>9.4f} {me['brier']:>8.4f} "
              f"{me['ece']:>7.4f} {me['acc']:>7.3f} {_grade_from_logloss(me['logloss']):>6.1f}")
        print(f"{'':12} {mf['n']:>5} {'Fusao':>8} {mf['logloss']:>9.4f} {mf['brier']:>8.4f} "
              f"{mf['ece']:>7.4f} {mf['acc']:>7.3f} {_grade_from_logloss(mf['logloss']):>6.1f}")
        fused_blend[name] = mf["logloss"]
    nota_elo = 0.45 * _grade_from_logloss(_metrics(elo_inter)["logloss"]) + 0.55 * _grade_from_logloss(_metrics(elo_same)["logloss"])
    nota_fus = 0.45 * _grade_from_logloss(fused_blend["inter-liga"]) + 0.55 * _grade_from_logloss(fused_blend["mesma-liga"])
    print(f"\nNOTA Elo-core   (45% inter + 55% mesma): {nota_elo:.2f} / 10")
    print(f"NOTA FUSAO (real) (45% inter + 55% mesma): {nota_fus:.2f} / 10")
    try:
        import json as _json
        import time as _time
        from pathlib import Path as _Path
        _ev = _Path(__file__).resolve().parents[1] / "evidence"
        _ev.mkdir(exist_ok=True)
        (_ev / "fusion_scorecard.json").write_text(_json.dumps({
            "generated_at": _time.strftime("%Y-%m-%dT%H:%M:%S"),
            "nota_fusao": round(float(nota_fus), 2), "nota_elo_core": round(float(nota_elo), 2),
            "inter_logloss": round(float(fused_blend["inter-liga"]), 4),
            "same_logloss": round(float(fused_blend["mesma-liga"]), 4),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
