"""Phase 6: Validate live state-to-win models through the acceptance gate.

Trains 4 LightGBM models (one per snapshot @10/@15/@20/@25 minutes) on
historical games where we know the final outcome and the actual game state
at each snapshot. The "baseline" for the gate is the pre-game prediction
(p_map_pre); the "candidate" is the live-adjusted prediction.

The gate is evaluated on the TEST holdout for each snapshot independently.

Usage
-----
    python tools/run_phase6_live_gate.py --val-cutoff 2026-03-31 --output FASE6_LIVE.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

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

from mlcore.ml_eval import acceptance_gate, build_split, metrics_with_ci
from mlcore.live_ml import SNAPSHOT_MINUTES, StateToWinModel, build_snapshot_features


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _gather_csvs(paths):
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
    """Load Oracle's Elixir team-level rows (participantid 100 or 200)."""
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
    """Compute production p_map for a sample (this is the p_map_pre)."""
    p_t_ms = _apply_ms(float(s.p_team), s, microseg_table)
    p_t_cal = float(clip_prob(platt_team.predict_proba(p_t_ms)))
    p_fused = float(clip_prob(_fuse_probs_by_precision(
        p_team=p_t_cal, p_players=float(s.p_players),
        n_team=float(s.n_team), n_players=float(s.n_players),
        team_scale=1.0, players_scale=1.0,
    )))
    p_fused_ms = _apply_ms(p_fused, s, microseg_table)
    return float(clip_prob(platt_fused.predict_proba(p_fused_ms)))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--players-artifact", default="players_artifact.json")
    ap.add_argument("--csv-train", default="CSV_HISTORICO")
    ap.add_argument("--csv-current", default="CSV_DIARIO")
    ap.add_argument("--params", default="params_fitted.json")
    ap.add_argument("--val-cutoff", default="2026-03-31")
    ap.add_argument("--n-bootstrap", type=int, default=1000)
    ap.add_argument("--output", default="FASE6_LIVE.json")
    ap.add_argument("--save-models-dir", default=None,
                    help="If set, save trained models to this directory (one subdir per minute)")
    args = ap.parse_args()

    csv_paths = _gather_csvs([args.csv_train, args.csv_current])
    train_years = (2024, 2025)
    val_year = 2026

    print(f"\n{'='*72}")
    print("  FASE 6 GATE - Live State-to-Win models")
    print(f"{'='*72}\n")

    # ---- Load and build base p_map_pre for all games ----
    print("[1/4] Loading data and building production baseline (p_map_pre)...")
    g = _load_games_multi(csv_paths)
    art = MLArtifact.load_json(args.artifact)
    p_art = PlayersArtifact.load_json(args.players_artifact)
    w_lineup = float((((art.meta or {}).get("players_layer") or {}).get("w_lineup") or 0.85))
    gameids_set = set(g["gameid"].astype(str).tolist())
    pr = load_match_player_rows(csv_paths, keep_playoffs=None, gameids=gameids_set)
    lineup_cache = _build_lineup_cache(pr)
    samples = _make_samples(art=art, p_art=p_art, games=g, lineup_cache=lineup_cache, w_lineup=w_lineup)
    split = build_split(samples, train_years=train_years, val_year=val_year, val_cutoff=args.val_cutoff)
    summary = split.summary()
    print(f"      Samples: Train={summary['train']['n']}, Val={summary['val']['n']}, Test={summary['test']['n']}")

    microseg_table = (_read_json_file_safe(Path(args.params)).get("microseg_calibration") or {}).get("table") or {}
    train_y = [int(s.y) for s in split.train.samples]
    train_p_team_ms = [_apply_ms(float(s.p_team), s, microseg_table) for s in split.train.samples]
    platt_team = fit_platt_from_raw_probs(train_y, train_p_team_ms)
    train_p_fused_prod = []
    for s, p_t_ms in zip(split.train.samples, train_p_team_ms):
        p_t_cal = float(clip_prob(platt_team.predict_proba(p_t_ms)))
        pf = float(clip_prob(_fuse_probs_by_precision(
            p_team=p_t_cal, p_players=float(s.p_players),
            n_team=float(s.n_team), n_players=float(s.n_players),
            team_scale=1.0, players_scale=1.0,
        )))
        train_p_fused_prod.append(pf)
    train_p_fused_ms = [_apply_ms(p, s, microseg_table) for p, s in zip(train_p_fused_prod, split.train.samples)]
    platt_fused = fit_platt_from_raw_probs(train_y, train_p_fused_ms)

    # Build dict (gameid, side) -> p_map_pre using each sample's perspective
    p_map_pre_by_gs: Dict[Tuple[str, str], float] = {}
    for sample_bucket in (split.train.samples, split.val.samples, split.test.samples):
        for s in sample_bucket:
            gid = str(getattr(s, "gameid", "") or "")
            sample_side = str(getattr(s, "side", "blue") or "blue").strip().title()
            p = _production_p_for_sample(s, microseg_table, platt_team, platt_fused)
            p_map_pre_by_gs[(gid, sample_side)] = float(p)
            # also fill the opposite side
            opp_side = "Red" if sample_side == "Blue" else "Blue"
            p_map_pre_by_gs[(gid, opp_side)] = float(1.0 - p)
    print(f"      p_map_pre filled for {len(p_map_pre_by_gs)} (gameid, side) entries")

    # ---- Load team rows for snapshot features ----
    print("[2/4] Loading team rows for snapshot features...")
    team_rows = _load_team_rows(csv_paths)
    print(f"      Team rows: {len(team_rows)}")
    train_max = pd.Timestamp(f"{val_year}-01-01")
    val_max = pd.Timestamp(args.val_cutoff)

    # ---- For each snapshot minute, build features + train + gate ----
    print(f"[3/4] Training one model per snapshot minute: {SNAPSHOT_MINUTES}\n")
    snapshot_results = []

    for minute in SNAPSHOT_MINUTES:
        print(f"  === Snapshot @ {minute} min ===")
        all_snaps = build_snapshot_features(
            team_rows, minute=minute,
            p_map_pre_by_gameid_side=p_map_pre_by_gs,
            require_complete=True,
        )
        # Split by date
        # Need to look up date for each gameid
        date_by_gid = team_rows.set_index("gameid")["date"].to_dict()
        train_snaps, val_snaps, test_snaps = [], [], []
        for s in all_snaps:
            d = date_by_gid.get(s.gameid)
            if d is None or pd.isna(d):
                continue
            if d < train_max:
                train_snaps.append(s)
            elif d <= val_max:
                val_snaps.append(s)
            else:
                test_snaps.append(s)
        print(f"      Snapshots: train={len(train_snaps)}, val={len(val_snaps)}, test={len(test_snaps)}")
        if len(test_snaps) < 100:
            print(f"      [SKIP] Insufficient test snapshots ({len(test_snaps)} < 100)")
            snapshot_results.append({
                "minute": minute,
                "n_train": len(train_snaps), "n_val": len(val_snaps), "n_test": len(test_snaps),
                "skipped": True, "reason": "insufficient_test",
            })
            continue
        if len(train_snaps) < 500:
            print(f"      [SKIP] Insufficient train snapshots ({len(train_snaps)} < 500)")
            snapshot_results.append({
                "minute": minute,
                "n_train": len(train_snaps), "n_val": len(val_snaps), "n_test": len(test_snaps),
                "skipped": True, "reason": "insufficient_train",
            })
            continue

        # Train model
        model = StateToWinModel(minute=minute)
        model.fit(train_snaps, val_snaps)

        # Save model if requested (PER-MINUTE subdirectory)
        if args.save_models_dir:
            model_dir = Path(args.save_models_dir) / f"minute_{minute:02d}"
            model.save(model_dir)
            print(f"      [SAVED] Model -> {model_dir}")

        # Predict on test
        y_test = np.array([s.y for s in test_snaps])
        p_baseline = np.array([s.p_pre for s in test_snaps])  # the gate baseline = p_map_pre alone
        p_candidate = model.predict_proba(test_snaps)         # state-aware prediction

        base_m = metrics_with_ci(y_test.tolist(), p_baseline.tolist(), n_bootstrap=int(args.n_bootstrap))
        cand_m = metrics_with_ci(y_test.tolist(), p_candidate.tolist(), n_bootstrap=int(args.n_bootstrap))
        gate = acceptance_gate(y_test.tolist(), p_baseline.tolist(), p_candidate.tolist(),
                               n_bootstrap=int(args.n_bootstrap))

        print(f"      Baseline (p_map_pre only) logloss: {base_m['logloss'].point:.5f}")
        print(f"      Candidate (state-aware)   logloss: {cand_m['logloss'].point:.5f}")
        print(f"      {gate.summary_line()}")

        # Top 5 features by importance
        imp_sorted = sorted(model.train_metadata.get("feature_importance", {}).items(),
                            key=lambda x: x[1], reverse=True)[:5]
        print(f"      Top features: {[(k, round(v, 1)) for k, v in imp_sorted]}\n")

        snapshot_results.append({
            "minute": minute,
            "n_train": len(train_snaps), "n_val": len(val_snaps), "n_test": len(test_snaps),
            "best_iteration": int(model.best_iteration),
            "baseline_metrics": {"logloss": base_m["logloss"].as_dict(), "ece": base_m["ece"].as_dict()},
            "candidate_metrics": {"logloss": cand_m["logloss"].as_dict(), "ece": cand_m["ece"].as_dict()},
            "gate_decision": gate.as_dict(),
            "feature_importance": dict(imp_sorted),
        })

    # ---- Summary ----
    print("[4/4] Summary\n")
    print(f"  {'Minute':>6} {'n_test':>7} {'Melhora':>10} {'p-value':>9} {'Gate':>8}")
    print(f"  {'-'*52}")
    for r in snapshot_results:
        if r.get("skipped"):
            print(f"  {r['minute']:>6} {r['n_test']:>7} {'SKIPPED':>10} {'-':>9} {'-':>8}")
            continue
        g = r["gate_decision"]
        gate_str = "ACCEPT" if g["accept"] else "REJECT"
        print(f"  {r['minute']:>6} {r['n_test']:>7} {g['delta_logloss']*100:>+8.3f}pp {g['p_value']:>9.4f} {gate_str:>8}")

    print(f"\n{'='*72}\n")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": "phase6_live_v1",
        "split": summary,
        "snapshots": snapshot_results,
    }
    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[INFO] Report saved to {args.output}")


if __name__ == "__main__":
    main()
