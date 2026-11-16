"""Phase 1 validation: run all candidate improvements through the acceptance gate.

For each candidate, computes baseline vs candidate probabilities on the TEST set
and runs the gate (Δlogloss > 0.002, p<0.05, ECE not worse).

Candidates evaluated
--------------------
  1. POST-FUSION CAL: apply Microseg + Platt AFTER team+players fusion
  2. UNCERTAINTY OFF: confirm the layer hurts when re-enabled (retroactive)
  3. MARGINAL TRUST OFF: idem
  4. SERIES GAMMA PER-LEAGUE: fit per-league gammas on train, validate on test

The baseline for ALL candidates is the production layer (L4 = Microseg + Platt
sequential pre-fusion, the simulated training pipeline output).

Usage
-----
    python tools/run_phase1_validation.py --val-cutoff 2026-03-31 --output FASE1_VALIDATION.json
"""
from __future__ import annotations

import argparse
import json
import math
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
from typing import Any, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

from mlcore.artifact import MLArtifact
from mlcore.bo import p_series_from_pmap
from mlcore.calibration import fit_platt_from_raw_probs
from mlcore.calibration_diagnostics import _apply_microseg_calibration, _read_json_file_safe
from mlcore.fit_ml_params import _build_lineup_cache, _fuse_probs_by_precision, _make_samples
from mlcore.io_oracle import load_oracle_elixir_games
from mlcore.players_layer import PlayersArtifact, load_match_player_rows
from mlcore.utils import clip_prob

from mlcore.ml_eval import acceptance_gate, build_split, metrics_with_ci

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
# Setup helpers
# ---------------------------------------------------------------------------

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


def _load_games_multi(csv_paths: List[str]) -> pd.DataFrame:
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


def _build_ml_info(s):
    n_team = float(getattr(s, "n_team", 0.0) or 0.0)
    n_players = float(getattr(s, "n_players", 0.0) or 0.0)
    league = str(getattr(s, "league", "") or "")
    return {
        "blue": {"games_played": int(max(0, round(n_team / 2.0))), "league": league},
        "red":  {"games_played": int(max(0, round(n_team / 2.0))), "league": league},
        "n_players_eff": float(n_players),
    }


def _apply_ms(p, s, table):
    if not table:
        return float(p)
    try:
        return float(clip_prob(_apply_microseg_calibration(
            float(p),
            league=str(s.league), split=str(getattr(s, "split", "")),
            side=str(getattr(s, "side", "blue")), bo=str(getattr(s, "bo_bucket", "1")),
            phase=str(getattr(s, "phase", "regular")),
            table=table, min_n=30, strength=0.60, cap_pp=8.0,
            hierarchical=True, hierarchy_decay=0.80,
        )))
    except Exception:
        return float(p)


def _fuse(s):
    return float(clip_prob(_fuse_probs_by_precision(
        p_team=float(s.p_team), p_players=float(s.p_players),
        n_team=float(s.n_team), n_players=float(s.n_players),
        team_scale=1.0, players_scale=1.0,
    )))


# ---------------------------------------------------------------------------
# Series gamma fit per league
# ---------------------------------------------------------------------------

def _eval_gamma(y: List[int], p_map: List[float], gamma: float, bo: int) -> float:
    """Compute logloss for a given gamma applied to p_series."""
    from mlcore.utils import logloss
    p_series_y = []
    y_keep = []
    for yi, pm in zip(y, p_map):
        if not math.isfinite(pm):
            continue
        ps_base = float(clip_prob(p_series_from_pmap(pm, bo)))
        ps = float(apply_series_gamma(ps_base, gamma))
        p_series_y.append(ps)
        y_keep.append(int(yi))
    if not y_keep:
        return float("inf")
    return float(logloss(y_keep, p_series_y))


def _fit_best_gamma(y: List[int], p_map: List[float], bo: int) -> Tuple[float, float, int]:
    """Grid search for best gamma in [0.6, 2.0]. Returns (gamma, logloss, n_samples)."""
    if not y or len(y) < 30:
        return 1.0, float("inf"), len(y)
    grid = [round(0.6 + 0.05 * i, 2) for i in range(int((2.0 - 0.6) / 0.05) + 1)]
    best = (1.0, _eval_gamma(y, p_map, 1.0, bo))
    for g in grid:
        ll = _eval_gamma(y, p_map, g, bo)
        if ll < best[1]:
            best = (g, ll)
    return best[0], best[1], len(y)


# ---------------------------------------------------------------------------
# Main validation
# ---------------------------------------------------------------------------

def run_phase1(
    *, artifact_path: str, players_artifact_path: str, csv_paths: List[str],
    params_fitted_path: Optional[str], val_cutoff: str = "2026-03-31",
    train_years: tuple = (2024, 2025), val_year: int = 2026,
    n_bootstrap: int = 1000,
) -> Dict[str, Any]:
    print(f"\n{'='*72}")
    print("  FASE 1 VALIDATION - gate runs for all candidate improvements")
    print(f"{'='*72}\n")

    # Load
    print("[1/4] Loading data and building samples...")
    g = _load_games_multi(csv_paths)
    art = MLArtifact.load_json(artifact_path)
    p_art = PlayersArtifact.load_json(players_artifact_path)
    w_lineup = float((((art.meta or {}).get("players_layer") or {}).get("w_lineup") or 0.85))
    gameids = set(g["gameid"].astype(str).tolist())
    pr = load_match_player_rows(csv_paths, keep_playoffs=None, gameids=gameids)
    lineup_cache = _build_lineup_cache(pr)
    samples = _make_samples(art=art, p_art=p_art, games=g, lineup_cache=lineup_cache, w_lineup=w_lineup)

    split = build_split(samples, train_years=train_years, val_year=val_year, val_cutoff=val_cutoff)
    summary = split.summary()
    print(f"      Train: {summary['train']['n']}, Val: {summary['val']['n']}, Test: {summary['test']['n']}")

    # Load microseg table
    microseg_table = {}
    if params_fitted_path:
        prm = _read_json_file_safe(Path(params_fitted_path))
        microseg_table = (prm.get("microseg_calibration") or {}).get("table") or {}

    # Fit two Platt models from training set:
    #   platt_team:   on p_team_cal (used in current production BEFORE fusion)
    #   platt_fused:  on microseg'd fused (used as proposed post-fusion cal)
    print("[2/4] Fitting Platt models on training set...")
    train_y = [int(s.y) for s in split.train.samples]

    # Pre-fusion path: microseg on p_team -> Platt on microseg'd p_team -> fuse with players
    train_p_team_ms = [_apply_ms(float(s.p_team), s, microseg_table) for s in split.train.samples]
    platt_team_postms = fit_platt_from_raw_probs(train_y, train_p_team_ms)

    # Post-fusion path: fuse(cal'd team, players) -> microseg on fused -> Platt on fused
    train_p_fused_prod = []
    for s, p_t_ms in zip(split.train.samples, train_p_team_ms):
        p_t_cal = float(clip_prob(platt_team_postms.predict_proba(p_t_ms)))
        pf = float(clip_prob(_fuse_probs_by_precision(
            p_team=p_t_cal, p_players=float(s.p_players),
            n_team=float(s.n_team), n_players=float(s.n_players),
            team_scale=1.0, players_scale=1.0,
        )))
        train_p_fused_prod.append(pf)
    train_p_fused_prod_ms = [_apply_ms(p, s, microseg_table) for p, s in zip(train_p_fused_prod, split.train.samples)]
    platt_fused_postms = fit_platt_from_raw_probs(train_y, train_p_fused_prod_ms)

    # Compute production baseline on TEST:
    #   microseg(p_team) -> platt(p_team_ms) -> fuse(p_team_cal, p_players)
    print("[3/4] Computing PRODUCTION baseline on TEST...")
    y_test = [int(s.y) for s in split.test.samples]
    p_baseline = []  # production: cal BEFORE fusion only
    p_postfusion_extra = []  # production + cal AFTER fusion
    for s in split.test.samples:
        # Pre-fusion cal on p_team
        p_t_ms = _apply_ms(float(s.p_team), s, microseg_table)
        p_t_cal = float(clip_prob(platt_team_postms.predict_proba(p_t_ms)))
        # Fuse with players
        p_fused = float(clip_prob(_fuse_probs_by_precision(
            p_team=p_t_cal, p_players=float(s.p_players),
            n_team=float(s.n_team), n_players=float(s.n_players),
            team_scale=1.0, players_scale=1.0,
        )))
        p_baseline.append(p_fused)
        # Add post-fusion cal: microseg + platt on fused
        p_fused_ms = _apply_ms(p_fused, s, microseg_table)
        p_fused_cal = float(clip_prob(platt_fused_postms.predict_proba(p_fused_ms)))
        p_postfusion_extra.append(p_fused_cal)

    base_metrics = metrics_with_ci(y_test, p_baseline, n_bootstrap=n_bootstrap)
    print(f"      Baseline (production) logloss: {base_metrics['logloss'].point:.5f} "
          f"CI[{base_metrics['logloss'].ci_low:.5f}, {base_metrics['logloss'].ci_high:.5f}]")
    print(f"      Baseline (production) ECE:     {base_metrics['ece'].point:.4f}")

    candidates = []

    # ----- Candidate 1: Add post-fusion cal ON TOP of pre-fusion cal -----
    print("\n[4/4] Running gate on each candidate...\n")
    print("--- Candidate 1: POST-FUSION CAL (added on top of pre-fusion cal) ---")
    gate1 = acceptance_gate(y_test, p_baseline, p_postfusion_extra, n_bootstrap=n_bootstrap)
    print(f"  {gate1.summary_line()}")
    candidates.append({
        "name": "post_fusion_cal",
        "description": "Production (pre-fusion cal) + extra Microseg + Platt AFTER team+players fusion",
        "decision": gate1.as_dict(),
    })

    # ----- Candidate 2: Uncertainty layer ENABLED (verify it would hurt) -----
    print("\n--- Candidate 2: UNCERTAINTY ENABLED (retroactive validation) ---")
    p_unc_on = []
    for i, s in enumerate(split.test.samples):
        ml = _build_ml_info(s)
        p_out, _ = apply_ml_uncertainty_adjust(
            float(p_baseline[i]), ml,
            clip_prob_fn=clip_prob,
            enabled=True, strength=0.55, prior_games=22.0, max_shrink=0.65,
        )
        p_unc_on.append(float(p_out))
    gate2 = acceptance_gate(y_test, p_baseline, p_unc_on, n_bootstrap=n_bootstrap)
    print(f"  {gate2.summary_line()}")
    candidates.append({
        "name": "uncertainty_enabled",
        "description": "Retroactive: enable Uncertainty layer with old defaults (strength=0.55, prior=22)",
        "decision": gate2.as_dict(),
        "interpretation": "REJECT = baseline (disabled) is correct; ACCEPT = should re-enable",
    })

    # ----- Candidate 3: Marginal Trust ENABLED -----
    print("\n--- Candidate 3: MARGINAL TRUST ENABLED (retroactive validation) ---")
    p_mt_on = []
    for i, s in enumerate(split.test.samples):
        ml = _build_ml_info(s)
        try:
            p_out, _ = apply_ml_marginal_trust_adjust(
                float(p_baseline[i]), ml,
                clip_prob_fn=clip_prob,
                norm_league_key_fn=norm_league_key,
                tier_from_league_fn=tier_from_league,
                ml_league_conf_band_fn=ml_league_conf_band,
                ml_marginal_band_profile_fn=ml_marginal_band_profile,
                league_is_excluded_fn=league_is_excluded,
                is_marginal_league_for_ml_fn=is_marginal_league_for_ml,
                sanitize_ml_marginal_band_coeffs_fn=sanitize_ml_marginal_band_coeffs,
                league=str(s.league),
                enabled=True, strength=0.70, prior_games=28.0, max_shrink=0.72,
                cap_prob=0.84, confidence_score=72.0,
            )
        except Exception:
            p_out = p_baseline[i]
        p_mt_on.append(float(p_out))
    gate3 = acceptance_gate(y_test, p_baseline, p_mt_on, n_bootstrap=n_bootstrap)
    print(f"  {gate3.summary_line()}")
    candidates.append({
        "name": "marginal_trust_enabled",
        "description": "Retroactive: enable Marginal Trust with old defaults (strength=0.70, prior=28)",
        "decision": gate3.as_dict(),
        "interpretation": "REJECT = baseline (disabled) is correct; ACCEPT = should re-enable",
    })

    # ----- Candidate 4: Series gamma per-league (fit on train, validate on test) -----
    print("\n--- Candidate 4: SERIES GAMMA PER-LEAGUE (BO3/BO5 only) ---")
    # Fit best gamma per league per BO on training set, evaluate on test
    train_by_league_bo: Dict[Tuple[str, int], Dict[str, list]] = {}
    for s in split.train.samples:
        bo = int(getattr(s, "bo_bucket", 1)) if str(getattr(s, "bo_bucket", "1")).isdigit() else 1
        if bo not in (3, 5):
            continue
        lg = str(s.league)
        key = (lg, bo)
        if key not in train_by_league_bo:
            train_by_league_bo[key] = {"p_map": [], "y": []}
        train_by_league_bo[key]["p_map"].append(_fuse(s))
        train_by_league_bo[key]["y"].append(int(s.y))

    league_gammas: Dict[Tuple[str, int], float] = {}
    fit_results = []
    for (lg, bo), d in train_by_league_bo.items():
        if len(d["y"]) < 50:
            league_gammas[(lg, bo)] = 1.3  # fallback to global BO3 default
            continue
        gamma_best, _, n = _fit_best_gamma(d["y"], d["p_map"], bo)
        league_gammas[(lg, bo)] = gamma_best
        fit_results.append({"league": lg, "bo": bo, "gamma": gamma_best, "n_train": n})

    print(f"      Fitted gammas for {len(fit_results)} (league, bo) pairs")

    # Apply baseline (global gamma=1.3 for BO3, 1.0 for BO5) vs candidate (per-league)
    p_series_base = []
    p_series_cand = []
    y_series = []
    for s in split.test.samples:
        bo = int(getattr(s, "bo_bucket", 1)) if str(getattr(s, "bo_bucket", "1")).isdigit() else 1
        if bo not in (3, 5):
            continue
        pm = _fuse(s)
        if not math.isfinite(pm):
            continue
        ps_base = float(clip_prob(p_series_from_pmap(pm, bo)))
        # Global gamma: 1.3 for BO3, 1.0 for BO5
        gamma_global = 1.3 if bo == 3 else 1.0
        gamma_lg = league_gammas.get((str(s.league), bo), gamma_global)
        p_series_base.append(float(apply_series_gamma(ps_base, gamma_global)))
        p_series_cand.append(float(apply_series_gamma(ps_base, gamma_lg)))
        y_series.append(int(s.y))

    if len(y_series) >= 50:
        gate4 = acceptance_gate(y_series, p_series_base, p_series_cand, n_bootstrap=n_bootstrap)
        print(f"      Test series BO3/5 samples: {len(y_series)}")
        print(f"      {gate4.summary_line()}")
        candidates.append({
            "name": "series_gamma_per_league",
            "description": f"Fit per-league gammas on train ({len(fit_results)} pairs), apply on test BO3/5",
            "decision": gate4.as_dict(),
            "fitted_gammas": fit_results,
        })
    else:
        print(f"      INSUFFICIENT SERIES SAMPLES IN TEST ({len(y_series)} < 50) — skipping gate")
        candidates.append({
            "name": "series_gamma_per_league",
            "description": "Skipped: insufficient series samples in test",
            "decision": {"accept": False, "reason": "insufficient_series_samples_in_test"},
        })

    # Summary
    print(f"\n{'='*72}")
    print("  SUMMARY")
    print(f"{'='*72}")
    for c in candidates:
        d = c["decision"]
        verdict = "ACCEPT" if d.get("accept") else "REJECT"
        print(f"  [{verdict}] {c['name']:<32} reason={d.get('reason', '')[:50]}")
    print(f"{'='*72}\n")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": "phase1_validation_v1",
        "split": summary,
        "baseline_metrics": {
            "logloss": base_metrics["logloss"].as_dict(),
            "ece": base_metrics["ece"].as_dict(),
            "brier": base_metrics["brier"].as_dict(),
        },
        "candidates": candidates,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--players-artifact", default="players_artifact.json")
    ap.add_argument("--csv-train", default="CSV_HISTORICO")
    ap.add_argument("--csv-current", default="CSV_DIARIO")
    ap.add_argument("--params", default="params_fitted.json")
    ap.add_argument("--val-cutoff", default="2026-03-31")
    ap.add_argument("--n-bootstrap", type=int, default=1000)
    ap.add_argument("--output", default="FASE1_VALIDATION.json")
    args = ap.parse_args()

    csv_paths = _gather_csvs([args.csv_train, args.csv_current])
    report = run_phase1(
        artifact_path=args.artifact,
        players_artifact_path=args.players_artifact,
        csv_paths=csv_paths,
        params_fitted_path=args.params,
        val_cutoff=args.val_cutoff,
        n_bootstrap=int(args.n_bootstrap),
    )
    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[INFO] Report saved to {args.output}")


if __name__ == "__main__":
    main()
