"""Isolated ablation + parameter sweep for live ML pipeline layers.

Differences from run_ablation_live_layers.py:
- Each layer is applied DIRECTLY on the baseline (not cumulative), so we measure
  the true marginal effect of each layer in isolation.
- Adds parameter sweep for Uncertainty and Marginal Trust to find best settings.
- Adds calibration diagnostics: split impact by sample size bucket.

Usage
-----
    python tools/run_ablation_isolated_layers.py \\
        --artifact ml_artifact.json \\
        --players-artifact players_artifact.json \\
        --csv CSV_DIARIO \\
        [--params params_fitted.json] \\
        [--holdout-days 180] \\
        [--output ablation_isolated_report.json]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

from mlcore.artifact import MLArtifact
from mlcore.calibration import fit_platt_from_raw_probs
from mlcore.calibration_diagnostics import _apply_microseg_calibration, _ece, _load_games, _read_json_file_safe
from mlcore.fit_ml_params import _build_lineup_cache, _fuse_probs_by_precision, _make_samples
from mlcore.players_layer import PlayersArtifact, load_match_player_rows
from mlcore.utils import brier, clip_prob, logloss

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


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _safe_ll(y, p):
    if not y or not p or len(y) != len(p):
        return None
    return float(logloss(y, p))


def _safe_ece(y, p, bins=10):
    if not y or not p or len(y) != len(p):
        return None
    return float(_ece(y, p, bins=bins))


def _safe_brier(y, p):
    if not y or not p or len(y) != len(p):
        return None
    return float(brier(y, p))


def _change_stats(p_before, p_after):
    if not p_before or len(p_before) != len(p_after):
        return 0.0, 0.0
    diffs = [abs(float(b) - float(a)) for b, a in zip(p_before, p_after)]
    pct = 100.0 * sum(1 for d in diffs if d > 1e-6) / len(diffs)
    mean = (sum(diffs) / len(diffs)) * 100.0
    return pct, mean


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


# ---------------------------------------------------------------------------
# Layer appliers
# ---------------------------------------------------------------------------

def _apply_uncertainty(df: pd.DataFrame, p_base: List[float], *, strength: float, prior_games: float, max_shrink: float) -> List[float]:
    out = []
    for i, row in df.iterrows():
        p_out, _ = apply_ml_uncertainty_adjust(
            float(p_base[i]),
            row["ml_info"],
            clip_prob_fn=clip_prob,
            enabled=True,
            strength=strength,
            prior_games=prior_games,
            max_shrink=max_shrink,
        )
        out.append(float(p_out))
    return out


def _apply_marginal_trust(df: pd.DataFrame, p_base: List[float], *, strength: float, prior_games: float, max_shrink: float, confidence_score: float = 72.0) -> List[float]:
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
                prior_games=prior_games,
                max_shrink=max_shrink,
                cap_prob=0.84,
                confidence_score=confidence_score,
            )
        except Exception:
            p_out = float(p_base[i])
        out.append(float(p_out))
    return out


def _apply_microseg(df: pd.DataFrame, p_base: List[float], table: Dict[str, Dict[str, float]], *, strength: float = 0.60) -> List[float]:
    if not table:
        return list(p_base)
    out = []
    for i, row in df.iterrows():
        try:
            p_out = float(clip_prob(_apply_microseg_calibration(
                float(p_base[i]),
                league=str(row["league"]),
                split=str(row["split"]),
                side=str(row["side"]),
                bo=str(row["bo"]),
                phase=str(row["phase"]),
                table=table,
                min_n=30,
                strength=strength,
                cap_pp=8.0,
                hierarchical=True,
                hierarchy_decay=0.80,
            )))
        except Exception:
            p_out = float(p_base[i])
        out.append(p_out)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_isolated_ablation(*, artifact_path: str, players_artifact_path: str, csv_paths: List[str],
                          params_fitted_path: Optional[str] = None, holdout_days: int = 180,
                          team_scale: float = 1.0, players_scale: float = 1.0) -> Dict[str, Any]:
    print(f"\n{'='*72}")
    print("  ABLATION ISOLADO + SWEEP DE PARAMETROS")
    print(f"{'='*72}")

    print("\n[1/3] Carregando dados...")
    g = _load_games(csv_paths)
    if g.empty:
        return {"error": "no_games"}

    art = MLArtifact.load_json(str(artifact_path))
    p_art = PlayersArtifact.load_json(str(players_artifact_path))
    w_lineup = float((((art.meta or {}).get("players_layer") or {}).get("w_lineup") or 0.85))
    gameids = set(g["gameid"].astype(str).tolist())
    pr = load_match_player_rows(csv_paths, keep_playoffs=None, gameids=gameids)
    lineup_cache = _build_lineup_cache(pr)
    samples = _make_samples(art=art, p_art=p_art, games=g, lineup_cache=lineup_cache, w_lineup=w_lineup)
    if not samples:
        return {"error": "no_samples"}

    train_samples, hold_samples = _chronological_holdout(samples, holdout_days)
    print(f"      Train: {len(train_samples)}, Holdout: {len(hold_samples)}")

    # Build base probabilities
    train_p, train_y = [], []
    for s in train_samples:
        pf = float(_fuse_probs_by_precision(
            p_team=float(s.p_team), p_players=float(s.p_players),
            n_team=float(s.n_team), n_players=float(s.n_players),
            team_scale=team_scale, players_scale=players_scale,
        ))
        if math.isfinite(pf):
            train_p.append(pf)
            train_y.append(int(s.y))

    platt_fused = None
    if len(train_p) >= 100:
        try:
            platt_fused = fit_platt_from_raw_probs(train_y, train_p)
        except Exception:
            pass

    microseg_table: Dict[str, Dict[str, float]] = {}
    if params_fitted_path:
        prm = _read_json_file_safe(Path(str(params_fitted_path)).expanduser())
        ms_pack = prm.get("microseg_calibration") if isinstance(prm.get("microseg_calibration"), dict) else {}
        ms_tbl = ms_pack.get("table") if isinstance(ms_pack.get("table"), dict) else {}
        if isinstance(ms_tbl, dict):
            microseg_table = ms_tbl

    rows = []
    for s in hold_samples:
        p_fused_raw = float(clip_prob(_fuse_probs_by_precision(
            p_team=float(s.p_team), p_players=float(s.p_players),
            n_team=float(s.n_team), n_players=float(s.n_players),
            team_scale=team_scale, players_scale=players_scale,
        )))
        p_base = float(clip_prob(platt_fused.predict_proba(p_fused_raw))) if platt_fused else p_fused_raw
        rows.append({
            "league": str(s.league),
            "bo": str(getattr(s, "bo_bucket", "1") or "1"),
            "phase": str(getattr(s, "phase", "regular") or "regular"),
            "side": str(getattr(s, "side", "blue") or "blue"),
            "split": str(getattr(s, "split", "") or ""),
            "y": int(s.y),
            "n_team": float(getattr(s, "n_team", 0.0) or 0.0),
            "n_players": float(getattr(s, "n_players", 0.0) or 0.0),
            "p_base": p_base,
            "ml_info": _build_ml_info(s),
        })

    df = pd.DataFrame(rows)
    y = df["y"].tolist()
    p_base = df["p_base"].tolist()

    base_ll = _safe_ll(y, p_base)
    base_ece = _safe_ece(y, p_base)
    print(f"      Baseline: logloss={base_ll:.5f} ECE={base_ece:.4f}")

    # =======================================================================
    # PART 1: ISOLATED LAYER TEST (each layer vs baseline directly)
    # =======================================================================
    print("\n[2/3] ABLATION ISOLADO (cada camada vs baseline)")
    print(f"{'='*72}")
    print(f"  {'Camada (config padrao)':<35} {'Logloss':>9} {'Melhora':>10} {'ECE':>7}")
    print(f"  {'-'*72}")
    print(f"  {'L0 Baseline':<35} {base_ll:>9.5f} {'-':>10} {base_ece:>7.4f}")

    isolated_results = []

    # Uncertainty isolada
    p_unc = _apply_uncertainty(df, p_base, strength=0.55, prior_games=22.0, max_shrink=0.65)
    ll = _safe_ll(y, p_unc); ece = _safe_ece(y, p_unc)
    d = (base_ll - ll) * 100 if ll is not None else 0
    isolated_results.append({"name": "Uncertainty (default)", "logloss": ll, "ece": ece, "delta_pp": d})
    print(f"  {'Uncertainty (default)':<35} {ll:>9.5f} {'+' if d>=0 else ''}{d:>8.3f}pp {ece:>7.4f}")

    # Marginal Trust isolada
    p_mt = _apply_marginal_trust(df, p_base, strength=0.70, prior_games=28.0, max_shrink=0.72)
    ll = _safe_ll(y, p_mt); ece = _safe_ece(y, p_mt)
    d = (base_ll - ll) * 100 if ll is not None else 0
    isolated_results.append({"name": "Marginal Trust (default)", "logloss": ll, "ece": ece, "delta_pp": d})
    print(f"  {'Marginal Trust (default)':<35} {ll:>9.5f} {'+' if d>=0 else ''}{d:>8.3f}pp {ece:>7.4f}")

    # Microseg isolada
    p_ms = _apply_microseg(df, p_base, microseg_table, strength=0.60)
    ll = _safe_ll(y, p_ms); ece = _safe_ece(y, p_ms)
    d = (base_ll - ll) * 100 if ll is not None else 0
    isolated_results.append({"name": "Microseg (default)", "logloss": ll, "ece": ece, "delta_pp": d})
    print(f"  {'Microseg (default)':<35} {ll:>9.5f} {'+' if d>=0 else ''}{d:>8.3f}pp {ece:>7.4f}")

    # =======================================================================
    # PART 2: PARAMETER SWEEP - Uncertainty
    # =======================================================================
    print("\n[3/3] SWEEP DE PARAMETROS - Uncertainty")
    print(f"{'='*72}")
    print(f"  {'strength':>10} {'prior_games':>12} {'max_shrink':>11} {'Logloss':>9} {'Melhora':>10}")
    print(f"  {'-'*60}")

    sweep_unc = []
    configs_unc = [
        (0.10, 22.0, 0.65), (0.20, 22.0, 0.65), (0.30, 22.0, 0.65),
        (0.55, 22.0, 0.65),  # default
        (0.55, 50.0, 0.65), (0.55, 100.0, 0.65),
        (0.55, 22.0, 0.30), (0.55, 22.0, 0.10),
        (0.00, 22.0, 0.65),  # disabled
    ]
    for strength, pg, ms in configs_unc:
        p_test = _apply_uncertainty(df, p_base, strength=strength, prior_games=pg, max_shrink=ms)
        ll = _safe_ll(y, p_test)
        d = (base_ll - ll) * 100 if ll is not None else 0
        marker = "  <-- default" if (strength, pg, ms) == (0.55, 22.0, 0.65) else ""
        sweep_unc.append({"strength": strength, "prior_games": pg, "max_shrink": ms,
                          "logloss": ll, "delta_pp": d})
        sign = "+" if d >= 0 else ""
        print(f"  {strength:>10.2f} {pg:>12.1f} {ms:>11.2f} {ll:>9.5f} {sign}{d:>8.3f}pp{marker}")

    best_unc = max(sweep_unc, key=lambda r: r["delta_pp"])
    print(f"\n  MELHOR CONFIG: strength={best_unc['strength']}, prior={best_unc['prior_games']}, "
          f"max_shrink={best_unc['max_shrink']} -> +{best_unc['delta_pp']:.3f}pp")

    # =======================================================================
    # PART 3: PARAMETER SWEEP - Marginal Trust
    # =======================================================================
    print("\n  SWEEP DE PARAMETROS - Marginal Trust")
    print(f"  {'-'*60}")
    print(f"  {'strength':>10} {'prior_games':>12} {'max_shrink':>11} {'Logloss':>9} {'Melhora':>10}")
    print(f"  {'-'*60}")

    sweep_mt = []
    configs_mt = [
        (0.10, 28.0, 0.72), (0.20, 28.0, 0.72), (0.35, 28.0, 0.72),
        (0.50, 28.0, 0.72), (0.70, 28.0, 0.72),  # default
        (0.70, 60.0, 0.72), (0.70, 28.0, 0.40), (0.70, 28.0, 0.20),
        (0.00, 28.0, 0.72),  # disabled
    ]
    for strength, pg, ms in configs_mt:
        p_test = _apply_marginal_trust(df, p_base, strength=strength, prior_games=pg, max_shrink=ms)
        ll = _safe_ll(y, p_test)
        d = (base_ll - ll) * 100 if ll is not None else 0
        marker = "  <-- default" if (strength, pg, ms) == (0.70, 28.0, 0.72) else ""
        sweep_mt.append({"strength": strength, "prior_games": pg, "max_shrink": ms,
                         "logloss": ll, "delta_pp": d})
        sign = "+" if d >= 0 else ""
        print(f"  {strength:>10.2f} {pg:>12.1f} {ms:>11.2f} {ll:>9.5f} {sign}{d:>8.3f}pp{marker}")

    best_mt = max(sweep_mt, key=lambda r: r["delta_pp"])
    print(f"\n  MELHOR CONFIG: strength={best_mt['strength']}, prior={best_mt['prior_games']}, "
          f"max_shrink={best_mt['max_shrink']} -> +{best_mt['delta_pp']:.3f}pp")

    # =======================================================================
    # PART 4: Impact by sample size bucket
    # =======================================================================
    print("\n  IMPACTO POR BUCKET DE TAMANHO DE AMOSTRA (Uncertainty default):")
    print(f"  {'-'*60}")
    print(f"  {'n_team':<18} {'N samples':>10} {'LL base':>9} {'LL+Unc':>9} {'Melhora':>10}")
    print(f"  {'-'*60}")

    buckets = [(0, 10, "muito pouco (<10)"), (10, 25, "pouco (10-25)"),
               (25, 50, "medio (25-50)"), (50, 100, "bom (50-100)"),
               (100, 9999, "abundante (>100)")]
    bucket_results = []
    for lo, hi, label in buckets:
        mask = (df["n_team"] >= lo) & (df["n_team"] < hi)
        if mask.sum() < 20:
            continue
        sub_y = df.loc[mask, "y"].tolist()
        sub_p_base = df.loc[mask, "p_base"].tolist()
        sub_idx = df.index[mask].tolist()
        sub_p_unc = [p_unc[i] for i in sub_idx]
        ll_b = _safe_ll(sub_y, sub_p_base)
        ll_u = _safe_ll(sub_y, sub_p_unc)
        d = (ll_b - ll_u) * 100 if (ll_b is not None and ll_u is not None) else 0
        bucket_results.append({"bucket": label, "n": int(mask.sum()), "ll_base": ll_b,
                               "ll_unc": ll_u, "delta_pp": d})
        sign = "+" if d >= 0 else ""
        print(f"  {label:<18} {int(mask.sum()):>10} {ll_b:>9.5f} {ll_u:>9.5f} {sign}{d:>8.3f}pp")

    print(f"\n{'='*72}\n")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "holdout_n": len(hold_samples),
        "train_n": len(train_samples),
        "baseline": {"logloss": base_ll, "ece": base_ece},
        "isolated_layers": isolated_results,
        "sweep_uncertainty": sweep_unc,
        "best_uncertainty": best_unc,
        "sweep_marginal_trust": sweep_mt,
        "best_marginal_trust": best_mt,
        "uncertainty_by_bucket": bucket_results,
    }


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--players-artifact", default="players_artifact.json")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--params", default=None)
    ap.add_argument("--holdout-days", type=int, default=180)
    ap.add_argument("--team-scale", type=float, default=1.0)
    ap.add_argument("--players-scale", type=float, default=1.0)
    ap.add_argument("--output", default=None)
    args = ap.parse_args(argv)

    csv_p = Path(str(args.csv)).expanduser()
    if csv_p.is_dir():
        cands = sorted(csv_p.glob("*.csv"), key=lambda x: x.stat().st_mtime, reverse=True)
        if not cands:
            print(f"[ERROR] No .csv files in {csv_p}", file=sys.stderr)
            sys.exit(1)
        csv_paths = [str(cands[0])]
        print(f"[INFO] Using newest CSV: {csv_paths[0]}")
    else:
        csv_paths = [str(csv_p)]

    report = run_isolated_ablation(
        artifact_path=str(args.artifact),
        players_artifact_path=str(args.players_artifact),
        csv_paths=csv_paths,
        params_fitted_path=args.params,
        holdout_days=int(args.holdout_days),
        team_scale=float(args.team_scale),
        players_scale=float(args.players_scale),
    )

    if report.get("error"):
        print(f"[ERROR] {report['error']}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[INFO] Report saved to {args.output}")


if __name__ == "__main__":
    main()
