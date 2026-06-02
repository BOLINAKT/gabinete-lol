"""Ablation study for LIVE pipeline layers (not training layers).

Measures the incremental contribution of each post-training layer to model quality.
Uses walk-forward hold-out evaluation to avoid data leakage.

Live layers evaluated
---------------------
  Base                 Output of training pipeline (p_fused_oof)
  + Uncertainty        apply_ml_uncertainty_adjust (shrinks toward 0.5 when low sample)
  + Marginal Trust     apply_ml_marginal_trust_adjust (shrinks marginal leagues)
  + Microseg Cal       apply_ml_microseg_calibration (per-segment bias correction)
  + Series Gamma       apply_series_gamma (per-league series adjustment, BO3/5 only)
  + Series Coherence   enforce_series_economic_coherence (BO bounds enforcement)

For each layer, we compute:
- Δ logloss (positive = improvement)
- Δ ECE (positive = improvement in calibration)
- Pct of samples actually changed by the layer
- Mean absolute shift in pp (probability-points)

This identifies layers that:
- IMPROVE (positive Δ logloss + reasonable change rate)
- NEUTRAL (~0 Δ logloss, minimal changes)
- HURT (negative Δ logloss, candidate for removal)

Usage
-----
    python tools/run_ablation_live_layers.py \\
        --artifact ml_artifact.json \\
        --players-artifact players_artifact.json \\
        --csv CSV_DIARIO \\
        [--params params_fitted.json] \\
        [--holdout-days 180] \\
        [--output ablation_live_report.json]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

from mlcore.artifact import MLArtifact
from mlcore.calibration import fit_platt_from_raw_probs
from mlcore.calibration_diagnostics import _apply_microseg_calibration, _ece, _load_games, _read_json_file_safe
from mlcore.fit_ml_params import _build_lineup_cache, _fuse_probs_by_precision, _make_samples
from mlcore.players_layer import PlayersArtifact, load_match_player_rows
from mlcore.series_bo_core import enforce_series_economic_coherence
from mlcore.bo import p_series_from_pmap
from mlcore.utils import brier, clip_prob, logloss

from app_core.ml_probability_adjustments_core import (
    apply_ml_marginal_trust_adjust,
    apply_ml_uncertainty_adjust,
    apply_series_gamma,
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

def _safe_ll(y: List[int], p: List[float]) -> Optional[float]:
    if not y or not p or len(y) != len(p):
        return None
    return float(logloss(y, p))


def _safe_ece(y: List[int], p: List[float], bins: int = 10) -> Optional[float]:
    if not y or not p or len(y) != len(p):
        return None
    return float(_ece(y, p, bins=bins))


def _safe_brier(y: List[int], p: List[float]) -> Optional[float]:
    if not y or not p or len(y) != len(p):
        return None
    return float(brier(y, p))


def _delta_pct(prev: Optional[float], curr: Optional[float]) -> Optional[float]:
    if prev is None or curr is None:
        return None
    return float(prev - curr)


def _change_stats(p_before: List[float], p_after: List[float]) -> Tuple[float, float, float]:
    """Return (pct_changed, mean_abs_shift_pp, max_abs_shift_pp)."""
    if not p_before or len(p_before) != len(p_after):
        return 0.0, 0.0, 0.0
    diffs = [abs(float(b) - float(a)) for b, a in zip(p_before, p_after)]
    n_changed = sum(1 for d in diffs if d > 1e-6)
    pct_changed = 100.0 * n_changed / len(diffs)
    mean_shift = (sum(diffs) / len(diffs)) * 100.0
    max_shift = max(diffs) * 100.0
    return pct_changed, mean_shift, max_shift


# ---------------------------------------------------------------------------
# Holdout split (same as training ablation)
# ---------------------------------------------------------------------------

def _chronological_holdout(samples: list, holdout_days: int) -> Tuple[list, list]:
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
        print(f"      [WARN] Using 75/25 chronological fallback. Train: {split_idx}, Hold: {n_hold}")
        return samples_sorted[:split_idx], samples_sorted[split_idx:]
    return train, hold


# ---------------------------------------------------------------------------
# Helpers to construct ml_info for each sample
# ---------------------------------------------------------------------------

def _build_ml_info(s: Any) -> Dict[str, Any]:
    """Reconstruct ml_info dict from a sample so uncertainty/marginal layers work."""
    n_team = float(getattr(s, "n_team", 0.0) or 0.0)
    n_players = float(getattr(s, "n_players", 0.0) or 0.0)
    league = str(getattr(s, "league", "") or "")
    # Estimate per-side games (n_team is global; split evenly as conservative proxy)
    return {
        "blue": {"games_played": int(max(0, round(n_team / 2.0))), "league": league},
        "red":  {"games_played": int(max(0, round(n_team / 2.0))), "league": league},
        "n_players_eff": float(n_players),
    }


# ---------------------------------------------------------------------------
# Run ablation
# ---------------------------------------------------------------------------

def run_live_ablation(
    *,
    artifact_path: str,
    players_artifact_path: str,
    csv_paths: List[str],
    params_fitted_path: Optional[str] = None,
    holdout_days: int = 180,
    team_scale: float = 1.0,
    players_scale: float = 1.0,
    bins: int = 10,
) -> Dict[str, Any]:
    print(f"\n{'='*72}")
    print("  ABLATION STUDY - CAMADAS DO LIVE PIPELINE")
    print(f"{'='*72}")

    # ---- Load ---------------------------------------------------------------
    print("\n[1/4] Carregando dados e artefatos...")
    g = _load_games(csv_paths)
    if g.empty:
        return {"error": "no_games"}
    print(f"      {len(g)} games carregados.")

    art = MLArtifact.load_json(str(artifact_path))
    p_art = PlayersArtifact.load_json(str(players_artifact_path))
    w_lineup = float((((art.meta or {}).get("players_layer") or {}).get("w_lineup") or 0.85))

    gameids = set(g["gameid"].astype(str).tolist())
    pr = load_match_player_rows(csv_paths, keep_playoffs=None, gameids=gameids)
    lineup_cache = _build_lineup_cache(pr)
    samples = _make_samples(
        art=art,
        p_art=p_art,
        games=g,
        lineup_cache=lineup_cache,
        w_lineup=w_lineup,
    )
    if not samples:
        return {"error": "no_samples"}
    print(f"      {len(samples)} samples criados.")

    # ---- Holdout split ------------------------------------------------------
    print(f"[2/4] Splitting holdout ({holdout_days} dias)...")
    train_samples, hold_samples = _chronological_holdout(samples, holdout_days)
    print(f"      Train: {len(train_samples)}, Holdout: {len(hold_samples)}")
    if len(hold_samples) < 50:
        return {"error": f"holdout too small: {len(hold_samples)}"}

    # ---- Build base probabilities (p_fused_oof) on holdout -----------------
    print("[3/4] Computando probabilidades base...")
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

    # Load microseg table
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
            "p_base": p_base,
            "ml_info": _build_ml_info(s),
        })

    df = pd.DataFrame(rows)
    y = df["y"].tolist()
    p_base = df["p_base"].tolist()

    # ---- Apply each layer in isolation -------------------------------------
    print("[4/4] Aplicando cada camada isoladamente...")

    layer_results: List[Dict[str, Any]] = []

    # Baseline
    layer_results.append({
        "layer": "L0 Base (p_fused_oof)",
        "logloss": _safe_ll(y, p_base),
        "ece": _safe_ece(y, p_base),
        "brier": _safe_brier(y, p_base),
        "pct_changed": 0.0,
        "mean_shift_pp": 0.0,
        "delta_logloss_pp": 0.0,
    })

    # --- Layer 1: Uncertainty -----------------------------------------------
    p_unc = []
    for _, row in df.iterrows():
        p_in = float(row["p_base"])
        p_out, _ = apply_ml_uncertainty_adjust(
            p_in,
            row["ml_info"],
            clip_prob_fn=clip_prob,
            enabled=True,
            strength=0.55,
            prior_games=22.0,
            max_shrink=0.65,
        )
        p_unc.append(float(p_out))

    pct, mean_sh, _ = _change_stats(p_base, p_unc)
    layer_results.append({
        "layer": "L1 + Uncertainty",
        "logloss": _safe_ll(y, p_unc),
        "ece": _safe_ece(y, p_unc),
        "brier": _safe_brier(y, p_unc),
        "pct_changed": pct,
        "mean_shift_pp": mean_sh,
        "delta_logloss_pp": _delta_pct(layer_results[-1]["logloss"], _safe_ll(y, p_unc)),
    })

    # --- Layer 2: Marginal Trust --------------------------------------------
    p_marg = []
    for i, row in df.iterrows():
        p_in = float(p_unc[i])  # apply on top of uncertainty
        try:
            p_out, _ = apply_ml_marginal_trust_adjust(
                p_in,
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
                strength=0.70,
                prior_games=28.0,
                max_shrink=0.72,
                cap_prob=0.84,
                confidence_score=72.0,
            )
        except Exception:
            p_out = p_in
        p_marg.append(float(p_out))

    pct, mean_sh, _ = _change_stats(p_unc, p_marg)
    layer_results.append({
        "layer": "L2 + Marginal Trust",
        "logloss": _safe_ll(y, p_marg),
        "ece": _safe_ece(y, p_marg),
        "brier": _safe_brier(y, p_marg),
        "pct_changed": pct,
        "mean_shift_pp": mean_sh,
        "delta_logloss_pp": _delta_pct(layer_results[-1]["logloss"], _safe_ll(y, p_marg)),
    })

    # --- Layer 3: Microseg (already applied in base but test as separate layer)
    p_mseg = []
    if microseg_table:
        for i, row in df.iterrows():
            p_in = float(p_marg[i])
            try:
                p_out = float(clip_prob(_apply_microseg_calibration(
                    p_in,
                    league=str(row["league"]),
                    split=str(row["split"]),
                    side=str(row["side"]),
                    bo=str(row["bo"]),
                    phase=str(row["phase"]),
                    table=microseg_table,
                    min_n=30,
                    strength=0.60,
                    cap_pp=8.0,
                    hierarchical=True,
                    hierarchy_decay=0.80,
                )))
            except Exception:
                p_out = p_in
            p_mseg.append(p_out)
    else:
        p_mseg = list(p_marg)

    pct, mean_sh, _ = _change_stats(p_marg, p_mseg)
    layer_results.append({
        "layer": "L3 + Microseg",
        "logloss": _safe_ll(y, p_mseg),
        "ece": _safe_ece(y, p_mseg),
        "brier": _safe_brier(y, p_mseg),
        "pct_changed": pct,
        "mean_shift_pp": mean_sh,
        "delta_logloss_pp": _delta_pct(layer_results[-1]["logloss"], _safe_ll(y, p_mseg)),
    })

    # --- Layer 4: Series Gamma (BO3/5 only, on p_series) --------------------
    # Series gamma applies on p_series, not p_map. We compute the equivalent
    # p_series from p_map and measure impact on the series prediction.
    p_series_base = []
    p_series_gamma = []
    y_series = []
    for i, row in df.iterrows():
        bo = int(row["bo"]) if str(row["bo"]).isdigit() else 1
        if bo not in (3, 5):
            continue
        p_map = float(p_mseg[i])
        ps_base = float(clip_prob(p_series_from_pmap(p_map, bo)))
        gamma = 1.0  # use default; per-league gammas would require fit_params
        ps_gamma = float(apply_series_gamma(ps_base, gamma))
        p_series_base.append(ps_base)
        p_series_gamma.append(ps_gamma)
        y_series.append(int(row["y"]))

    pct_g, mean_sh_g, _ = _change_stats(p_series_base, p_series_gamma)
    layer_results.append({
        "layer": "L4 Series Gamma (BO3/5)",
        "logloss": _safe_ll(y_series, p_series_gamma) if y_series else None,
        "logloss_base": _safe_ll(y_series, p_series_base) if y_series else None,
        "n_eligible": len(y_series),
        "pct_changed": pct_g,
        "mean_shift_pp": mean_sh_g,
        "delta_logloss_pp": _delta_pct(_safe_ll(y_series, p_series_base), _safe_ll(y_series, p_series_gamma)) if y_series else None,
    })

    # --- Layer 5: Series Coherence (BO3/5 only) -----------------------------
    p_series_coh = []
    p_series_coh_before = []
    y_series_coh = []
    for i, row in df.iterrows():
        bo = int(row["bo"]) if str(row["bo"]).isdigit() else 1
        if bo not in (3, 5):
            continue
        p_map = float(p_mseg[i])
        ps_in = float(clip_prob(p_series_from_pmap(p_map, bo)))
        result = enforce_series_economic_coherence(p_map=p_map, p_series=ps_in, bo=bo)
        ps_out = result.get("p_series_after") if result.get("applied") else ps_in
        if ps_out is None:
            ps_out = ps_in
        p_series_coh_before.append(ps_in)
        p_series_coh.append(float(ps_out))
        y_series_coh.append(int(row["y"]))

    pct_c, mean_sh_c, _ = _change_stats(p_series_coh_before, p_series_coh)
    layer_results.append({
        "layer": "L5 Series Coherence (BO3/5)",
        "logloss": _safe_ll(y_series_coh, p_series_coh) if y_series_coh else None,
        "logloss_base": _safe_ll(y_series_coh, p_series_coh_before) if y_series_coh else None,
        "n_eligible": len(y_series_coh),
        "pct_changed": pct_c,
        "mean_shift_pp": mean_sh_c,
        "delta_logloss_pp": _delta_pct(_safe_ll(y_series_coh, p_series_coh_before), _safe_ll(y_series_coh, p_series_coh)) if y_series_coh else None,
    })

    # ---- Print report -------------------------------------------------------
    print(f"\n{'='*72}")
    print(f"  RESULTADOS - {len(hold_samples)} samples no holdout")
    print(f"{'='*72}\n")

    print(f"  CAMADAS DE MAP-LEVEL (todos os {len(hold_samples)} samples):")
    print(f"  {'Camada':<27} {'Logloss':>8} {'Melhora':>10} {'ECE':>7} {'%mud':>6} {'shift':>7}")
    print(f"  {'-'*72}")
    for r in layer_results[:4]:
        ll = r.get("logloss")
        d_ll = r.get("delta_logloss_pp")
        ece = r.get("ece")
        pct = r.get("pct_changed", 0.0)
        sh = r.get("mean_shift_pp", 0.0)
        ll_s = f"{ll:.5f}" if ll is not None else "  N/A  "
        if d_ll is None or d_ll == 0:
            d_s = "   -    "
        else:
            sign = "+" if d_ll >= 0 else ""
            d_s = f"{sign}{d_ll*100:.3f}pp"
        ece_s = f"{ece:.4f}" if ece is not None else "  N/A "
        print(f"  {r['layer']:<27} {ll_s:>8} {d_s:>10} {ece_s:>7} {pct:>5.1f}% {sh:>6.2f}")

    print("\n  CAMADAS DE SERIES-LEVEL (somente BO3/5):")
    print(f"  {'Camada':<27} {'N elig':>7} {'LL base':>8} {'LL after':>9} {'Melhora':>10} {'%mud':>6}")
    print(f"  {'-'*78}")
    for r in layer_results[4:]:
        n_e = r.get("n_eligible", 0)
        ll = r.get("logloss")
        ll_b = r.get("logloss_base")
        d_ll = r.get("delta_logloss_pp")
        pct = r.get("pct_changed", 0.0)
        ll_s = f"{ll:.5f}" if ll is not None else "  N/A  "
        ll_b_s = f"{ll_b:.5f}" if ll_b is not None else "  N/A  "
        if d_ll is None or d_ll == 0:
            d_s = "   -    "
        else:
            sign = "+" if d_ll >= 0 else ""
            d_s = f"{sign}{d_ll*100:.3f}pp"
        print(f"  {r['layer']:<27} {n_e:>7} {ll_b_s:>8} {ll_s:>9} {d_s:>10} {pct:>5.1f}%")

    # ---- Verdict ------------------------------------------------------------
    print("\n  VEREDITO POR CAMADA:")
    print(f"  {'-'*72}")
    for r in layer_results[1:]:
        d_ll = r.get("delta_logloss_pp")
        pct = r.get("pct_changed", 0.0)
        layer = r["layer"]
        if d_ll is None:
            verdict = "[?] dados insuficientes"
        elif pct < 1.0:
            verdict = "[=] inativa (quase nao muda probs)"
        elif d_ll > 0.0005:
            verdict = "[+] AJUDA"
        elif abs(d_ll) <= 0.0005:
            verdict = "[=] neutra"
        else:
            verdict = "[-] PIORA - candidata a remocao"
        print(f"    {layer:<27} {verdict}")

    print(f"\n{'='*72}\n")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "holdout_n": len(hold_samples),
        "train_n": len(train_samples),
        "layers": layer_results,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

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

    report = run_live_ablation(
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
