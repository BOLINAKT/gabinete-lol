"""Ablation study for the ML pipeline.

Measures the incremental contribution of each layer to model quality (logloss, ECE, Brier).
Uses walk-forward hold-out evaluation to avoid data leakage.

Layers evaluated
----------------
  L0  p_team          Base Elo only (no calibration, no players)
  L1  p_cal           Elo + OOF Platt calibration
  L2  p_fused_raw     + Players layer fusion
  L3  p_fused_cal     + Microseg / hierarchical calibration on fused
  L4  p_fused_oof     + OOF Platt calibration applied to fused output

A positive Δ_logloss means the layer IMPROVES the model (lower logloss = better).
A positive Δ_ece means the layer IMPROVES calibration (lower ECE = better).

Usage
-----
    python tools/run_ablation_study.py \\
        --artifact ml_artifact.json \\
        --players-artifact players_artifact.json \\
        --csv CSV_DIARIO \\
        [--params params_fitted.json] \\
        [--holdout-days 180] \\
        [--output ablation_report.json]
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

# ---------------------------------------------------------------------------
# Bootstrap path so the script can be run from the repo root directly.
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

from mlcore.artifact import MLArtifact
from mlcore.calibration import fit_platt_from_raw_probs
from mlcore.calibration_diagnostics import (
    _apply_microseg_calibration,
    _ece,
    _load_games,
    _read_json_file_safe,
)
from mlcore.fit_ml_params import _build_lineup_cache, _fuse_probs_by_precision, _make_samples
from mlcore.players_layer import PlayersArtifact, load_match_player_rows
from mlcore.utils import brier, clip_prob, logloss


# ---------------------------------------------------------------------------
# Metrics helpers
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


def _metrics_row(name: str, y: List[int], p: List[float]) -> Dict[str, Any]:
    ll = _safe_ll(y, p)
    ece = _safe_ece(y, p)
    br = _safe_brier(y, p)
    return {
        "layer": name,
        "n": len(y),
        "logloss": ll,
        "ece": ece,
        "brier": br,
    }


def _delta(prev: Optional[float], curr: Optional[float], lower_is_better: bool = True) -> Optional[float]:
    if prev is None or curr is None:
        return None
    d = prev - curr  # positive = improvement when lower_is_better
    return float(d) if lower_is_better else float(curr - prev)


def _fmt_metric(v: Optional[float], decimals: int = 5) -> str:
    if v is None:
        return "  N/A   "
    return f"{v:.{decimals}f}"


def _fmt_delta(v: Optional[float]) -> str:
    if v is None:
        return "    -   "
    sign = "+" if v >= 0 else ""
    return f"{sign}{v*100:.3f}pp"


# ---------------------------------------------------------------------------
# Holdout split
# ---------------------------------------------------------------------------

def _chronological_holdout(
    samples: list,
    holdout_days: int,
) -> Tuple[list, list]:
    """Split samples into train/holdout by date (no leakage).

    Falls back to 75/25 percentage split if date-based split yields no training data.
    """
    dates = [str(getattr(s, "date_day", "") or "") for s in samples]
    valid_dates = sorted([d for d in dates if d.strip()])
    if not valid_dates:
        n = max(1, int(len(samples) * 0.25))
        return samples[:-n], samples[-n:]
    cutoff_dt = pd.Timestamp(valid_dates[-1]) - pd.Timedelta(days=int(holdout_days))
    cutoff_str = cutoff_dt.date().isoformat()
    train = [s for s, d in zip(samples, dates) if d < cutoff_str]
    hold = [s for s, d in zip(samples, dates) if d >= cutoff_str]
    # Fallback: if date-based split has < 20% training data, use fixed 75/25 split
    if len(train) < max(50, int(len(samples) * 0.20)):
        n_hold = max(50, int(len(samples) * 0.25))
        sorted_samples = sorted(zip(dates, samples), key=lambda x: x[0])
        samples_sorted = [s for _, s in sorted_samples]
        split_idx = len(samples_sorted) - n_hold
        print("      [WARN] Date split has insufficient training data. Using 75/25 chronological split.")
        print(f"      Train: {split_idx}, Holdout: {n_hold}")
        return samples_sorted[:split_idx], samples_sorted[split_idx:]
    return train, hold


# ---------------------------------------------------------------------------
# Calibration helpers
# ---------------------------------------------------------------------------

def _fit_platt_on_train(train_samples: list, p_col: str = "p_team") -> Optional[Any]:
    """Fit Platt calibrator on training samples using the given probability column."""
    y = [int(s.y) for s in train_samples]
    p = [float(getattr(s, p_col)) for s in train_samples]
    finite_pairs = [(yi, pi) for yi, pi in zip(y, p) if math.isfinite(pi)]
    if len(finite_pairs) < 100:
        return None
    yy, pp = zip(*finite_pairs)
    try:
        return fit_platt_from_raw_probs(list(yy), list(pp))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main ablation
# ---------------------------------------------------------------------------

def run_ablation(
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
    print(f"\n{'='*60}")
    print("  ML PIPELINE ABLATION STUDY")
    print(f"{'='*60}")

    # ---- Load data ----------------------------------------------------------
    print("\n[1/5] Loading CSV data...")
    g = _load_games(csv_paths)
    if g.empty:
        return {"error": "no_games"}
    print(f"      {len(g)} games loaded.")

    print("[2/5] Loading artifacts...")
    art = MLArtifact.load_json(str(artifact_path))
    p_art = PlayersArtifact.load_json(str(players_artifact_path))
    w_lineup = float((((art.meta or {}).get("players_layer") or {}).get("w_lineup") or 0.85))

    print("[3/5] Building samples...")
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
    print(f"      {len(samples)} samples built.")

    # ---- Split --------------------------------------------------------------
    print(f"[4/5] Splitting holdout ({holdout_days} days)...")
    train_samples, hold_samples = _chronological_holdout(samples, holdout_days)
    print(f"      Train: {len(train_samples)}, Holdout: {len(hold_samples)}")
    if len(hold_samples) < 50:
        return {"error": f"holdout too small: {len(hold_samples)} samples. Reduce --holdout-days."}

    # ---- Load microseg table ------------------------------------------------
    microseg_table: Dict[str, Dict[str, float]] = {}
    if params_fitted_path:
        prm = _read_json_file_safe(Path(str(params_fitted_path)).expanduser())
        ms_pack = prm.get("microseg_calibration") if isinstance(prm.get("microseg_calibration"), dict) else {}
        ms_tbl = ms_pack.get("table") if isinstance(ms_pack.get("table"), dict) else {}
        if isinstance(ms_tbl, dict):
            microseg_table = ms_tbl
        print(f"      Microseg table: {len(microseg_table)} segments loaded.")

    # ---- Fit Platt on training set ------------------------------------------
    print("[5/5] Fitting calibrators on training set...")
    platt_team = _fit_platt_on_train(train_samples, "p_team")

    # ---- Build holdout DataFrame -------------------------------------------
    rows = []
    for s in hold_samples:
        p_team = float(clip_prob(float(s.p_team)))
        p_players = float(clip_prob(float(s.p_players)))

        p_fused_raw = float(clip_prob(float(_fuse_probs_by_precision(
            p_team=float(s.p_team),
            p_players=float(s.p_players),
            n_team=float(s.n_team),
            n_players=float(s.n_players),
            team_scale=float(team_scale),
            players_scale=float(players_scale),
        ))))

        p_cal = float(clip_prob(platt_team.predict_proba(p_team))) if platt_team else p_team

        p_fused_cal = p_fused_raw
        if microseg_table:
            try:
                p_fused_cal = float(clip_prob(_apply_microseg_calibration(
                    p_fused_raw,
                    league=str(s.league),
                    split=str(s.split),
                    side=str(s.side or "blue"),
                    bo=str(s.bo_bucket or "1"),
                    phase=str(s.phase or "regular"),
                    table=microseg_table,
                    min_n=30,
                    strength=0.60,
                    cap_pp=8.0,
                    hierarchical=True,
                    hierarchy_decay=0.80,
                )))
            except Exception:
                p_fused_cal = p_fused_raw

        rows.append({
            "month": str(getattr(s, "month", "") or ""),
            "league": str(s.league),
            "y": int(s.y),
            "p_team": p_team,
            "p_cal": p_cal,
            "p_players": p_players,
            "p_fused_raw": p_fused_raw,
            "p_fused_cal": p_fused_cal,
        })

    df = pd.DataFrame(rows)

    # Fit Platt on training fused and apply OOF in hold
    train_p_fused = []
    train_y_fused = []
    for s in train_samples:
        pf = float(_fuse_probs_by_precision(
            p_team=float(s.p_team),
            p_players=float(s.p_players),
            n_team=float(s.n_team),
            n_players=float(s.n_players),
            team_scale=float(team_scale),
            players_scale=float(players_scale),
        ))
        if math.isfinite(pf):
            train_p_fused.append(pf)
            train_y_fused.append(int(s.y))

    platt_fused = None
    if len(train_p_fused) >= 100:
        try:
            platt_fused = fit_platt_from_raw_probs(train_y_fused, train_p_fused)
        except Exception:
            pass

    if platt_fused:
        df["p_fused_oof"] = df["p_fused_raw"].apply(
            lambda x: float(clip_prob(platt_fused.predict_proba(float(x)))) if math.isfinite(float(x)) else 0.5
        )
    else:
        df["p_fused_oof"] = df["p_fused_raw"]

    # ---- Compute metrics per layer -----------------------------------------
    y = df["y"].tolist()

    results = []
    layer_cols = [
        ("L0  Elo base",          "p_team"),
        ("L1  Elo + Platt cal",   "p_cal"),
        ("L2  + Players fusion",  "p_fused_raw"),
        ("L3  + Microseg cal",    "p_fused_cal"),
        ("L4  + OOF Platt fused", "p_fused_oof"),
    ]

    for name, col in layer_cols:
        p = df[col].tolist()
        results.append(_metrics_row(name, y, p))

    # ---- Per-league breakdown on best layer --------------------------------
    best_col = "p_fused_oof"
    league_rows = []
    for lg, gdf in df.groupby("league"):
        if len(gdf) < 30:
            continue
        ly = gdf["y"].tolist()
        lp_team = gdf["p_team"].tolist()
        lp_fused = gdf[best_col].tolist()
        ll_base = _safe_ll(ly, lp_team)
        ll_fused = _safe_ll(ly, lp_fused)
        delta = _delta(ll_base, ll_fused)
        league_rows.append({
            "league": str(lg),
            "n": len(ly),
            "logloss_base": ll_base,
            "logloss_fused": ll_fused,
            "delta_logloss_pp": round(float(delta * 100), 3) if delta is not None else None,
        })
    league_rows.sort(key=lambda r: abs(r.get("delta_logloss_pp") or 0), reverse=True)

    # ---- Print report -------------------------------------------------------
    print(f"\n{'='*60}")
    print("  RESULTADOS DA ABLATION STUDY")
    print(f"  Holdout: {len(hold_samples)} samples | {holdout_days} dias finais")
    print(f"{'='*60}")
    print(f"\n  {'Camada':<25} {'Logloss':>9} {'Melhora(pp)':>12} {'ECE':>8} {'Brier':>8}")
    print(f"  {'-'*68}")

    prev_ll = None
    for r in results:
        ll = r["logloss"]
        delta_pp = _delta(prev_ll, ll)
        ece = r["ece"]
        br = r["brier"]
        print(
            f"  {r['layer']:<25} {_fmt_metric(ll, 5):>9}"
            f" {_fmt_delta(delta_pp):>11}"
            f" {_fmt_metric(ece, 4):>8}"
            f" {_fmt_metric(br, 4):>8}"
        )
        prev_ll = ll

    print("\n  Nota: Melhora(pp) positivo = camada ajuda (logloss cai = melhor)")

    print("\n  Top ligas por impacto dos players (L0 vs L4):")
    print(f"  {'Liga':<15} {'N':>5} {'LL base':>9} {'LL fused':>9} {'Imp(pp)':>9}")
    print(f"  {'-'*52}")
    for r in league_rows[:10]:
        d_str = f"+{r['delta_logloss_pp']:.2f}" if (r['delta_logloss_pp'] or 0) >= 0 else f"{r['delta_logloss_pp']:.2f}"
        print(
            f"  {r['league']!s:<15} {r['n']:>5}"
            f" {_fmt_metric(r['logloss_base'], 4):>9}"
            f" {_fmt_metric(r['logloss_fused'], 4):>9}"
            f" {d_str:>9}"
        )

    # ---- Stage contribution summary ----------------------------------------
    print("\n  CONTRIBUICAO DE CADA CAMADA (logloss em pp):")
    labels = ["Players fusion", "Microseg cal", "OOF Platt fused"]
    pairs = [
        ("p_team",      "p_fused_raw"),
        ("p_fused_raw", "p_fused_cal"),
        ("p_fused_cal", "p_fused_oof"),
    ]
    for label, (c1, c2) in zip(labels, pairs):
        ll1 = _safe_ll(y, df[c1].tolist())
        ll2 = _safe_ll(y, df[c2].tolist())
        d = _delta(ll1, ll2)
        status = "[+] ajuda" if (d or 0) > 0.0001 else ("[=] neutro" if abs(d or 0) < 0.0001 else "[-] piora")
        print(f"    {label:<20}: {_fmt_delta(d):>10}  {status}")

    print(f"\n{'='*60}\n")

    # ---- Build output -------------------------------------------------------
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "holdout_n": len(hold_samples),
        "train_n": len(train_samples),
        "holdout_days": holdout_days,
        "layers": results,
        "by_league": league_rows,
        "stage_contributions": [
            {"stage": label, "delta_logloss_pp": round(float(_delta(_safe_ll(y, df[c1].tolist()), _safe_ll(y, df[c2].tolist())) * 100), 4) if _delta(_safe_ll(y, df[c1].tolist()), _safe_ll(y, df[c2].tolist())) is not None else None}
            for label, (c1, c2) in zip(labels, pairs)
        ],
    }
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--artifact", default="ml_artifact.json", help="Path to ml_artifact.json")
    ap.add_argument("--players-artifact", default="players_artifact.json", help="Path to players_artifact.json")
    ap.add_argument(
        "--csv",
        required=True,
        help="Path to OracleElixir CSV or directory (newest .csv used if directory)",
    )
    ap.add_argument("--params", default=None, help="Path to params_fitted.json (optional, enables microseg)")
    ap.add_argument("--holdout-days", type=int, default=180, help="Days to hold out for evaluation (default 180)")
    ap.add_argument("--team-scale", type=float, default=1.0)
    ap.add_argument("--players-scale", type=float, default=1.0)
    ap.add_argument("--output", default=None, help="Save JSON report to this path")
    args = ap.parse_args(argv)

    # Resolve CSV path
    csv_p = Path(str(args.csv)).expanduser()
    if csv_p.is_dir():
        cands = sorted(csv_p.glob("*.csv"), key=lambda x: x.stat().st_mtime, reverse=True)
        if not cands:
            print(f"[ERROR] No .csv files found in {csv_p}", file=sys.stderr)
            sys.exit(1)
        csv_paths = [str(cands[0])]
        print(f"[INFO] Using newest CSV in directory: {csv_paths[0]}")
    elif csv_p.exists():
        csv_paths = [str(csv_p)]
    else:
        print(f"[ERROR] CSV not found: {csv_p}", file=sys.stderr)
        sys.exit(1)

    report = run_ablation(
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
        out_path = Path(str(args.output)).expanduser()
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[INFO] Report saved to {out_path}")


if __name__ == "__main__":
    main()
