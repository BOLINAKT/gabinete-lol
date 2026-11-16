"""Phase 10: Train and validate player-prop models (v1 = kills).

Predicts expected kills per (player × champion × position) per game from the
player's recent rolling stats + game context (league, BO, playoffs, team
strength). Uses residual sigma → P(over X) via normal CDF for over/under
markets.

Gate: paired bootstrap delta_RMSE vs the per-player rolling mean baseline.
"""
from __future__ import annotations

import argparse
import json
import random
import sys

# Console cp1252 no Windows derruba qualquer print com acento/emoji — e o estouro
# vem no fim, depois do trabalho todo feito. Ver tools/find_silent_failures.py.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd

from mlcore.artifact import MLArtifact
from mlcore.calibration import fit_platt_from_raw_probs
from mlcore.calibration_diagnostics import _apply_microseg_calibration, _read_json_file_safe
from mlcore.fit_ml_params import _build_lineup_cache, _fuse_probs_by_precision, _make_samples
from mlcore.players_layer import PlayersArtifact, load_match_player_rows
from mlcore.utils import clip_prob

from mlcore.live_ml import (
    PlayerPropModel, build_player_kill_features,
)


def _gather_csvs(paths: List[str]) -> List[str]:
    out = []
    for p in paths:
        pp = Path(p).expanduser()
        if pp.is_dir():
            for f in sorted(pp.glob("*.csv")):
                out.append(str(f))
        elif pp.exists():
            out.append(str(pp))
    return out


def _load_player_rows(csv_paths: List[str]) -> pd.DataFrame:
    chunks = []
    for p in csv_paths:
        df = pd.read_csv(p, low_memory=False)
        df = df[df["position"].isin(["top", "jng", "mid", "bot", "sup"])].copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date", "gameid", "playername", "champion", "kills"])
        chunks.append(df)
    return pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()


def _load_games_multi(csv_paths):
    from mlcore.io_oracle import load_oracle_elixir_games
    chunks = []
    for p in csv_paths:
        d = load_oracle_elixir_games(str(p), keep_playoffs=None)
        if d is not None and not d.empty:
            d2 = d.dropna(how="all").dropna(axis=1, how="all")
            if not d2.empty:
                chunks.append(d2)
    if not chunks:
        return pd.DataFrame()
    g = chunks[0].copy() if len(chunks) == 1 else pd.concat(chunks, ignore_index=True, join="inner")
    g["date"] = pd.to_datetime(g["date"], errors="coerce")
    g = g.dropna(subset=["date"])
    g = g.sort_values(["date", "gameid"]).drop_duplicates(subset=["gameid"], keep="last").reset_index(drop=True)
    return g


def _apply_ms(p, s, table):
    if not table:
        return float(p)
    try:
        return float(clip_prob(_apply_microseg_calibration(
            float(p), league=str(s.league),
            split=str(getattr(s, "split", "")),
            side=str(getattr(s, "side", "blue")),
            bo=str(getattr(s, "bo_bucket", "1")),
            phase=str(getattr(s, "phase", "regular")),
            table=table, min_n=30, strength=0.60, cap_pp=8.0,
            hierarchical=True, hierarchy_decay=0.80,
        )))
    except Exception:
        return float(p)


def _production_p_for_sample(s, microseg_table, platt_team, platt_fused):
    p_t_ms = _apply_ms(float(s.p_team), s, microseg_table)
    p_t_cal = float(clip_prob(platt_team.predict_proba(p_t_ms)))
    p_fused = float(clip_prob(_fuse_probs_by_precision(
        p_team=p_t_cal, p_players=float(s.p_players),
        n_team=float(s.n_team), n_players=float(s.n_players),
        team_scale=1.0, players_scale=1.0,
    )))
    p_fused_ms = _apply_ms(p_fused, s, microseg_table)
    return float(clip_prob(platt_fused.predict_proba(p_fused_ms)))


def _bootstrap_rmse_delta(y, pb, pc, n_bootstrap=500, seed=1337):
    rng = random.Random(int(seed))
    n = len(y)
    if n == 0:
        return float("nan"), float("nan"), float("nan"), 1.0
    y_arr = np.asarray(y, dtype=float)
    pb = np.asarray(pb, dtype=float)
    pc = np.asarray(pc, dtype=float)
    delta = float(np.sqrt(np.mean((y_arr - pb) ** 2))) - float(np.sqrt(np.mean((y_arr - pc) ** 2)))
    deltas = []
    for _ in range(n_bootstrap):
        idx = [rng.randrange(0, n) for _ in range(n)]
        rb = float(np.sqrt(np.mean((y_arr[idx] - pb[idx]) ** 2)))
        rc = float(np.sqrt(np.mean((y_arr[idx] - pc[idx]) ** 2)))
        deltas.append(rb - rc)
    deltas.sort()
    nd = len(deltas)
    ci_lo = deltas[max(0, int(0.025 * nd))]
    ci_hi = deltas[min(nd - 1, int(0.975 * nd))]
    if delta >= 0:
        adverse = sum(1 for d in deltas if d <= 0)
    else:
        adverse = sum(1 for d in deltas if d >= 0)
    p_value = 2.0 * adverse / nd
    return float(delta), float(ci_lo), float(ci_hi), float(min(1.0, max(0.0, p_value)))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--players-artifact", default="players_artifact.json")
    ap.add_argument("--csv-train", default="CSV_HISTORICO")
    ap.add_argument("--csv-current", default="CSV_DIARIO")
    ap.add_argument("--params", default="params_fitted.json")
    ap.add_argument("--val-cutoff", default="2026-03-31")
    ap.add_argument("--n-bootstrap", type=int, default=500)
    ap.add_argument("--output", default="FASE10_PLAYER_PROPS.json")
    ap.add_argument("--save-models-dir", default=None)
    args = ap.parse_args()

    csv_paths = _gather_csvs([args.csv_train, args.csv_current])
    print(f"\n{'='*72}")
    print("  FASE 10 - Player prop models (v1: kills)")
    print(f"{'='*72}\n")

    print("[1/4] Building production p_map_pre...")
    g = _load_games_multi(csv_paths)
    art = MLArtifact.load_json(args.artifact)
    p_art = PlayersArtifact.load_json(args.players_artifact)
    w_lineup = float((((art.meta or {}).get("players_layer") or {}).get("w_lineup") or 0.85))
    gameids_set = set(g["gameid"].astype(str).tolist())
    pr = load_match_player_rows(csv_paths, keep_playoffs=None, gameids=gameids_set)
    lineup_cache = _build_lineup_cache(pr)
    samples = _make_samples(art=art, p_art=p_art, games=g, lineup_cache=lineup_cache, w_lineup=w_lineup)
    microseg_table = (_read_json_file_safe(Path(args.params)).get("microseg_calibration") or {}).get("table") or {}
    train_y = [int(s.y) for s in samples if (str(getattr(s, "date_day", "") or "")[:4] in {"2024", "2025"})]
    train_p_team_ms = [_apply_ms(float(s.p_team), s, microseg_table) for s in samples
                       if (str(getattr(s, "date_day", "") or "")[:4] in {"2024", "2025"})]
    platt_team = fit_platt_from_raw_probs(train_y, train_p_team_ms)
    train_samples_24_25 = [s for s in samples if (str(getattr(s, "date_day", "") or "")[:4] in {"2024", "2025"})]
    train_p_fused_prod = []
    for s, p_t_ms in zip(train_samples_24_25, train_p_team_ms):
        p_t_cal = float(clip_prob(platt_team.predict_proba(p_t_ms)))
        pf = float(clip_prob(_fuse_probs_by_precision(
            p_team=p_t_cal, p_players=float(s.p_players),
            n_team=float(s.n_team), n_players=float(s.n_players),
            team_scale=1.0, players_scale=1.0,
        )))
        train_p_fused_prod.append(pf)
    train_p_fused_ms = [_apply_ms(p, s, microseg_table) for p, s in zip(train_p_fused_prod, train_samples_24_25)]
    platt_fused = fit_platt_from_raw_probs(train_y, train_p_fused_ms)

    p_pre_by_gs: Dict[tuple, float] = {}
    for s in samples:
        gid = str(getattr(s, "gameid", "") or "")
        side_norm = str(getattr(s, "side", "blue") or "blue").strip().title()
        p = _production_p_for_sample(s, microseg_table, platt_team, platt_fused)
        p_pre_by_gs[(gid, side_norm)] = float(p)

    print(f"      p_map_pre filled for {len(p_pre_by_gs)} (game,side) pairs")

    print("[2/4] Loading player rows...")
    player_rows = _load_player_rows(csv_paths)
    print(f"      Player rows: {len(player_rows)}")

    print("[3/4] Building features (causal rolling)...")
    feat_samples = build_player_kill_features(
        player_rows,
        p_map_pre_by_gameid_side=p_pre_by_gs,
        min_history=5, half_life_games=20,
    )
    print(f"      Sample rows: {len(feat_samples)}")

    # Split by date
    date_by_gid: Dict[str, pd.Timestamp] = {}
    for _, row in player_rows.iterrows():
        date_by_gid[str(row["gameid"])] = row["date"]
    train_max = pd.Timestamp("2026-01-01")
    val_max = pd.Timestamp(args.val_cutoff)
    train, val, test = [], [], []
    for s in feat_samples:
        d = date_by_gid.get(s.gameid)
        if d is None or pd.isna(d):
            continue
        if d < train_max:
            train.append(s)
        elif d <= val_max:
            val.append(s)
        else:
            test.append(s)
    print(f"      Split: train={len(train)} val={len(val)} test={len(test)}")
    if len(test) < 500 or len(train) < 2000:
        print("      [SKIP] Insufficient samples")
        return 0

    print("[4/4] Training + gate...")
    model = PlayerPropModel(market="player_kills")
    model.fit(train, val)

    y_test = np.array([s.target for s in test], dtype=float)
    # Baseline = player's rolling mean (which is feature[0])
    pred_baseline = np.array([s.features[0] for s in test], dtype=float)
    pred_candidate = model.predict_mean_batch(test)

    rmse_b = float(np.sqrt(np.mean((y_test - pred_baseline) ** 2)))
    rmse_c = float(np.sqrt(np.mean((y_test - pred_candidate) ** 2)))
    delta, ci_lo, ci_hi, pval = _bootstrap_rmse_delta(
        y_test.tolist(), pred_baseline.tolist(), pred_candidate.tolist(),
        n_bootstrap=int(args.n_bootstrap),
    )
    accept = bool(delta > 0.05 and pval < 0.05 and ci_lo > 0)

    sign = "+" if delta >= 0 else ""
    print(f"      Baseline RMSE: {rmse_b:.3f} | Candidate RMSE: {rmse_c:.3f}")
    print(f"      [{('ACCEPT' if accept else 'REJECT')}] delta_RMSE={sign}{delta:.3f} "
          f"CI[{ci_lo:+.3f}, {ci_hi:+.3f}] p={pval:.4f}")
    top_imp = sorted(model.train_metadata.get("feature_importance", {}).items(),
                     key=lambda x: x[1], reverse=True)[:5]
    print(f"      Top features: {[(k, int(v)) for k, v in top_imp]}\n")

    if accept and args.save_models_dir:
        path = Path(args.save_models_dir) / "player_kills" / "pregame"
        model.save(path)
        print(f"      [SAVED] -> {path}\n")

    out = {
        "version": "phase10_player_props_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "val_cutoff": args.val_cutoff,
        "n_train": len(train), "n_val": len(val), "n_test": len(test),
        "baseline_rmse": rmse_b, "candidate_rmse": rmse_c,
        "delta_rmse": delta, "ci_low": ci_lo, "ci_high": ci_hi,
        "p_value": pval, "accept": accept,
        "residual_sigma": float(model.residual_sigma),
        "feature_importance_top5": dict(top_imp),
    }
    Path(args.output).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  Report -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
