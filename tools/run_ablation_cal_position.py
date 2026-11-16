"""Test calibration POSITION: before fusion (current pipeline) vs after fusion.

Current pipeline:
    p_team_raw -> Platt_artifact -> Microseg -> Platt_post_cal -> Fuse(players) -> p_map

Hypothesis (from ablation):
    p_team_raw -> Platt_artifact -> Fuse(players) -> Microseg -> Platt -> p_map  (better?)

This script measures both empirically on the holdout.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

from mlcore.artifact import MLArtifact
from mlcore.calibration import fit_platt_from_raw_probs
from mlcore.calibration_diagnostics import _apply_microseg_calibration, _ece, _load_games, _read_json_file_safe
from mlcore.fit_ml_params import _build_lineup_cache, _fuse_probs_by_precision, _make_samples
from mlcore.players_layer import PlayersArtifact, load_match_player_rows
from mlcore.utils import clip_prob, logloss


def _ll(y, p):
    return float(logloss(y, p)) if y and p else None


def _ece_safe(y, p, bins=10):
    return float(_ece(y, p, bins=bins)) if y and p else None


def _holdout(samples, days):
    dates = [str(getattr(s, "date_day", "") or "") for s in samples]
    valid = sorted([d for d in dates if d.strip()])
    if not valid:
        n = max(1, int(len(samples) * 0.25))
        return samples[:-n], samples[-n:]
    cutoff = (pd.Timestamp(valid[-1]) - pd.Timedelta(days=days)).date().isoformat()
    train = [s for s, d in zip(samples, dates) if d < cutoff]
    hold = [s for s, d in zip(samples, dates) if d >= cutoff]
    if len(train) < max(50, int(len(samples) * 0.20)):
        n_hold = max(50, int(len(samples) * 0.25))
        sorted_s = [s for _, s in sorted(zip(dates, samples), key=lambda x: x[0])]
        split = len(sorted_s) - n_hold
        return sorted_s[:split], sorted_s[split:]
    return train, hold


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--players-artifact", default="players_artifact.json")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--params", default="params_fitted.json")
    ap.add_argument("--holdout-days", type=int, default=180)
    args = ap.parse_args()

    csv_p = Path(args.csv)
    if csv_p.is_dir():
        cands = sorted(csv_p.glob("*.csv"), key=lambda x: x.stat().st_mtime, reverse=True)
        csv_paths = [str(cands[0])]
    else:
        csv_paths = [str(csv_p)]

    print(f"\n{'='*72}")
    print("  CAL POSITION TEST: Before-Fusion vs After-Fusion")
    print(f"{'='*72}\n")

    print("[1/3] Loading data...")
    g = _load_games(csv_paths)
    art = MLArtifact.load_json(args.artifact)
    p_art = PlayersArtifact.load_json(args.players_artifact)
    w_lineup = float((((art.meta or {}).get("players_layer") or {}).get("w_lineup") or 0.85))
    gameids = set(g["gameid"].astype(str).tolist())
    pr = load_match_player_rows(csv_paths, keep_playoffs=None, gameids=gameids)
    lineup_cache = _build_lineup_cache(pr)
    samples = _make_samples(art=art, p_art=p_art, games=g, lineup_cache=lineup_cache, w_lineup=w_lineup)

    train_samples, hold_samples = _holdout(samples, args.holdout_days)
    print(f"      Train: {len(train_samples)}, Holdout: {len(hold_samples)}")

    # Load microseg table
    prm = _read_json_file_safe(Path(args.params))
    ms_pack = prm.get("microseg_calibration") or {}
    ms_table = ms_pack.get("table") or {}
    print(f"      Microseg table: {len(ms_table)} segments\n")

    def _apply_ms(p, s):
        try:
            return float(clip_prob(_apply_microseg_calibration(
                p, league=str(s.league), split=str(getattr(s, "split", "")),
                side=str(getattr(s, "side", "blue")), bo=str(getattr(s, "bo_bucket", "1")),
                phase=str(getattr(s, "phase", "regular")),
                table=ms_table, min_n=30, strength=0.60, cap_pp=8.0,
                hierarchical=True, hierarchy_decay=0.80,
            )))
        except Exception:
            return p

    print("[2/3] Building variants...\n")

    # ----- VARIANT A: Current pipeline (cal BEFORE fusion) -----
    # 1. p_team (already has Platt from artifact)
    # 2. Microseg on p_team
    # 3. Platt fit on training p_team_microseg'd, then applied
    # 4. Fuse(p_team_cal, p_players)

    train_p_team = [float(s.p_team) for s in train_samples]
    train_y = [int(s.y) for s in train_samples]

    # Microseg p_team for training
    train_p_team_ms = [_apply_ms(p, s) for p, s in zip(train_p_team, train_samples)]
    # Fit Platt on microseg'd p_team
    platt_team_postms = fit_platt_from_raw_probs(train_y, train_p_team_ms)

    # Build A on holdout
    p_A = []
    for s in hold_samples:
        p_t = float(clip_prob(s.p_team))
        p_t_ms = _apply_ms(p_t, s)
        p_t_cal = float(clip_prob(platt_team_postms.predict_proba(p_t_ms)))
        # Fuse with players
        p_fused = float(clip_prob(_fuse_probs_by_precision(
            p_team=p_t_cal, p_players=float(s.p_players),
            n_team=float(s.n_team), n_players=float(s.n_players),
            team_scale=1.0, players_scale=1.0,
        )))
        p_A.append(p_fused)

    # ----- VARIANT B: Alternative (cal AFTER fusion) -----
    # 1. Fuse(p_team, p_players)
    # 2. Microseg on p_fused
    # 3. Platt fit on training fused_microseg'd, then applied

    def _pfused(s):
        return float(clip_prob(_fuse_probs_by_precision(
            p_team=float(s.p_team), p_players=float(s.p_players),
            n_team=float(s.n_team), n_players=float(s.n_players),
            team_scale=1.0, players_scale=1.0,
        )))

    train_p_fused = [_pfused(s) for s in train_samples]
    train_p_fused_ms = [_apply_ms(p, s) for p, s in zip(train_p_fused, train_samples)]
    platt_fused_postms = fit_platt_from_raw_probs(train_y, train_p_fused_ms)

    p_B = []
    for s in hold_samples:
        p_f = _pfused(s)
        p_f_ms = _apply_ms(p_f, s)
        p_f_cal = float(clip_prob(platt_fused_postms.predict_proba(p_f_ms)))
        p_B.append(p_f_cal)

    # ----- VARIANT C: Hybrid - cal in BOTH places -----
    p_C = []
    for s in hold_samples:
        p_t = float(clip_prob(s.p_team))
        p_t_ms = _apply_ms(p_t, s)
        p_t_cal = float(clip_prob(platt_team_postms.predict_proba(p_t_ms)))
        p_fused = float(clip_prob(_fuse_probs_by_precision(
            p_team=p_t_cal, p_players=float(s.p_players),
            n_team=float(s.n_team), n_players=float(s.n_players),
            team_scale=1.0, players_scale=1.0,
        )))
        p_fused_ms = _apply_ms(p_fused, s)
        p_fused_cal = float(clip_prob(platt_fused_postms.predict_proba(p_fused_ms)))
        p_C.append(p_fused_cal)

    # ----- VARIANT D: Naive (no cal in either place, just fuse) -----
    p_D = [_pfused(s) for s in hold_samples]

    # ----- Print results -----
    y = [int(s.y) for s in hold_samples]

    print(f"[3/3] Results on {len(hold_samples)} holdout samples:\n")
    print(f"  {'Variant':<55} {'Logloss':>9} {'ECE':>7}")
    print(f"  {'-'*72}")

    variants = [
        ("A  Cal BEFORE fusion (Microseg+Platt on p_team) [CURRENT]", p_A),
        ("B  Cal AFTER fusion (Microseg+Platt on p_fused)", p_B),
        ("C  Cal BOTH (before AND after fusion)", p_C),
        ("D  No cal (only fuse)  [naive baseline]", p_D),
    ]
    for name, p in variants:
        ll = _ll(y, p)
        ece = _ece_safe(y, p)
        print(f"  {name:<55} {ll:>9.5f} {ece:>7.4f}")

    best = min(variants, key=lambda v: _ll(y, v[1]))
    best_ll = _ll(y, best[1])
    print(f"\n  MELHOR LOGLOSS: {best[0]}")
    print(f"  Logloss: {best_ll:.5f}")

    # Compare A vs B vs C
    ll_a = _ll(y, p_A)
    ll_b = _ll(y, p_B)
    ll_c = _ll(y, p_C)
    print(f"\n  A vs B: {'+' if (ll_a - ll_b) >= 0 else ''}{(ll_a - ll_b)*100:.3f}pp (positivo = B melhor)")
    print(f"  A vs C: {'+' if (ll_a - ll_c) >= 0 else ''}{(ll_a - ll_c)*100:.3f}pp (positivo = C melhor)")
    print(f"  B vs C: {'+' if (ll_b - ll_c) >= 0 else ''}{(ll_b - ll_c)*100:.3f}pp (positivo = C melhor)")

    print(f"\n{'='*72}\n")


if __name__ == "__main__":
    main()
