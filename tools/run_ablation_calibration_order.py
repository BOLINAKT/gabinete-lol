"""Test order of calibration layers: Platt-before-Microseg vs Microseg-before-Platt.

The training pipeline currently applies microseg + OOF Platt. The order matters because:
- Microseg adds per-segment bias correction (additive in probability space)
- Platt is a sigmoid recalibration (multiplicative in logit space)

This script tests:
- Just Platt
- Just Microseg
- Microseg then Platt (current order in calibration_diagnostics)
- Platt then Microseg (alternative)

To find the configuration that maximizes both logloss and ECE simultaneously.
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


def _safe_ece(y, p, bins=10):
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
    print("  CALIBRATION ORDER TEST: Microseg vs Platt vs Both")
    print(f"{'='*72}\n")

    print("Loading data...")
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

    # Compute p_fused_raw for all
    def _pfused(s):
        return float(clip_prob(_fuse_probs_by_precision(
            p_team=float(s.p_team), p_players=float(s.p_players),
            n_team=float(s.n_team), n_players=float(s.n_players),
            team_scale=1.0, players_scale=1.0,
        )))

    train_p = [_pfused(s) for s in train_samples]
    train_y = [int(s.y) for s in train_samples]

    # Fit Platt on train fused
    platt = fit_platt_from_raw_probs(train_y, train_p)

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

    # Compute all variants
    y = [int(s.y) for s in hold_samples]
    p_raw = [_pfused(s) for s in hold_samples]
    p_platt = [float(clip_prob(platt.predict_proba(p))) for p in p_raw]
    p_ms = [_apply_ms(p, s) for p, s in zip(p_raw, hold_samples)]
    p_ms_then_platt = [float(clip_prob(platt.predict_proba(p))) for p in p_ms]
    p_platt_then_ms = [_apply_ms(p, s) for p, s in zip(p_platt, hold_samples)]

    # Re-fit Platt on training MICROSEG'd data for "Platt(microseg)" variant
    train_p_ms = [_apply_ms(p, s) for p, s in zip(train_p, train_samples)]
    platt_after_ms = fit_platt_from_raw_probs(train_y, train_p_ms)
    p_ms_then_platt_v2 = [float(clip_prob(platt_after_ms.predict_proba(p))) for p in p_ms]

    print(f"  {'Pipeline':<40} {'Logloss':>9} {'Melhora':>10} {'ECE':>7}")
    print(f"  {'-'*72}")

    variants = [
        ("L0  p_fused_raw (sem cal)", p_raw),
        ("L1  + Platt (sozinho)", p_platt),
        ("L2  + Microseg (sozinho)", p_ms),
        ("L3  Microseg -> Platt (mesmo Platt)", p_ms_then_platt),
        ("L4  Platt -> Microseg", p_platt_then_ms),
        ("L5  Microseg -> Platt (Platt re-fit)", p_ms_then_platt_v2),
    ]

    base_ll = _ll(y, p_raw)
    for name, p in variants:
        ll = _ll(y, p)
        ece = _safe_ece(y, p)
        d = (base_ll - ll) * 100 if ll is not None else 0
        sign = "+" if d >= 0 else ""
        print(f"  {name:<40} {ll:>9.5f} {sign}{d:>8.3f}pp {ece:>7.4f}")

    # Best result
    best_idx = max(range(len(variants)), key=lambda i: -1 * (_ll(y, variants[i][1]) or 1))
    print(f"\n  MELHOR: {variants[best_idx][0]}")
    print(f"  Logloss: {_ll(y, variants[best_idx][1]):.5f}  ECE: {_safe_ece(y, variants[best_idx][1]):.4f}")
    print(f"\n{'='*72}\n")


if __name__ == "__main__":
    main()
