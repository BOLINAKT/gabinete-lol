"""Establish the Phase 0 baseline for ML quality.

Computes the CURRENT state of the pipeline on the chronological holdout
(train: 2024+2025, val: 2026 H1, test: 2026 H2) with bootstrap CIs.

This is the rigorous baseline against which all subsequent improvements
(Fase 1+) will be measured.

Usage
-----
    python tools/run_baseline_phase0.py \\
        --artifact ml_artifact.json \\
        --players-artifact players_artifact.json \\
        --csv-train CSV_HISTORICO \\
        --csv-current CSV_DIARIO \\
        --params params_fitted.json \\
        --val-cutoff 2026-06-30 \\
        --output FASE0_BASELINE.json
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
from mlcore.calibration_diagnostics import _apply_microseg_calibration, _read_json_file_safe
from mlcore.fit_ml_params import _build_lineup_cache, _fuse_probs_by_precision, _make_samples
from mlcore.io_oracle import load_oracle_elixir_games
from mlcore.players_layer import PlayersArtifact, load_match_player_rows
from mlcore.utils import clip_prob

from mlcore.ml_eval import build_split, metrics_with_ci


def _gather_csvs(paths: List[str]) -> List[str]:
    out: List[str] = []
    for p in paths:
        pp = Path(p).expanduser()
        if pp.is_dir():
            for f in sorted(pp.glob("*.csv")):
                out.append(str(f))
        elif pp.exists():
            out.append(str(pp))
    return out


def _load_games_multi(csv_paths: List[str]) -> pd.DataFrame:
    chunks: List[pd.DataFrame] = []
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


def _apply_microseg(p, s, table):
    if not table:
        return float(p)
    try:
        return float(clip_prob(_apply_microseg_calibration(
            float(p),
            league=str(s.league),
            split=str(getattr(s, "split", "") or ""),
            side=str(getattr(s, "side", "blue") or "blue"),
            bo=str(getattr(s, "bo_bucket", "1") or "1"),
            phase=str(getattr(s, "phase", "regular") or "regular"),
            table=table,
            min_n=30, strength=0.60, cap_pp=8.0,
            hierarchical=True, hierarchy_decay=0.80,
        )))
    except Exception:
        return float(p)


def run_baseline(
    *,
    artifact_path: str,
    players_artifact_path: str,
    csv_paths: List[str],
    params_fitted_path: Optional[str],
    val_cutoff: str = "2026-06-30",
    train_years: tuple = (2024, 2025),
    val_year: int = 2026,
    n_bootstrap: int = 1000,
) -> Dict[str, Any]:
    print(f"\n{'='*72}")
    print("  FASE 0 BASELINE - estado atual do pipeline ML")
    print(f"{'='*72}\n")

    print("[1/5] Loading CSVs and artifacts...")
    g = _load_games_multi(csv_paths)
    if g.empty:
        return {"error": "no_games"}
    print(f"      Total games loaded: {len(g)}")

    art = MLArtifact.load_json(str(artifact_path))
    p_art = PlayersArtifact.load_json(str(players_artifact_path))
    w_lineup = float((((art.meta or {}).get("players_layer") or {}).get("w_lineup") or 0.85))

    print("[2/5] Building samples...")
    gameids = set(g["gameid"].astype(str).tolist())
    pr = load_match_player_rows(csv_paths, keep_playoffs=None, gameids=gameids)
    lineup_cache = _build_lineup_cache(pr)
    samples = _make_samples(art=art, p_art=p_art, games=g, lineup_cache=lineup_cache, w_lineup=w_lineup)
    if not samples:
        return {"error": "no_samples"}
    print(f"      Samples built: {len(samples)}")

    print(f"[3/5] Building chronological split (train={train_years}, val_year={val_year}, cutoff={val_cutoff})...")
    split = build_split(samples, train_years=train_years, val_year=val_year, val_cutoff=val_cutoff)
    summary = split.summary()
    print(f"      Train: {summary['train']['n']} samples  [{summary['train']['date_range']}]")
    print(f"      Val:   {summary['val']['n']} samples  [{summary['val']['date_range']}]")
    print(f"      Test:  {summary['test']['n']} samples  [{summary['test']['date_range']}]")

    if split.test.n < 100:
        return {"error": f"test set too small: {split.test.n} samples"}

    # Load microseg table
    microseg_table: Dict[str, Any] = {}
    if params_fitted_path:
        prm = _read_json_file_safe(Path(params_fitted_path))
        ms = prm.get("microseg_calibration") or {}
        microseg_table = ms.get("table") or {}
    print(f"      Microseg table: {len(microseg_table)} segments")

    print("[4/5] Fitting Platt on TRAIN fused probabilities...")
    train_p, train_y = [], []
    for s in split.train.samples:
        pf = float(_fuse_probs_by_precision(
            p_team=float(s.p_team), p_players=float(s.p_players),
            n_team=float(s.n_team), n_players=float(s.n_players),
            team_scale=1.0, players_scale=1.0,
        ))
        if math.isfinite(pf):
            train_p.append(pf)
            train_y.append(int(s.y))
    if len(train_p) < 100:
        return {"error": f"train set too small for Platt fit: {len(train_p)}"}
    platt = fit_platt_from_raw_probs(train_y, train_p)
    print(f"      Platt fit on {len(train_p)} training samples")

    print("[5/5] Computing baseline probabilities on TEST set...")

    # Compute multiple intermediate probabilities for diagnostics
    test_samples = split.test.samples
    y_test = [int(s.y) for s in test_samples]

    # L0: p_team only
    p_team = [float(clip_prob(s.p_team)) for s in test_samples]

    # L1: p_fused_raw (team + players, no calibration)
    p_fused_raw = []
    for s in test_samples:
        pf = float(clip_prob(_fuse_probs_by_precision(
            p_team=float(s.p_team), p_players=float(s.p_players),
            n_team=float(s.n_team), n_players=float(s.n_players),
            team_scale=1.0, players_scale=1.0,
        )))
        p_fused_raw.append(pf)

    # L2: p_fused + Platt
    p_fused_platt = [float(clip_prob(platt.predict_proba(p))) for p in p_fused_raw]

    # L3: p_fused + Microseg (current production simulation)
    # Production applies microseg on p_team BEFORE fusion, but our diagnostics
    # simplify by applying after; this is the closest we can get without rebuilding
    # the whole pipeline.
    p_fused_microseg = [_apply_microseg(p, s, microseg_table) for p, s in zip(p_fused_raw, test_samples)]

    # L4: p_fused + Microseg + Platt (training pipeline output)
    p_final = [float(clip_prob(platt.predict_proba(p))) for p in p_fused_microseg]

    print(f"      Computing bootstrap CIs (n_bootstrap={n_bootstrap})...")

    layers = [
        ("L0_p_team_only", p_team),
        ("L1_fused_raw", p_fused_raw),
        ("L2_fused_platt", p_fused_platt),
        ("L3_fused_microseg", p_fused_microseg),
        ("L4_final_microseg_platt", p_final),
    ]

    layer_metrics: List[Dict[str, Any]] = []
    print(f"\n  {'Layer':<28} {'logloss [CI]':>32} {'ECE':>20}")
    print(f"  {'-'*84}")
    for name, p in layers:
        m = metrics_with_ci(y_test, p, n_bootstrap=n_bootstrap)
        if "error" in m:
            print(f"  {name:<28} ERROR: {m['error']}")
            continue
        ll = m["logloss"]
        ec = m["ece"]
        br = m["brier"]
        ll_str = f"{ll.point:.5f} [{ll.ci_low:.5f}, {ll.ci_high:.5f}]"
        ec_str = f"{ec.point:.4f}"
        layer_metrics.append({
            "layer": name,
            "logloss": ll.as_dict(),
            "ece": ec.as_dict(),
            "brier": br.as_dict(),
        })
        print(f"  {name:<28} {ll_str:>32} {ec_str:>20}")

    # Per-league breakdown on the final layer
    print("\n  PER-LEAGUE BREAKDOWN (L4 final):")
    print(f"  {'League':<12} {'n':>5} {'logloss':>9} {'ECE':>7}")
    print(f"  {'-'*45}")
    league_results = []
    df_test = pd.DataFrame({"league": [str(s.league) for s in test_samples], "y": y_test, "p": p_final})
    for lg, gdf in df_test.groupby("league"):
        if len(gdf) < 20:
            continue
        m = metrics_with_ci(gdf["y"].tolist(), gdf["p"].tolist(), n_bootstrap=200)
        if "error" in m:
            continue
        league_results.append({
            "league": str(lg), "n": len(gdf),
            "logloss": m["logloss"].as_dict(),
            "ece": m["ece"].as_dict(),
        })
    league_results.sort(key=lambda r: r["n"], reverse=True)
    for r in league_results[:15]:
        print(f"  {r['league']:<12} {r['n']:>5} {r['logloss']['point']:>9.5f} {r['ece']['point']:>7.4f}")

    print(f"\n{'='*72}\n")

    # Identify the production-equivalent layer
    production_layer = "L4_final_microseg_platt"
    production_ll = next((m["logloss"]["point"] for m in layer_metrics if m["layer"] == production_layer), None)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": "phase0_baseline_v1",
        "split": summary,
        "n_bootstrap": int(n_bootstrap),
        "layers": layer_metrics,
        "by_league": league_results,
        "production_layer": production_layer,
        "production_logloss": production_ll,
        "config": {
            "artifact_path": str(artifact_path),
            "players_artifact_path": str(players_artifact_path),
            "csv_paths": list(csv_paths),
            "params_fitted_path": str(params_fitted_path or ""),
            "val_cutoff": str(val_cutoff),
            "train_years": list(train_years),
            "val_year": int(val_year),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--players-artifact", default="players_artifact.json")
    ap.add_argument("--csv-train", default="CSV_HISTORICO", help="Path or dir for historical training CSVs")
    ap.add_argument("--csv-current", default="CSV_DIARIO", help="Path or dir for current-season CSV")
    ap.add_argument("--params", default="params_fitted.json")
    ap.add_argument("--val-cutoff", default="2026-06-30")
    ap.add_argument("--n-bootstrap", type=int, default=1000)
    ap.add_argument("--output", default="FASE0_BASELINE.json")
    args = ap.parse_args()

    csv_paths = _gather_csvs([args.csv_train, args.csv_current])
    print(f"[INFO] CSV paths: {csv_paths}")

    report = run_baseline(
        artifact_path=args.artifact,
        players_artifact_path=args.players_artifact,
        csv_paths=csv_paths,
        params_fitted_path=args.params,
        val_cutoff=args.val_cutoff,
        n_bootstrap=int(args.n_bootstrap),
    )
    if "error" in report:
        print(f"[ERROR] {report['error']}", file=sys.stderr)
        sys.exit(1)

    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[INFO] Baseline saved to {args.output}")


if __name__ == "__main__":
    main()
