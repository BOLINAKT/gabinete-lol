"""Phase 9: cross-league calibration diagnostic + corrective shift table.

Goal: take the production p_map_pre for every game where blue and red teams
come from DIFFERENT macro regions (LCK/LPL/LEC/LCS/PCS/...) and check if
the model's calibration on those games is systematically off. If yes, fit
a small per-macro-pair Platt-style correction and validate via paired
bootstrap. ACCEPT the correction only when it provably improves logloss.

Cross-league games are rare per individual pair (MSI, Worlds, FST, EWC,
EU Masters), so we bucket by *macro pair* (e.g. "KR_vs_EMEA") and require
a minimum sample size before fitting any correction.
"""
from __future__ import annotations

import argparse
import json
import math
import random
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
from mlcore.tiers import canonical_league, tier_for_league
from mlcore.utils import clip_prob


# Bucket each league into a macro region for cross-league analysis
MACRO_REGION: Dict[str, str] = {
    "LCK": "KR", "LCKC": "KR",
    "LPL": "CN", "AL": "CN", "LDL": "CN",
    "LEC": "EMEA", "LFL": "EMEA", "PRM": "EMEA", "LVP SL": "EMEA",
    "NLC": "EMEA", "EM": "EMEA", "TCL": "EMEA", "EBL": "EMEA",
    "HM": "EMEA", "LES": "EMEA", "LPLOL": "EMEA", "ROL": "EMEA",
    "CCWS": "EMEA", "PRMP": "EMEA",
    "LCS": "AMERICAS", "AMERICAS": "AMERICAS", "CBLOL": "AMERICAS",
    "CBLOLA": "AMERICAS", "NACL": "AMERICAS",
    "PCS": "APAC", "VCS": "APAC", "LJL": "APAC", "LCP": "APAC",
    "LCO": "APAC",
    "MSI": "INTL", "WORLDS": "INTL", "FST": "INTL", "EWC": "INTL",
    "LLA": "AMERICAS", "LAS": "AMERICAS",
}


def macro_of(league: str) -> str:
    key = canonical_league(league)
    if key in MACRO_REGION:
        return MACRO_REGION[key]
    # Fallback via tier
    t = tier_for_league(key)
    if t in ("ERL",):
        return "EMEA"  # most ERLs are EMEA
    return "OTHER"


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


def _logloss(y, p):
    y = np.asarray(y, dtype=float)
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _brier(y, p):
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    return float(np.mean((y - p) ** 2))


def _ece(y, p, n_bins=10):
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    n = len(y)
    if n == 0:
        return 0.0
    bins = np.minimum(n_bins - 1, (p * n_bins).astype(int))
    ece = 0.0
    for b in range(n_bins):
        mask = bins == b
        if not mask.any():
            continue
        mp = float(p[mask].mean())
        ma = float(y[mask].mean())
        ece += (mask.sum() / n) * abs(mp - ma)
    return float(ece)


def _bootstrap_logloss_delta(y, pb, pc, n_bootstrap=500, seed=1337):
    rng = random.Random(int(seed))
    n = len(y)
    if n == 0:
        return float("nan"), float("nan"), float("nan"), 1.0
    y_arr = np.asarray(y, dtype=float)
    pb = np.clip(np.asarray(pb, dtype=float), 1e-6, 1 - 1e-6)
    pc = np.clip(np.asarray(pc, dtype=float), 1e-6, 1 - 1e-6)
    delta = _logloss(y_arr, pb) - _logloss(y_arr, pc)
    deltas = []
    for _ in range(n_bootstrap):
        idx = [rng.randrange(0, n) for _ in range(n)]
        deltas.append(_logloss(y_arr[idx], pb[idx]) - _logloss(y_arr[idx], pc[idx]))
    deltas.sort()
    nd = len(deltas)
    ci_lo = deltas[max(0, int(0.025 * nd))]
    ci_hi = deltas[min(nd - 1, int(0.975 * nd))]
    if delta >= 0:
        adverse = sum(1 for d in deltas if d <= 0)
    else:
        adverse = sum(1 for d in deltas if d >= 0)
    p_value = 2.0 * adverse / nd
    return float(delta), float(ci_lo), float(ci_hi), float(min(1.0, max(0.0, p_value)))


def _logit(p):
    p = max(1e-9, min(1.0 - 1e-9, float(p)))
    return math.log(p / (1.0 - p))


def _sigmoid(z):
    return 1.0 / (1.0 + math.exp(-float(z)))


def _fit_platt(y, p, l2=0.5):
    """Tiny Platt fit: minimize logloss over (a*logit(p)+b) on (y, p)."""
    if not y:
        return 1.0, 0.0
    a, b = 1.0, 0.0
    lr = 0.05
    for _ in range(400):
        ga = 0.0
        gb = 0.0
        for yi, pi in zip(y, p):
            zi = a * _logit(pi) + b
            qi = _sigmoid(zi)
            err = qi - yi
            ga += err * _logit(pi)
            gb += err
        n = len(y)
        a -= lr * (ga / n + l2 * (a - 1.0))
        b -= lr * (gb / n)
    return float(a), float(b)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--players-artifact", default="players_artifact.json")
    ap.add_argument("--csv-train", default="CSV_HISTORICO")
    ap.add_argument("--csv-current", default="CSV_DIARIO")
    ap.add_argument("--params", default="params_fitted.json")
    ap.add_argument("--val-cutoff", default="2026-03-31")
    ap.add_argument("--min-bucket-n", type=int, default=40)
    ap.add_argument("--n-bootstrap", type=int, default=500)
    ap.add_argument("--output", default="FASE9_CROSSLEAGUE.json")
    ap.add_argument("--save-calibration", default="cross_league_calibration.json")
    args = ap.parse_args()

    csv_paths = _gather_csvs([args.csv_train, args.csv_current])

    print(f"\n{'='*72}")
    print("  FASE 9 - Cross-league calibration diagnostic")
    print(f"{'='*72}\n")

    print("[1/4] Building production p_map_pre...")
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
    train_samples_24_25 = [s for s in samples if (str(getattr(s, "date_day", "") or "")[:4] in {"2024", "2025"})]
    train_p_fused_prod = []
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

    print(f"      Samples loaded: {len(samples)}")

    print("[2/4] Identifying cross-league games (via team -> domestic league)...")
    # Map each team to its domestic league per year (from team rows in CSVs)
    from mlcore.league_transfer_loader_core import infer_team_domestic_league_by_year, load_oracle_team_rows
    team_rows_all = load_oracle_team_rows(csv_paths)
    team_to_year_league = infer_team_domestic_league_by_year(team_rows_all)

    def _domestic_league(team: str, year: int) -> str:
        m = team_to_year_league.get(str(team or "")) or {}
        # Try exact year first, then nearest year present
        if year in m:
            return str(m[year])
        if m:
            closest_year = min(m.keys(), key=lambda y: abs(int(y) - int(year)))
            return str(m[closest_year])
        return ""

    g_idx = g.set_index("gameid")
    rows = []
    for s in samples:
        gid = str(getattr(s, "gameid", "") or "")
        if gid not in g_idx.index:
            continue
        row = g_idx.loc[gid]
        year_v = int(row.get("year", 2025) or 2025)
        blue_team = str(row.get("blue", "") or "")
        red_team = str(row.get("red", "") or "")
        if not blue_team or not red_team:
            continue
        league_blue = _domestic_league(blue_team, year_v)
        league_red = _domestic_league(red_team, year_v)
        if not league_blue or not league_red:
            continue
        macro_a = macro_of(league_blue)
        macro_b = macro_of(league_red)
        if macro_a == "OTHER" or macro_b == "OTHER":
            continue
        if macro_a == macro_b:
            continue  # same macro — skip
        # cross-league
        side_norm = str(getattr(s, "side", "blue") or "blue").strip().title()
        p_prod = _production_p_for_sample(s, microseg_table, platt_team, platt_fused)
        if side_norm == "Red":
            p_blue = float(1.0 - p_prod)
            y_blue = int(not bool(s.y))
        else:
            p_blue = float(p_prod)
            y_blue = int(s.y)
        pair = "_vs_".join(sorted([macro_a, macro_b]))
        rows.append({
            "gameid": gid,
            "pair": pair,
            "macro_blue": macro_a,
            "macro_red": macro_b,
            "league_blue": league_blue,
            "league_red": league_red,
            "p_blue": float(p_blue),
            "y_blue": int(y_blue),
            "date": getattr(s, "date_day", ""),
        })

    print(f"      Cross-league games: {len(rows)}")
    if not rows:
        print("      No cross-league games found; aborting.")
        return 0

    # Split train/val/test — cross-league events are rare, so split by quantile
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    n_total = len(df)
    # Reserve the last 25% chronologically as test, next 15% as val
    i_test = int(n_total * 0.75)
    i_val = int(n_total * 0.60)
    train_df = df.iloc[:i_val]
    val_df = df.iloc[i_val:i_test]
    test_df = df.iloc[i_test:]
    print(f"      Split (chronological 60/15/25): train={len(train_df)} val={len(val_df)} test={len(test_df)}")
    if len(test_df) > 0:
        print(f"      Train range: {train_df['date'].min().date()} - {train_df['date'].max().date()}")
        print(f"      Test  range: {test_df['date'].min().date()} - {test_df['date'].max().date()}")

    # Per-pair counts
    print("[3/4] Per-macro-pair diagnostics (TEST):")
    pair_counts = test_df["pair"].value_counts().to_dict()
    print(f"      {'pair':<28} {'n':>4}")
    for p, n in sorted(pair_counts.items(), key=lambda x: -x[1]):
        print(f"      {p:<28} {n:>4}")

    # Fit per-pair Platt correction on TRAIN+VAL with min n
    print(f"\n[4/4] Fitting per-pair calibration (min n={args.min_bucket_n} on train+val)...")
    fit_df = pd.concat([train_df, val_df], ignore_index=True)
    pair_calibration: Dict[str, Dict[str, float]] = {}
    for pair, g_pair in fit_df.groupby("pair"):
        n = len(g_pair)
        if n < args.min_bucket_n:
            continue
        ys = g_pair["y_blue"].tolist()
        ps = g_pair["p_blue"].tolist()
        a, b = _fit_platt(ys, ps)
        pair_calibration[pair] = {"a": float(a), "b": float(b), "n_fit": int(n)}

    # Also fit a GLOBAL cross-league Platt (single correction across all pairs)
    ys_all = fit_df["y_blue"].tolist()
    ps_all = fit_df["p_blue"].tolist()
    a_global, b_global = _fit_platt(ys_all, ps_all)
    print(f"      Global cross-league Platt: a={a_global:.4f} b={b_global:.4f} n_fit={len(fit_df)}")

    # Evaluate on TEST: baseline (no correction) vs candidate (with per-pair Platt)
    if len(test_df) == 0:
        print("      No test rows — cannot validate.")
        return 0

    y_test = test_df["y_blue"].astype(float).values
    p_baseline = test_df["p_blue"].astype(float).values
    p_candidate = []
    p_global_cand = []
    for _, r in test_df.iterrows():
        cal = pair_calibration.get(str(r["pair"]))
        if cal is None:
            p_candidate.append(float(r["p_blue"]))
        else:
            z = cal["a"] * _logit(float(r["p_blue"])) + cal["b"]
            p_candidate.append(float(_sigmoid(z)))
        # Global candidate
        zg = a_global * _logit(float(r["p_blue"])) + b_global
        p_global_cand.append(float(_sigmoid(zg)))
    p_candidate = np.array(p_candidate, dtype=float)
    p_global_cand = np.array(p_global_cand, dtype=float)

    ll_b = _logloss(y_test, p_baseline)
    ll_c = _logloss(y_test, p_candidate)
    ll_g = _logloss(y_test, p_global_cand)
    br_b = _brier(y_test, p_baseline)
    br_c = _brier(y_test, p_candidate)
    br_g = _brier(y_test, p_global_cand)
    ece_b = _ece(y_test, p_baseline)
    ece_c = _ece(y_test, p_candidate)
    ece_g = _ece(y_test, p_global_cand)
    delta_ll, ci_lo, ci_hi, pval = _bootstrap_logloss_delta(
        y_test.tolist(), p_baseline.tolist(), p_candidate.tolist(),
        n_bootstrap=int(args.n_bootstrap),
    )
    delta_ll_g, ci_lo_g, ci_hi_g, pval_g = _bootstrap_logloss_delta(
        y_test.tolist(), p_baseline.tolist(), p_global_cand.tolist(),
        n_bootstrap=int(args.n_bootstrap),
    )
    accept_pair = bool(delta_ll > 0.001 and pval < 0.05 and ci_lo > 0)
    accept_global = bool(delta_ll_g > 0.001 and pval_g < 0.05 and ci_lo_g > 0)

    sign = "+" if delta_ll >= 0 else ""
    sign_g = "+" if delta_ll_g >= 0 else ""
    print(f"\n  Baseline (no correction):    logloss={ll_b:.5f} brier={br_b:.5f} ece={ece_b:.5f}")
    print(f"  Candidate (per-pair Platt):  logloss={ll_c:.5f} brier={br_c:.5f} ece={ece_c:.5f}")
    print(f"  Candidate (global X-league): logloss={ll_g:.5f} brier={br_g:.5f} ece={ece_g:.5f}")
    print(f"  [{'ACCEPT' if accept_pair else 'REJECT'}] per-pair:  delta_logloss={sign}{delta_ll:.5f} "
          f"CI[{ci_lo:+.5f}, {ci_hi:+.5f}] p={pval:.4f}")
    print(f"  [{'ACCEPT' if accept_global else 'REJECT'}] global:    delta_logloss={sign_g}{delta_ll_g:.5f} "
          f"CI[{ci_lo_g:+.5f}, {ci_hi_g:+.5f}] p={pval_g:.4f}")

    out = {
        "version": "phase9_crossleague_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "val_cutoff": args.val_cutoff,
        "n_train": len(train_df), "n_val": len(val_df), "n_test": len(test_df),
        "pair_test_counts": pair_counts,
        "pair_calibration": pair_calibration,
        "global_calibration": {"a": float(a_global), "b": float(b_global), "n_fit": len(fit_df)},
        "baseline":  {"logloss": ll_b, "brier": br_b, "ece": ece_b},
        "per_pair":  {"logloss": ll_c, "brier": br_c, "ece": ece_c,
                      "delta_logloss": delta_ll, "ci_low": ci_lo, "ci_high": ci_hi,
                      "p_value": pval, "accept": accept_pair},
        "global":    {"logloss": ll_g, "brier": br_g, "ece": ece_g,
                      "delta_logloss": delta_ll_g, "ci_low": ci_lo_g, "ci_high": ci_hi_g,
                      "p_value": pval_g, "accept": accept_global},
    }
    Path(args.output).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n  Report -> {args.output}")
    # Save the best calibration that ACCEPTS (prefer global if accepts, else per-pair)
    chosen = None
    if accept_global:
        chosen = {"mode": "global", "global": {"a": float(a_global), "b": float(b_global)}}
        print(f"  Saving GLOBAL cross-league calibration -> {args.save_calibration}")
    elif accept_pair:
        chosen = {"mode": "per_pair", "pair_calibration": pair_calibration}
        print(f"  Saving PER-PAIR cross-league calibration -> {args.save_calibration}")
    if chosen:
        chosen.update({
            "version": "cross_league_calibration_v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "macro_region": MACRO_REGION,
        })
        Path(args.save_calibration).write_text(json.dumps(chosen, indent=2), encoding="utf-8")
    else:
        print("  (No calibration saved -- both gates REJECTED)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
