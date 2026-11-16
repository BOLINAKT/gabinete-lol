"""Confidence-score sweep for Marginal Trust ablation.

Tests Marginal Trust adjustment with multiple confidence_score values to determine
if there's ANY scenario where the layer helps. If it hurts at all score levels,
it confirms the layer should be disabled (or rethought).

Uncertainty layer doesn't depend on confidence_score, so it's tested once.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

from mlcore.artifact import MLArtifact
from mlcore.calibration import fit_platt_from_raw_probs
from mlcore.calibration_diagnostics import _ece, _load_games
from mlcore.fit_ml_params import _build_lineup_cache, _fuse_probs_by_precision, _make_samples
from mlcore.players_layer import PlayersArtifact, load_match_player_rows
from mlcore.utils import clip_prob, logloss

from app_core.ml_probability_adjustments_core import (
    apply_ml_marginal_trust_adjust,
    apply_ml_uncertainty_adjust,
)
from app_core.ml_league_runtime_core import (
    is_marginal_league_for_ml,
    league_is_excluded,
    ml_league_conf_band,
    ml_marginal_band_profile,
    norm_league_key,
    sanitize_ml_marginal_band_coeffs,
    tier_from_league,
)


def _safe_ll(y, p):
    if not y or not p or len(y) != len(p):
        return None
    return float(logloss(y, p))


def _safe_ece(y, p, bins=10):
    if not y or not p or len(y) != len(p):
        return None
    return float(_ece(y, p, bins=bins))


def _chronological_holdout(samples, holdout_days):
    dates = [str(getattr(s, "date_day", "") or "") for s in samples]
    valid_dates = sorted([d for d in dates if d.strip()])
    if not valid_dates:
        n = max(1, int(len(samples) * 0.25))
        return samples[:-n], samples[-n:]
    cutoff_dt = pd.Timestamp(valid_dates[-1]) - pd.Timedelta(days=int(holdout_days))
    cutoff_str = cutoff_dt.date().isoformat()
    train = [s for s, d in zip(samples, dates) if d < cutoff_str]
    hold = [s for s, d in zip(samples, dates) if d >= cutoff_str]
    if len(train) < max(50, int(len(samples) * 0.20)):
        n_hold = max(50, int(len(samples) * 0.25))
        sorted_samples = sorted(zip(dates, samples), key=lambda x: x[0])
        samples_sorted = [s for _, s in sorted_samples]
        split_idx = len(samples_sorted) - n_hold
        print("      [WARN] Using 75/25 chronological fallback")
        return samples_sorted[:split_idx], samples_sorted[split_idx:]
    return train, hold


def _build_ml_info(s):
    n_team = float(getattr(s, "n_team", 0.0) or 0.0)
    n_players = float(getattr(s, "n_players", 0.0) or 0.0)
    league = str(getattr(s, "league", "") or "")
    return {
        "blue": {"games_played": int(max(0, round(n_team / 2.0))), "league": league},
        "red":  {"games_played": int(max(0, round(n_team / 2.0))), "league": league},
        "n_players_eff": float(n_players),
    }


def _apply_mt_with_score(df, p_base, confidence_score, *, strength=0.70):
    out = []
    for i, row in df.iterrows():
        try:
            p_out, _ = apply_ml_marginal_trust_adjust(
                float(p_base[i]),
                row["ml_info"],
                clip_prob_fn=clip_prob,
                norm_league_key_fn=norm_league_key,
                tier_from_league_fn=tier_from_league,
                ml_league_conf_band_fn=ml_league_conf_band,
                ml_marginal_band_profile_fn=ml_marginal_band_profile,
                league_is_excluded_fn=league_is_excluded,
                is_marginal_league_for_ml_fn=is_marginal_league_for_ml,
                sanitize_ml_marginal_band_coeffs_fn=sanitize_ml_marginal_band_coeffs,
                league=str(row["league"]),
                enabled=True,
                strength=strength,
                prior_games=28.0,
                max_shrink=0.72,
                cap_prob=0.84,
                confidence_score=confidence_score,
            )
        except Exception:
            p_out = float(p_base[i])
        out.append(float(p_out))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--players-artifact", default="players_artifact.json")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--holdout-days", type=int, default=180)
    args = ap.parse_args()

    csv_p = Path(str(args.csv)).expanduser()
    if csv_p.is_dir():
        cands = sorted(csv_p.glob("*.csv"), key=lambda x: x.stat().st_mtime, reverse=True)
        if not cands:
            print(f"[ERROR] No .csv in {csv_p}", file=sys.stderr)
            sys.exit(1)
        csv_paths = [str(cands[0])]
    else:
        csv_paths = [str(csv_p)]

    print(f"\n{'='*72}")
    print("  CONFIDENCE SCORE SWEEP - Marginal Trust")
    print(f"{'='*72}\n")

    print("[1/2] Loading data and building samples...")
    g = _load_games(csv_paths)
    art = MLArtifact.load_json(str(args.artifact))
    p_art = PlayersArtifact.load_json(str(args.players_artifact))
    w_lineup = float((((art.meta or {}).get("players_layer") or {}).get("w_lineup") or 0.85))
    gameids = set(g["gameid"].astype(str).tolist())
    pr = load_match_player_rows(csv_paths, keep_playoffs=None, gameids=gameids)
    lineup_cache = _build_lineup_cache(pr)
    samples = _make_samples(art=art, p_art=p_art, games=g, lineup_cache=lineup_cache, w_lineup=w_lineup)

    train_samples, hold_samples = _chronological_holdout(samples, int(args.holdout_days))
    print(f"      Train: {len(train_samples)}, Holdout: {len(hold_samples)}")

    train_p, train_y = [], []
    for s in train_samples:
        pf = float(_fuse_probs_by_precision(
            p_team=float(s.p_team), p_players=float(s.p_players),
            n_team=float(s.n_team), n_players=float(s.n_players),
            team_scale=1.0, players_scale=1.0,
        ))
        if math.isfinite(pf):
            train_p.append(pf)
            train_y.append(int(s.y))

    platt = fit_platt_from_raw_probs(train_y, train_p)

    rows = []
    for s in hold_samples:
        p_fused_raw = float(clip_prob(_fuse_probs_by_precision(
            p_team=float(s.p_team), p_players=float(s.p_players),
            n_team=float(s.n_team), n_players=float(s.n_players),
            team_scale=1.0, players_scale=1.0,
        )))
        p_base = float(clip_prob(platt.predict_proba(p_fused_raw)))
        rows.append({
            "league": str(s.league),
            "y": int(s.y),
            "p_base": p_base,
            "ml_info": _build_ml_info(s),
        })

    df = pd.DataFrame(rows)
    y = df["y"].tolist()
    p_base = df["p_base"].tolist()
    base_ll = _safe_ll(y, p_base)
    base_ece = _safe_ece(y, p_base)
    print(f"      Baseline: logloss={base_ll:.5f} ECE={base_ece:.4f}\n")

    print("[2/2] Sweeping confidence_score values for Marginal Trust:\n")
    print(f"  {'confidence_score':>17} {'Strength=0.10':>14} {'Strength=0.35':>14} {'Strength=0.70':>14}")
    print(f"  {'-'*65}")

    scores_to_test = [None, 25.0, 40.0, 55.0, 72.0, 85.0, 95.0]
    strengths = [0.10, 0.35, 0.70]

    results = []
    for cs in scores_to_test:
        row_str = []
        for st in strengths:
            p_out = _apply_mt_with_score(df, p_base, cs, strength=st)
            ll = _safe_ll(y, p_out)
            d_pp = (base_ll - ll) * 100 if ll is not None else 0
            sign = "+" if d_pp >= 0 else ""
            row_str.append(f"{sign}{d_pp:>6.3f}pp")
            results.append({"confidence_score": cs, "strength": st, "logloss": ll, "delta_pp": d_pp})
        cs_label = "None (default=50)" if cs is None else f"{cs:.0f}"
        print(f"  {cs_label:>17} {row_str[0]:>14} {row_str[1]:>14} {row_str[2]:>14}")

    # Find best result
    best = max(results, key=lambda r: r["delta_pp"])
    print(f"\n  MELHOR CONFIG TESTADA: cs={best['confidence_score']}, strength={best['strength']}")
    print(f"  Logloss: {best['logloss']:.5f}  vs baseline: {'+' if best['delta_pp']>=0 else ''}{best['delta_pp']:.3f}pp")

    # Check if any config beats baseline
    helpful = [r for r in results if r["delta_pp"] > 0]
    print(f"\n  {len(helpful)}/{len(results)} configuracoes melhoraram o baseline")

    if not helpful:
        print("\n  VEREDITO: Marginal Trust NAO AJUDA em NENHUMA configuracao testada.")
        print("  RECOMENDACAO: Desabilitar ml_marginal_trust_enabled.")
    else:
        print("\n  Configuracoes que ajudaram:")
        for r in helpful[:5]:
            print(f"    cs={r['confidence_score']}, strength={r['strength']} -> +{r['delta_pp']:.3f}pp")

    # Also sweep Uncertainty briefly
    print(f"\n{'='*72}")
    print("  SWEEP FINAL - Uncertainty (independente de confidence_score)")
    print(f"{'='*72}\n")
    print(f"  {'strength':>10} {'prior_games':>12} {'Logloss':>9} {'Melhora':>10}")
    print(f"  {'-'*50}")

    unc_configs = [
        (0.00, 22.0), (0.05, 22.0), (0.10, 22.0), (0.20, 22.0),
        (0.10, 50.0), (0.10, 5.0), (0.30, 5.0),
    ]
    unc_results = []
    for st, pg in unc_configs:
        p_out = []
        for i, row in df.iterrows():
            po, _ = apply_ml_uncertainty_adjust(
                float(p_base[i]), row["ml_info"],
                clip_prob_fn=clip_prob,
                enabled=True, strength=st, prior_games=pg, max_shrink=0.65,
            )
            p_out.append(float(po))
        ll = _safe_ll(y, p_out)
        d = (base_ll - ll) * 100 if ll is not None else 0
        sign = "+" if d >= 0 else ""
        unc_results.append({"strength": st, "prior_games": pg, "logloss": ll, "delta_pp": d})
        marker = "  <-- DISABLED" if st == 0.0 else ""
        print(f"  {st:>10.2f} {pg:>12.1f} {ll:>9.5f} {sign}{d:>8.3f}pp{marker}")

    helpful_unc = [r for r in unc_results if r["delta_pp"] > 0]
    print(f"\n  {len(helpful_unc)}/{len(unc_results)} configuracoes melhoraram o baseline")
    if not helpful_unc:
        print("  VEREDITO: Uncertainty NAO AJUDA em NENHUMA configuracao testada.")
        print("  RECOMENDACAO: Desabilitar ml_uncertainty_enabled (manter strength=0 ou flag off).")

    print(f"\n{'='*72}\n")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "holdout_n": len(hold_samples),
        "baseline": {"logloss": base_ll, "ece": base_ece},
        "marginal_trust_sweep": results,
        "uncertainty_sweep": unc_results,
    }
    Path("ablation_confidence_sweep.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("[INFO] Report saved to ablation_confidence_sweep.json")


if __name__ == "__main__":
    main()
