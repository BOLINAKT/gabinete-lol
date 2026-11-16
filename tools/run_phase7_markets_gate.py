"""Phase 7: Train and validate live market models through the acceptance gate.

For each (market × snapshot minute) pair, trains a LightGBM regressor that
predicts the final game total (kills, towers, dragons, barons, gamelength_min)
from the game state at minute t. The gate compares it against a fixed-line
baseline (predict the global mean total).

Saves models to `live_models/markets/{market}/minute_{T}/` and updates the
manifest with their freshness signature.

Usage
-----
    python tools/run_phase7_markets_gate.py --val-cutoff 2026-03-31 \\
        --save-models-dir live_models/markets --output FASE7_MARKETS.json
"""
from __future__ import annotations

import argparse
import json
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
    LiveMarketModel, SUPPORTED_MARKETS,
    SNAPSHOT_MINUTES, build_market_features,
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


def _load_team_rows(csv_paths: List[str]) -> pd.DataFrame:
    chunks = []
    for p in csv_paths:
        df = pd.read_csv(p, low_memory=False)
        df = df[df["participantid"].isin([100, 200])].copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date", "gameid"])
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


def _bootstrap_rmse_delta(y_true, pred_baseline, pred_candidate, n_bootstrap=500, seed=1337):
    """Paired bootstrap for delta_RMSE (positive = candidate is better)."""
    import random
    rng = random.Random(int(seed))
    n = len(y_true)
    if n == 0 or len(pred_baseline) != n or len(pred_candidate) != n:
        return float("nan"), float("nan"), float("nan"), 1.0
    y_arr = np.asarray(y_true, dtype=float)
    pb = np.asarray(pred_baseline, dtype=float)
    pc = np.asarray(pred_candidate, dtype=float)
    rmse_b = float(np.sqrt(np.mean((y_arr - pb) ** 2)))
    rmse_c = float(np.sqrt(np.mean((y_arr - pc) ** 2)))
    delta = rmse_b - rmse_c
    deltas = []
    for _ in range(int(n_bootstrap)):
        idx = [rng.randrange(0, n) for _ in range(n)]
        y_r = y_arr[idx]; pb_r = pb[idx]; pc_r = pc[idx]
        rb = float(np.sqrt(np.mean((y_r - pb_r) ** 2)))
        rc = float(np.sqrt(np.mean((y_r - pc_r) ** 2)))
        deltas.append(rb - rc)
    deltas.sort()
    n_d = len(deltas)
    ci_lo = deltas[max(0, int(0.025 * n_d))]
    ci_hi = deltas[min(n_d - 1, int(0.975 * n_d))]
    if delta >= 0:
        adverse = sum(1 for d in deltas if d <= 0)
    else:
        adverse = sum(1 for d in deltas if d >= 0)
    p_value = 2.0 * float(adverse) / float(n_d)
    p_value = float(min(1.0, max(0.0, p_value)))
    return float(delta), float(ci_lo), float(ci_hi), float(p_value)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--players-artifact", default="players_artifact.json")
    ap.add_argument("--csv-train", default="CSV_HISTORICO")
    ap.add_argument("--csv-current", default="CSV_DIARIO")
    ap.add_argument("--params", default="params_fitted.json")
    ap.add_argument("--val-cutoff", default="2026-03-31")
    ap.add_argument("--n-bootstrap", type=int, default=500)
    ap.add_argument("--output", default="FASE7_MARKETS.json")
    ap.add_argument("--save-models-dir", default=None,
                    help="If set, save trained models under this directory")
    args = ap.parse_args()

    csv_paths = _gather_csvs([args.csv_train, args.csv_current])
    val_year = 2026

    print(f"\n{'='*72}")
    print("  FASE 7 GATE - Live MARKET regression models")
    print(f"{'='*72}\n")

    # ---- Load game samples + build production p_map_pre ----
    print("[1/4] Building production p_map_pre for all games...")
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
    train_p_fused_prod = []
    train_samples_24_25 = [s for s in samples if (str(getattr(s, "date_day", "") or "")[:4] in {"2024", "2025"})]
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

    p_map_pre_by_gid: Dict[str, float] = {}
    for s in samples:
        gid = str(getattr(s, "gameid", "") or "")
        side_norm = str(getattr(s, "side", "blue") or "blue").strip().title()
        p = _production_p_for_sample(s, microseg_table, platt_team, platt_fused)
        if side_norm == "Blue":
            p_map_pre_by_gid[gid] = float(p)
        elif side_norm == "Red":
            p_map_pre_by_gid[gid] = float(1.0 - p)

    print(f"      p_map_pre filled for {len(p_map_pre_by_gid)} games")

    # ---- Load team rows for snapshot extraction ----
    print("[2/4] Loading team rows for snapshot extraction...")
    team_rows = _load_team_rows(csv_paths)
    print(f"      Team rows: {len(team_rows)}")
    train_max = pd.Timestamp(f"{val_year}-01-01")
    val_max = pd.Timestamp(args.val_cutoff)

    # ---- For each (market, minute), train + gate ----
    print("[3/4] Training market models...\n")
    all_results = []

    for market in SUPPORTED_MARKETS:
        for minute in SNAPSHOT_MINUTES:
            print(f"  === {market} @ {minute}min ===")
            samples_all = build_market_features(
                team_rows, minute=int(minute), market=str(market),
                p_map_pre_by_gameid_blue=p_map_pre_by_gid,
                require_complete=True,
            )
            # Split by date
            date_by_gid = team_rows.set_index("gameid")["date"].to_dict()
            train_samples, val_samples, test_samples = [], [], []
            for s in samples_all:
                d = date_by_gid.get(s.gameid)
                if d is None or pd.isna(d):
                    continue
                if d < train_max:
                    train_samples.append(s)
                elif d <= val_max:
                    val_samples.append(s)
                else:
                    test_samples.append(s)
            print(f"      Samples: train={len(train_samples)}, val={len(val_samples)}, test={len(test_samples)}")

            if len(test_samples) < 50 or len(train_samples) < 200:
                print("      [SKIP] Insufficient samples")
                all_results.append({
                    "market": market, "minute": int(minute),
                    "skipped": True,
                    "n_train": len(train_samples), "n_val": len(val_samples), "n_test": len(test_samples),
                })
                continue

            # Train
            model = LiveMarketModel(market=str(market), minute=int(minute))
            model.fit(train_samples, val_samples)

            # Save if requested
            if args.save_models_dir:
                save_path = Path(args.save_models_dir) / market / f"minute_{minute:02d}"
                model.save(save_path)
                print(f"      [SAVED] -> {save_path}")

            # Evaluate baseline (predict TRAIN mean) vs candidate (model)
            train_targets = np.array([s.target for s in train_samples], dtype=float)
            baseline_mean = float(np.mean(train_targets))
            y_test = np.array([s.target for s in test_samples], dtype=float)
            pred_baseline = np.full(len(y_test), baseline_mean)
            pred_candidate = model.predict_mean_batch(test_samples)

            # Compute RMSE delta + paired bootstrap
            rmse_b = float(np.sqrt(np.mean((y_test - pred_baseline) ** 2)))
            rmse_c = float(np.sqrt(np.mean((y_test - pred_candidate) ** 2)))
            delta, ci_lo, ci_hi, pval = _bootstrap_rmse_delta(
                y_test.tolist(), pred_baseline.tolist(), pred_candidate.tolist(),
                n_bootstrap=int(args.n_bootstrap),
            )
            # ACCEPT if delta is clearly positive and significant
            accept = bool(delta > 0.05 and pval < 0.05 and ci_lo > 0)
            print(f"      Baseline RMSE: {rmse_b:.3f} | Candidate RMSE: {rmse_c:.3f}")
            sign = "+" if delta >= 0 else ""
            print(f"      [{('ACCEPT' if accept else 'REJECT')}] delta_RMSE={sign}{delta:.3f} CI[{ci_lo:+.3f}, {ci_hi:+.3f}] p={pval:.4f}")
            top_imp = sorted(model.train_metadata.get("feature_importance", {}).items(),
                             key=lambda x: x[1], reverse=True)[:3]
            print(f"      Top features: {[(k, int(v)) for k, v in top_imp]}\n")

            all_results.append({
                "market": market, "minute": int(minute),
                "n_train": len(train_samples), "n_val": len(val_samples), "n_test": len(test_samples),
                "baseline_rmse": rmse_b, "candidate_rmse": rmse_c,
                "delta_rmse": delta, "ci_low": ci_lo, "ci_high": ci_hi, "p_value": pval,
                "accept": accept,
                "residual_sigma": float(model.residual_sigma),
                "feature_importance_top3": dict(top_imp),
            })

    # ---- Summary ----
    print("[4/4] Summary")
    print(f"  {'Market':<18} {'Minute':>6} {'n_test':>7} {'delta_RMSE':>11} {'p-value':>9} {'Gate':>8}")
    print(f"  {'-'*68}")
    for r in all_results:
        if r.get("skipped"):
            print(f"  {r['market']:<18} {r['minute']:>6} {r['n_test']:>7} {'SKIPPED':>11} {'-':>9} {'-':>8}")
            continue
        gate = "ACCEPT" if r["accept"] else "REJECT"
        sign = "+" if r['delta_rmse'] >= 0 else ""
        print(f"  {r['market']:<18} {r['minute']:>6} {r['n_test']:>7} {sign}{r['delta_rmse']:>9.3f} {r['p_value']:>9.4f} {gate:>8}")

    print(f"\n{'='*72}\n")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": "phase7_markets_v1",
        "markets": all_results,
    }
    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[INFO] Report saved to {args.output}")


if __name__ == "__main__":
    main()
