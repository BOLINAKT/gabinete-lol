from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.meta_blend_core import (
    apply_meta_blend_c_lite,
    apply_meta_blend_c_model,
    should_apply_meta_blend_c_model_gate,
)
from app_core.state_strength_core import compute_state_shadow_alite
from app_core.style_matchup_core import (
    apply_style_matchup_b_lite,
    apply_style_matchup_b_model,
    should_apply_style_matchup_b_model_gate,
)
from mlcore.artifact import MLArtifact
from mlcore.bo import prob_win_series
from mlcore.fit_ml_params import (
    _build_lineup_cache,
    _fuse_probs_by_precision,
    _load_style_team_games,
    _make_samples,
    _meta_recent_evidence_from_sample,
    _sym_team_probs,
    Sample,
)
from mlcore.io_oracle import load_oracle_elixir_games
from mlcore.lines_engine import Filters as LineFilters, build_profile
from mlcore.players_layer import PlayersArtifact, load_match_player_rows
from mlcore.utils import brier, clip_prob, logloss


def _default_csv_paths(root: Path) -> List[str]:
    paths: List[Path] = []
    hist = root / "CSV_HISTORICO"
    daily = root / "CSV_DIARIO"
    if hist.exists():
        paths.extend(sorted([p for p in hist.glob("*.csv") if p.is_file()]))
    if daily.exists():
        paths.extend(sorted([p for p in daily.glob("*.csv") if p.is_file()]))
    return [str(p) for p in paths]


def _concat_non_empty_frames(parts: List[pd.DataFrame]) -> pd.DataFrame:
    clean: List[pd.DataFrame] = []
    for d in parts:
        if d is None or d.empty:
            continue
        # Avoid pandas FutureWarning during concat when some sources carry all-NA optional columns.
        dd = d.dropna(axis=1, how="all")
        if dd is None or dd.empty:
            continue
        clean.append(dd)
    if not clean:
        return pd.DataFrame()
    return pd.concat(clean, ignore_index=True, sort=False)


def _load_params(p: Path) -> Dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _pick_scales_and_form_cfg(params: Dict[str, Any]) -> Tuple[float, float, Dict[str, Any]]:
    best_combined = params.get("best_combined") if isinstance(params.get("best_combined"), dict) else {}
    best = params.get("best") if isinstance(params.get("best"), dict) else {}
    best_form = params.get("best_form") if isinstance(params.get("best_form"), dict) else {}

    team_scale = float((best_combined or {}).get("team_scale", (best or {}).get("team_scale", 1.0)) or 1.0)
    players_scale = float((best_combined or {}).get("players_scale", (best or {}).get("players_scale", 1.0)) or 1.0)
    form_settings = (best_combined or {}).get("form_settings") or (best_form or {}).get("settings") or {}
    form_enabled = bool((best_combined or {}).get("form_enabled", (best_form or {}).get("enabled", False)))
    cfg = {
        "enabled": bool(form_enabled),
        "max_weight": float(form_settings.get("ml_form_blend_max_weight", (best_form or {}).get("max_weight", 0.75)) or 0.75),
        "knee_games": float(form_settings.get("ml_form_blend_knee_games", (best_form or {}).get("knee_games", 6.0)) or 6.0),
        "beta_prior": float(form_settings.get("ml_form_blend_beta", (best_form or {}).get("beta_prior", 2.0)) or 2.0),
        "signal_power": float(form_settings.get("ml_form_blend_signal_power", (best_form or {}).get("signal_power", 1.0)) or 1.0),
        "elite_same_league_parity_strength": float(
            form_settings.get("ml_form_blend_parity_strength", (best_form or {}).get("elite_same_league_parity_strength", 0.35))
            or 0.35
        ),
    }
    return team_scale, players_scale, cfg


def _safe_prob(x: Any, default: float = 0.5) -> float:
    try:
        v = float(x)
        return float(clip_prob(v)) if math.isfinite(v) else float(default)
    except Exception:
        return float(default)


def _form_blend_trace(sample: Sample, p_model: float, form_cfg: Dict[str, Any]) -> Dict[str, Any]:
    pm = _safe_prob(p_model)
    out: Dict[str, Any] = {
        "applied": False,
        "reason": "",
        "p_model": float(pm),
        "p_form": None,
        "p_blended": float(pm),
        "w_form": 0.0,
        "n_a": int(sample.form_n_a),
        "n_b": int(sample.form_n_b),
        "wins_a": int(sample.form_wins_a),
        "wins_b": int(sample.form_wins_b),
    }
    if not bool((form_cfg or {}).get("enabled", False)):
        out["reason"] = "disabled"
        return out
    n_a = int(max(0, int(sample.form_n_a)))
    n_b = int(max(0, int(sample.form_n_b)))
    if n_a <= 0 or n_b <= 0:
        out["reason"] = "insufficient_form_games"
        return out

    wins_a = int(max(0, int(sample.form_wins_a)))
    wins_b = int(max(0, int(sample.form_wins_b)))
    bp = max(0.5, float((form_cfg or {}).get("beta_prior", 2.0)))
    p_a = float(clip_prob((float(wins_a) + bp) / (float(n_a) + 2.0 * bp)))
    p_b = float(clip_prob((float(wins_b) + bp) / (float(n_b) + 2.0 * bp)))
    logit_diff = math.log(p_a / (1.0 - p_a)) - math.log(p_b / (1.0 - p_b))
    if bool(sample.same_league):
        p_weak = min(float(p_a), float(p_b))
        if p_weak >= 0.60:
            parity_signal = max(0.0, min(1.0, (p_weak - 0.60) / 0.25))
            parity_strength = max(0.0, min(0.80, float((form_cfg or {}).get("elite_same_league_parity_strength", 0.35))))
            logit_diff = float(logit_diff) * float(1.0 - (parity_strength * parity_signal))
    p_form = float(1.0 / (1.0 + math.exp(-logit_diff)))
    n_min = float(min(n_a, n_b))
    knee = max(1.0, float((form_cfg or {}).get("knee_games", 6.0)))
    sample_factor = n_min / (n_min + knee)
    sig = abs(p_form - 0.5) / 0.5
    sig = max(0.0, min(1.0, sig))
    sp = max(0.1, float((form_cfg or {}).get("signal_power", 1.0)))
    signal_factor = sig ** sp
    w_cap = max(0.0, min(0.95, float((form_cfg or {}).get("max_weight", 0.75))))
    w_form = max(0.0, min(0.95, float(w_cap * sample_factor * signal_factor)))
    p_blended = float(clip_prob((1.0 - w_form) * pm + w_form * p_form))
    out.update(
        {
            "applied": True,
            "reason": "season_form_blend",
            "p_form": float(p_form),
            "p_blended": float(p_blended),
            "w_form": float(w_form),
        }
    )
    return out


def _sample_roster_changed(sample: Sample) -> bool:
    lane_mag = (
        abs(float(sample.lane_top))
        + abs(float(sample.lane_jungle))
        + abs(float(sample.lane_mid))
        + abs(float(sample.lane_bot))
        + abs(float(sample.lane_support))
    )
    return bool(float(sample.n_players) > 0.0 and lane_mag > 0.25)


def _patch_status_sequence(games: pd.DataFrame) -> List[Tuple[str, float]]:
    out: List[Tuple[str, float]] = []
    state: Dict[str, Dict[str, Any]] = {}
    for _, g in games.iterrows():
        league = str(g.get("league") or "").strip()
        patch_raw = str(g.get("patch") or "").strip()
        ps = state.get(league, {"patch": "", "count": 0})
        if patch_raw and str(ps.get("patch") or "") != patch_raw:
            status = "changed"
            ps = {"patch": patch_raw, "count": 0}
        else:
            cnt = int(ps.get("count", 0) or 0)
            status = "refit_needed" if cnt < 12 else ""
        cnt2 = int(ps.get("count", 0) or 0) + 1
        ps["count"] = cnt2
        state[league] = ps
        if status == "changed":
            shrink = 0.65
        elif status == "refit_needed":
            # decay the refit pressure as patch accumulates games
            shrink = max(0.20, 0.55 - 0.03 * max(0, cnt2 - 1))
        else:
            shrink = 0.0
        out.append((status, float(max(0.0, min(0.95, shrink)))))
    return out


def _build_ml_info_for_sample(art: MLArtifact, sample: Sample) -> Dict[str, Any]:
    model = getattr(art, "model", None)
    shrink_fn = getattr(model, "_shrink_factor", None) if model is not None else None

    n_b = int(max(0, int(sample.form_n_a)))
    n_r = int(max(0, int(sample.form_n_b)))
    try:
        sf_b = float(shrink_fn(n_b)) if callable(shrink_fn) else (1.0 if n_b > 0 else 0.0)
    except Exception:
        sf_b = 1.0 if n_b > 0 else 0.0
    try:
        sf_r = float(shrink_fn(n_r)) if callable(shrink_fn) else (1.0 if n_r > 0 else 0.0)
    except Exception:
        sf_r = 1.0 if n_r > 0 else 0.0
    sf_b = float(max(0.0, min(1.0, sf_b)))
    sf_r = float(max(0.0, min(1.0, sf_r)))

    return {
        "p_cal": float(_safe_prob(sample.p_team)),
        "blue": {
            "team": str(sample.blue_team),
            "league": str(sample.league),
            "games_played": int(n_b),
            "shrink_factor": float(sf_b),
        },
        "red": {
            "team": str(sample.red_team),
            "league": str(sample.league),
            "games_played": int(n_r),
            "shrink_factor": float(sf_r),
        },
    }


def _metrics(rows: List[Dict[str, Any]], key: str) -> Dict[str, Any]:
    ys = [int(r["y"]) for r in rows if r.get(key) is not None]
    ps = [float(r[key]) for r in rows if r.get(key) is not None]
    if not ys:
        return {"n": 0, "logloss": None, "brier": None}
    return {"n": len(ys), "logloss": float(logloss(ys, ps)), "brier": float(brier(ys, ps))}


_FAV_ODD_BINS: List[Tuple[float, float]] = [
    (1.00, 1.15),
    (1.15, 1.30),
    (1.30, 1.50),
    (1.50, 1.75),
    (1.75, 2.10),
    (2.10, 3.00),
]


def _band_label(lo: float, hi: float) -> str:
    return f"{lo:.2f}-{hi:.2f}"


def _favorite_side_view(row: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    try:
        p = float(row.get(key))
    except Exception:
        return None
    if not math.isfinite(p):
        return None
    p = float(clip_prob(p))
    y = int(row.get("y", 0))
    fav_blue = bool(p >= 0.5)
    p_fav = float(max(p, 1.0 - p))
    y_fav = int(y if fav_blue else (1 - y))
    odd_fav = float(1.0 / max(1e-9, p_fav))
    return {
        "p_fav": p_fav,
        "odd_fav": odd_fav,
        "y_fav": y_fav,
        "fav_blue": fav_blue,
    }


def _metrics_fav_view(items: List[Dict[str, Any]], p_key: str = "p_fav") -> Dict[str, Any]:
    ys = [int(x["y_fav"]) for x in items if x.get("y_fav") is not None]
    ps = [float(x[p_key]) for x in items if x.get(p_key) is not None]
    if not ys:
        return {"n": 0, "logloss": None, "brier": None, "winrate_actual": None, "p_mean": None, "odd_mean": None}
    odds = [float(x.get("odd_fav")) for x in items if x.get("odd_fav") is not None]
    return {
        "n": len(ys),
        "logloss": float(logloss(ys, ps)),
        "brier": float(brier(ys, ps)),
        "winrate_actual": float(sum(ys) / max(1, len(ys))),
        "p_mean": float(sum(ps) / max(1, len(ps))),
        "odd_mean": float(sum(odds) / max(1, len(odds))) if odds else None,
    }


def _odd_band_monitor(rows: List[Dict[str, Any]], key: str) -> Dict[str, Any]:
    fav_items: List[Dict[str, Any]] = []
    for r in rows:
        fv = _favorite_side_view(r, key)
        if fv is None:
            continue
        fav_items.append(fv)
    if not fav_items:
        return {"rows": 0, "bands": {}}
    bands: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for it in fav_items:
        odd = float(it["odd_fav"])
        placed = False
        for lo, hi in _FAV_ODD_BINS:
            if (odd >= lo) and (odd < hi):
                bands[_band_label(lo, hi)].append(it)
                placed = True
                break
        if not placed:
            if odd < _FAV_ODD_BINS[0][0]:
                bands[f"<{_FAV_ODD_BINS[0][0]:.2f}"].append(it)
            else:
                bands[f">={_FAV_ODD_BINS[-1][1]:.2f}"].append(it)
    out_bands: Dict[str, Any] = {}
    for label in sorted(bands.keys(), key=lambda s: (s.startswith(">="), s.startswith("<"), s)):
        m = _metrics_fav_view(bands[label])
        m["calibration_gap_pp"] = (
            float((m["winrate_actual"] - m["p_mean"]) * 100.0)
            if m.get("winrate_actual") is not None and m.get("p_mean") is not None
            else None
        )
        out_bands[label] = m
    return {"rows": len(fav_items), "bands": out_bands}


def _summarize_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    base = _metrics(rows, "p_base")
    final = _metrics(rows, "p_final")
    state_only = _metrics(rows, "p_after_a")
    style_only = _metrics(rows, "p_after_b")
    by_bo: Dict[str, Any] = {}
    for bo_key in sorted({str(r.get("bo") or "") for r in rows}):
        rr = [r for r in rows if str(r.get("bo") or "") == bo_key]
        by_bo[str(bo_key)] = {"base": _metrics(rr, "p_base"), "final": _metrics(rr, "p_final")}
    b_methods = Counter(str(r.get("b_method") or "") for r in rows)
    c_methods = Counter(str(r.get("c_method") or "") for r in rows)
    return {
        "rows": len(rows),
        "base": base,
        "final": final,
        "after_a": state_only,
        "after_b": style_only,
        "gain_logloss_vs_base": (
            float(base["logloss"]) - float(final["logloss"])
            if base.get("logloss") is not None and final.get("logloss") is not None
            else None
        ),
        "gain_brier_vs_base": (
            float(base["brier"]) - float(final["brier"])
            if base.get("brier") is not None and final.get("brier") is not None
            else None
        ),
        "methods": {
            "b": dict(sorted(b_methods.items())),
            "c": dict(sorted(c_methods.items())),
        },
        "by_bo": by_bo,
    }


def _iter_replay_rows(
    *,
    art: MLArtifact,
    p_art: PlayersArtifact,
    params: Dict[str, Any],
    csv_paths: List[str],
    max_rows: int = 0,
    speed_profile: str = "fast",
) -> List[Dict[str, Any]]:
    team_scale, players_scale, form_cfg = _pick_scales_and_form_cfg(params)

    t_phase0 = time.time()
    g_parts: List[pd.DataFrame] = []
    for p in csv_paths:
        d = load_oracle_elixir_games(p, keep_playoffs=None)
        if d is not None and not d.empty:
            g_parts.append(d)
    if not g_parts:
        return []
    print(f"[backtest_abc] loaded game parts={len(g_parts)} in {time.time()-t_phase0:.1f}s", flush=True)
    games = _concat_non_empty_frames(g_parts)
    if games.empty:
        return []
    games["date"] = pd.to_datetime(games["date"], errors="coerce")
    games = games.dropna(subset=["date"]).copy()
    games = games.sort_values(["date", "gameid"]).drop_duplicates(subset=["gameid"], keep="last").reset_index(drop=True)
    speed = str(speed_profile or "fast").strip().lower()
    if speed not in {"fast", "full"}:
        speed = "fast"
    if speed == "fast" and len(games) > 3500:
        games = games.tail(3500).reset_index(drop=True)
        print("[backtest_abc] speed=fast -> games tail cap=3500", flush=True)

    gameids = set(games["gameid"].astype(str).tolist())
    t_phase1 = time.time()
    pr = load_match_player_rows(csv_paths, keep_playoffs=None, gameids=gameids)
    print(f"[backtest_abc] player rows loaded in {time.time()-t_phase1:.1f}s", flush=True)
    lineup_cache = _build_lineup_cache(pr)
    w_lineup = float((((art.meta or {}).get("players_layer") or {}).get("w_lineup") or 0.85))
    t_phase2 = time.time()
    samples = _make_samples(art=art, p_art=p_art, games=games, lineup_cache=lineup_cache, w_lineup=w_lineup)
    print(f"[backtest_abc] samples built={len(samples)} in {time.time()-t_phase2:.1f}s", flush=True)
    if not samples:
        return []
    if len(samples) != len(games):
        # fallback guard: align by order only for shared length and report later
        n = min(len(samples), len(games))
        games = games.iloc[:n].copy().reset_index(drop=True)
        samples = samples[:n]

    patch_seq = _patch_status_sequence(games)
    t_phase3 = time.time()
    team_games = _load_style_team_games(csv_paths)
    if speed == "fast" and isinstance(team_games, pd.DataFrame) and not team_games.empty:
        _min_date = pd.to_datetime(games["date"].min(), errors="coerce")
        if pd.notna(_min_date):
            team_games = team_games[team_games["date"] < games["date"].max()].copy()
    print(f"[backtest_abc] team_games loaded={0 if team_games is None else len(team_games)} in {time.time()-t_phase3:.1f}s", flush=True)
    style_model_cfg = (params.get("style_matchup_b_model") or {}) if isinstance(params, dict) else {}
    meta_model_cfg = (params.get("meta_blend_c_model") or {}) if isinstance(params, dict) else {}

    rows: List[Dict[str, Any]] = []
    hist_cut = pd.NaT
    hist_df = team_games.iloc[:0].copy() if isinstance(team_games, pd.DataFrame) else pd.DataFrame()
    profile_cache: Dict[Tuple[str, str, Optional[int], str], Any] = {}
    t0 = time.time()
    total_n = len(samples)

    def _cached_profile(df_hist: pd.DataFrame, team: str, g_obj: Any) -> Any:
        try:
            yv = int(g_obj.year) if pd.notna(g_obj.year) else None
        except Exception:
            yv = None
        split_v = str(g_obj.split or "").strip()
        date_key = str(pd.Timestamp(g_obj.date).date().isoformat())
        ck = (date_key, str(team), yv, split_v)
        if ck in profile_cache:
            return profile_cache[ck]
        try:
            filt = LineFilters(year=yv, league=None, split=(split_v or None), playoffs=None)
        except Exception:
            filt = LineFilters(year=None, league=None, split=(split_v or None), playoffs=None)
        prof = build_profile(df_hist, team=str(team), filters=filt, league_mode="auto", map_mode="avg", half_life_days=180.0)
        profile_cache[ck] = prof
        return prof

    for idx, (g, s) in enumerate(zip(games.itertuples(index=False), samples)):
        if int(max_rows or 0) > 0 and idx >= int(max_rows):
            break
        if idx > 0 and (idx % 200 == 0):
            dt = time.time() - t0
            print(
                f"[backtest_abc] rows={idx}/{total_n} "
                f"({(100.0*idx/max(1,total_n)):.1f}%) "
                f"elapsed={dt:.1f}s cache_profiles={len(profile_cache)}",
                flush=True,
            )
        g_date = pd.to_datetime(g.date, errors="coerce")
        if pd.isna(g_date):
            continue
        if pd.isna(hist_cut) or g_date != hist_cut:
            hist_df = team_games[team_games["date"] < g_date].copy() if not team_games.empty else team_games.iloc[:0].copy()
            hist_cut = g_date

        # Baseline prior to A/B/C: team+players fusion + season form
        p_pre = _fuse_probs_by_precision(
            p_team=float(s.p_team),
            p_players=float(s.p_players),
            n_team=float(s.n_team),
            n_players=float(s.n_players),
            team_scale=float(team_scale),
            players_scale=float(players_scale),
        )
        form_trace = _form_blend_trace(s, p_pre, form_cfg)
        p_base = float(form_trace.get("p_blended", p_pre))
        p_series_base = float(prob_win_series(float(p_base), int(s.bo_bucket) if str(s.bo_bucket).isdigit() else 1))

        patch_status, patch_shrink = patch_seq[idx]
        roster_changed = _sample_roster_changed(s)

        a_trace = compute_state_shadow_alite(
            p_map_old=float(p_base),
            p_series_old=float(p_series_base),
            bo=int(s.bo_bucket) if str(s.bo_bucket).isdigit() else 1,
            ml_info=_build_ml_info_for_sample(art, s),
            trace_form_info=form_trace,
            trace_fusion_info={"roster_changed": bool(roster_changed)},
            trace_patch_guard_info={
                "enabled": True,
                "applied": bool(patch_status),
                "status": str(patch_status),
                "shrink": float(patch_shrink),
            },
            trace_uncertainty_info={
                "n_eff": float(max(0.0, float(s.n_team) + 0.65 * float(s.n_players))),
                "prior_games": 22.0,
            },
            n_team_eff=float(s.n_team),
            n_players_eff=float(s.n_players),
            consistency_guard_triggered=False,
            consistency_guard_drift_pp=0.0,
        )
        p_after_a = float(a_trace.get("p_map_new", p_base)) if bool(a_trace.get("applied", False)) else float(p_base)

        # B layer: build no-leakage profiles from team game history
        style_out: Dict[str, Any] = {"applied": False, "reason": "no_history", "method": "style_matchup_b_lite"}
        p_after_b = float(p_after_a)
        pA = None
        pB = None
        if isinstance(hist_df, pd.DataFrame) and not hist_df.empty:
            try:
                pA = _cached_profile(hist_df, str(s.blue_team), g)
                pB = _cached_profile(hist_df, str(s.red_team), g)
            except Exception:
                pA = None
                pB = None
        common_style_kwargs = {
            "p_map_in": float(p_after_a),
            "pA": pA,
            "pB": pB,
            "league_a": str(s.league),
            "league_b": str(s.league),
            "patch_status": str(patch_status),
            "roster_changed": bool(roster_changed),
        }
        try:
            b_gate = should_apply_style_matchup_b_model_gate(
                bo=int(s.bo_bucket) if str(s.bo_bucket).isdigit() else 1,
                n_team_eff=float(s.n_team),
                n_players_eff=float(s.n_players),
                pA=pA,
                pB=pB,
                interregional=(not bool(s.same_league)),
                patch_status=str(patch_status),
                roster_changed=bool(roster_changed),
            )
            if bool((b_gate or {}).get("allow", False)):
                style_out = apply_style_matchup_b_model(model_cfg=style_model_cfg if isinstance(style_model_cfg, dict) else {}, **common_style_kwargs)
                if not (isinstance(style_out, dict) and bool(style_out.get("applied", False))):
                    style_out = apply_style_matchup_b_lite(**common_style_kwargs)
                    if isinstance(style_out, dict):
                        style_out["fallback_from_model"] = True
                        style_out["b_model_gate"] = dict(b_gate or {})
            else:
                style_out = {
                    "applied": False,
                    "reason": "b_gate_blocked_no_b_apply",
                    "method": "style_matchup_b_model_gate",
                    "b_model_gate": dict(b_gate or {}),
                    "fallback_from_model": False,
                }
            if bool(style_out.get("applied", False)):
                p_after_b = _safe_prob(style_out.get("p_after"), p_after_a)
        except Exception as e_style:
            style_out = {"applied": False, "reason": f"error:{type(e_style).__name__}", "error": str(e_style), "method": "style_error"}
            p_after_b = float(p_after_a)

        # C layer: trained gate + fallback
        recent_ev = float(_meta_recent_evidence_from_sample(s))
        rd_conf = None
        try:
            rd_conf = (a_trace.get("weights") or {}).get("rd_conf") if isinstance(a_trace, dict) else None
        except Exception:
            rd_conf = None
        if rd_conf is None:
            rd_conf = 0.35 + 0.65 * (float(s.n_team) / (float(s.n_team) + 12.0) if float(s.n_team) > 0 else 0.0)
        rd_conf = float(max(0.10, min(1.0, float(rd_conf))))
        hybrid_agree = 1.0 - min(1.0, abs(float(p_after_b) - float(p_base)) / 0.25)
        hybrid_agree = float(max(0.0, min(1.0, hybrid_agree)))
        common_meta_kwargs = {
            "p_anchor": float(p_base),
            "p_adjusted": float(p_after_b),
            "n_team_eff": float(s.n_team),
            "n_players_eff": float(s.n_players),
            "recent_evidence": float(recent_ev),
            "rd_conf": float(rd_conf),
            "hybrid_agree": float(hybrid_agree),
            "bo": int(s.bo_bucket) if str(s.bo_bucket).isdigit() else 1,
            "is_playoffs": (str(s.phase).strip().lower() == "playoffs"),
            "patch_status": str(patch_status),
            "interregional": (not bool(s.same_league)),
            "unknown_macro": (str(s.macro or "").strip().upper() == "OTHER"),
            "roster_changed": bool(roster_changed),
            "consistency_guard_triggered": False,
            "consistency_guard_drift_pp": 0.0,
        }
        meta_out: Dict[str, Any]
        p_final = float(p_after_b)
        try:
            meta_gate = should_apply_meta_blend_c_model_gate(
                bo=common_meta_kwargs.get("bo"),
                recent_evidence=common_meta_kwargs.get("recent_evidence"),
                n_team_eff=common_meta_kwargs.get("n_team_eff"),
                n_players_eff=common_meta_kwargs.get("n_players_eff"),
                is_playoffs=common_meta_kwargs.get("is_playoffs"),
                patch_status=str(common_meta_kwargs.get("patch_status") or ""),
                interregional=bool(common_meta_kwargs.get("interregional", False)),
            )
            if bool((meta_gate or {}).get("allow", False)):
                meta_out = apply_meta_blend_c_model(model_cfg=meta_model_cfg if isinstance(meta_model_cfg, dict) else {}, **common_meta_kwargs)
                if isinstance(meta_out, dict):
                    meta_out["c_model_gate"] = dict(meta_gate)
                if not (isinstance(meta_out, dict) and bool(meta_out.get("applied", False))):
                    lite_kwargs = {k: v for k, v in common_meta_kwargs.items() if k not in {"bo", "is_playoffs"}}
                    meta_out = apply_meta_blend_c_lite(**lite_kwargs)
                    if isinstance(meta_out, dict):
                        meta_out["fallback_from_model"] = True
                        meta_out["c_model_gate"] = dict(meta_gate if 'meta_gate' in locals() else {})
            else:
                meta_out = {
                    "applied": False,
                    "reason": "c_gate_blocked_no_c_apply",
                    "method": "meta_blend_c_model_gate",
                    "c_model_gate": dict(meta_gate or {}),
                    "fallback_from_model": False,
                }
            if bool(meta_out.get("applied", False)):
                p_final = _safe_prob(meta_out.get("p_after"), p_after_b)
        except Exception as e_meta:
            meta_out = {"applied": False, "reason": f"error:{type(e_meta).__name__}", "error": str(e_meta), "method": "meta_error"}
            p_final = float(p_after_b)

        try:
            p_raw, p_cal = _sym_team_probs(art, str(s.blue_team), str(s.red_team), str(s.league))
        except Exception:
            p_raw, p_cal = float("nan"), float("nan")

        rows.append(
            {
                "idx": int(idx),
                "date": str(pd.Timestamp(g_date).isoformat()),
                "month": str(s.month),
                "league": str(s.league),
                "macro": str(s.macro),
                "split": str(s.split),
                "bo": str(s.bo_bucket),
                "phase": str(s.phase),
                "blue_team": str(s.blue_team),
                "red_team": str(s.red_team),
                "y": int(s.y),
                "p_raw_team": (float(p_raw) if math.isfinite(float(p_raw)) else None),
                "p_cal_team": (float(p_cal) if math.isfinite(float(p_cal)) else None),
                "p_base": float(_safe_prob(p_base)),
                "p_after_a": float(_safe_prob(p_after_a)),
                "p_after_b": float(_safe_prob(p_after_b)),
                "p_final": float(_safe_prob(p_final)),
                "a_method": str(a_trace.get("method", "")) if isinstance(a_trace, dict) else "",
                "a_applied": bool(a_trace.get("applied", False)) if isinstance(a_trace, dict) else False,
                "b_method": str(style_out.get("method") or style_out.get("reason") or ""),
                "b_reason": str(style_out.get("reason") or ""),
                "b_applied": bool(style_out.get("applied", False)),
                "c_method": str((meta_out.get("model_meta") or {}).get("version") or meta_out.get("method") or meta_out.get("reason") or ""),
                "c_reason": str(meta_out.get("reason") or ""),
                "c_applied": bool(meta_out.get("applied", False)),
                "patch_status": str(patch_status),
                "roster_changed": bool(roster_changed),
                "recent_ev": float(recent_ev),
                "n_team": float(s.n_team),
                "n_players": float(s.n_players),
            }
        )
    return rows


def _build_report(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    all_rows = list(rows or [])
    by_league_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_macro_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in all_rows:
        by_league_rows[str(r.get("league") or "")].append(r)
        by_macro_rows[str(r.get("macro") or "")].append(r)

    by_league: Dict[str, Any] = {}
    for lg, rr in sorted(by_league_rows.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        months = sorted({str(x.get("month") or "") for x in rr})
        last_month = months[-1] if months else ""
        rr_last = [x for x in rr if str(x.get("month") or "") == last_month] if last_month else []
        by_league[lg] = {
            "summary": _summarize_rows(rr),
            "last_month": str(last_month),
            "last_month_summary": _summarize_rows(rr_last) if rr_last else {"rows": 0},
            "months": len(months),
        }

    by_macro = {mk: _summarize_rows(rr) for mk, rr in sorted(by_macro_rows.items())}
    global_summary = _summarize_rows(all_rows)
    monitoring_global = {
        "favorite_odd_bands_base": _odd_band_monitor(all_rows, "p_base"),
        "favorite_odd_bands_final": _odd_band_monitor(all_rows, "p_final"),
    }
    monitoring_by_league: Dict[str, Any] = {}
    for lg, rr in by_league_rows.items():
        monitoring_by_league[str(lg)] = {
            "favorite_odd_bands_base": _odd_band_monitor(rr, "p_base"),
            "favorite_odd_bands_final": _odd_band_monitor(rr, "p_final"),
        }
    top_leagues = sorted(
        (
            {
                "league": lg,
                "rows": int(v["summary"].get("rows", 0)),
                "gain_logloss_vs_base": v["summary"].get("gain_logloss_vs_base"),
                "gain_brier_vs_base": v["summary"].get("gain_brier_vs_base"),
                "last_month": v.get("last_month"),
                "last_month_gain_logloss_vs_base": (((v.get("last_month_summary") or {}).get("gain_logloss_vs_base"))),
            }
            for lg, v in by_league.items()
        ),
        key=lambda r: (-int(r.get("rows") or 0), str(r.get("league") or "")),
    )
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "pipeline": {
            "base": "team+players+season_form (frozen params)",
            "A": "A-lite runtime replay",
            "B": "B-real contextual model (fallback B-lite)",
            "C": "C trained model (fallback C-lite)",
        },
        "rows_total": len(all_rows),
        "global": global_summary,
        "monitoring": {
            "favorite_odd_bins": [list(x) for x in _FAV_ODD_BINS],
            "global": monitoring_global,
            "by_league": monitoring_by_league,
        },
        "by_macro": by_macro,
        "by_league": by_league,
        "top_leagues": top_leagues,
    }


_MAJOR_LEAGUES = ["LCK", "LPL", "LEC", "CBLOL", "LCP", "PRM"]


def _safe_float(v: Any) -> Optional[float]:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _pick_band_metric(monitor_obj: Dict[str, Any], band_label: str) -> Optional[Dict[str, Any]]:
    try:
        return ((monitor_obj or {}).get("bands") or {}).get(str(band_label))
    except Exception:
        return None


def _evaluate_stop_rules(report: Dict[str, Any]) -> Dict[str, Any]:
    # Regras formais para promover mudança de pipeline para produção.
    thresholds = {
        "min_global_gain_logloss": 0.0030,
        "min_global_gain_brier": 0.0005,
        "max_major_league_drawdown_logloss": 0.0100,
        "max_bo1_drawdown_logloss": 0.0200,
        "max_global_calibration_gap_pp_midbands": 5.0,
        "min_rows_global": 2000,
        "min_rows_major_league": 80,
    }
    g = report.get("global") or {}
    by_league = report.get("by_league") or {}
    monitoring = report.get("monitoring") or {}
    mon_global_final = (monitoring.get("global") or {}).get("favorite_odd_bands_final") or {}

    rows_total = int(report.get("rows_total") or 0)
    gain_ll = _safe_float(g.get("gain_logloss_vs_base"))
    gain_br = _safe_float(g.get("gain_brier_vs_base"))

    bo1 = (((g.get("by_bo") or {}).get("1") or {}))
    bo1_base_ll = _safe_float(((bo1.get("base") or {}).get("logloss")))
    bo1_final_ll = _safe_float(((bo1.get("final") or {}).get("logloss")))
    bo1_gain_ll = (bo1_base_ll - bo1_final_ll) if (bo1_base_ll is not None and bo1_final_ll is not None) else None

    major_checks: List[Dict[str, Any]] = []
    major_worst_drawdown = 0.0
    major_hard_fail = False
    for lg in _MAJOR_LEAGUES:
        summ = ((by_league.get(lg) or {}).get("summary") or {})
        rows_lg = int(summ.get("rows") or 0)
        gain_lg = _safe_float(summ.get("gain_logloss_vs_base"))
        considered = rows_lg >= int(thresholds["min_rows_major_league"])
        fail = False
        if considered and gain_lg is not None and gain_lg < -float(thresholds["max_major_league_drawdown_logloss"]):
            fail = True
            major_hard_fail = True
        if considered and gain_lg is not None:
            major_worst_drawdown = min(major_worst_drawdown, float(gain_lg))
        major_checks.append(
            {
                "league": lg,
                "rows": rows_lg,
                "considered": bool(considered),
                "gain_logloss_vs_base": gain_lg,
                "fail_drawdown": bool(fail),
            }
        )

    # Calibração em faixas intermediárias do favorito (onde há volume e decisões práticas)
    mid_bands = ["1.30-1.50", "1.50-1.75", "1.75-2.10"]
    band_checks: List[Dict[str, Any]] = []
    max_midband_gap = 0.0
    for b in mid_bands:
        bm = _pick_band_metric(mon_global_final, b) or {}
        gap = _safe_float(bm.get("calibration_gap_pp"))
        n_band = int(bm.get("n") or 0)
        considered = n_band >= 50 and gap is not None
        if considered:
            max_midband_gap = max(max_midband_gap, abs(float(gap)))
        band_checks.append(
            {
                "band": b,
                "n": n_band,
                "considered": bool(considered),
                "calibration_gap_pp": gap,
                "fail_gap": bool(
                    considered and abs(float(gap)) > float(thresholds["max_global_calibration_gap_pp_midbands"])
                ),
            }
        )
    band_hard_fail = any(bool(x.get("fail_gap")) for x in band_checks)

    checks = {
        "rows_total": rows_total,
        "rows_sufficient": bool(rows_total >= int(thresholds["min_rows_global"])),
        "global_gain_logloss_vs_base": gain_ll,
        "global_gain_brier_vs_base": gain_br,
        "global_gain_logloss_pass": bool(gain_ll is not None and gain_ll >= float(thresholds["min_global_gain_logloss"])),
        "global_gain_brier_pass": bool(gain_br is not None and gain_br >= float(thresholds["min_global_gain_brier"])),
        "bo1_gain_logloss_vs_base": bo1_gain_ll,
        "bo1_drawdown_fail": bool(
            bo1_gain_ll is not None and bo1_gain_ll < -float(thresholds["max_bo1_drawdown_logloss"])
        ),
        "major_leagues": major_checks,
        "major_worst_drawdown_logloss": float(major_worst_drawdown),
        "major_hard_fail": bool(major_hard_fail),
        "favorite_odd_midbands": band_checks,
        "favorite_odd_midbands_hard_fail": bool(band_hard_fail),
        "favorite_odd_midbands_max_abs_gap_pp": float(max_midband_gap),
    }

    reasons: List[str] = []
    if not checks["rows_sufficient"]:
        reasons.append("amostra global insuficiente para decisao")
    if checks["major_hard_fail"]:
        reasons.append("degradacao excessiva em liga principal")
    if checks["favorite_odd_midbands_hard_fail"]:
        reasons.append("calibracao ruim em faixas medias de odd do favorito")

    decision = "shadow_only"
    if checks["rows_sufficient"] and not checks["major_hard_fail"] and not checks["favorite_odd_midbands_hard_fail"]:
        if checks["global_gain_logloss_pass"] and checks["global_gain_brier_pass"] and not checks["bo1_drawdown_fail"]:
            decision = "promote"
        elif (gain_ll is not None and gain_ll >= 0.0) and not checks["bo1_drawdown_fail"]:
            decision = "shadow_only"
            reasons.append("ganho global positivo, mas abaixo do threshold de promocao")
        else:
            decision = "reject"
            reasons.append("ganho global insuficiente/negativo")
    else:
        decision = "reject" if (checks["major_hard_fail"] or checks["favorite_odd_midbands_hard_fail"]) else "shadow_only"

    return {
        "version": "stop_rules_v1",
        "decision": str(decision),
        "thresholds": thresholds,
        "checks": checks,
        "reasons": reasons,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Backtest final por liga do pipeline A+B+C (replay frozen artifacts).")
    ap.add_argument("--artifact", default=str(ROOT / "ml_artifact.json"))
    ap.add_argument("--players-artifact", default=str(ROOT / "players_artifact.json"))
    ap.add_argument("--params", default=str(ROOT / "params_fitted.json"))
    ap.add_argument("--csv", dest="csvs", action="append", default=None, help="CSV path (repeatable). Default: CSV_HISTORICO + CSV_DIARIO")
    ap.add_argument("--out", default=str(ROOT / "backtest_pipeline_abc_by_league_report.json"))
    ap.add_argument("--max-rows", type=int, default=0, help="Replay cap for debugging (0=all).")
    ap.add_argument("--speed", default="fast", choices=["fast", "full"], help="fast=replay recent window, full=all games")
    args = ap.parse_args()

    csv_paths = list(args.csvs or []) or _default_csv_paths(ROOT)
    csv_paths = [str(Path(p)) for p in csv_paths if str(p).lower().endswith(".csv")]
    if not csv_paths:
        print("ERRO: nenhum CSV encontrado.")
        return 2

    art_path = Path(args.artifact)
    p_art_path = Path(args.players_artifact)
    params_path = Path(args.params)
    if not art_path.exists():
        print(f"ERRO: artifact ausente: {art_path}")
        return 2
    if not p_art_path.exists():
        print(f"ERRO: players_artifact ausente: {p_art_path}")
        return 2
    if not params_path.exists():
        print(f"ERRO: params_fitted ausente: {params_path}")
        return 2

    art = MLArtifact.load_json(str(art_path))
    p_art = PlayersArtifact.load_json(str(p_art_path))
    params = _load_params(params_path)

    rows = _iter_replay_rows(
        art=art,
        p_art=p_art,
        params=params,
        csv_paths=csv_paths,
        max_rows=int(args.max_rows or 0),
        speed_profile=str(args.speed or "fast"),
    )
    rep = _build_report(rows)
    rep["promotion_decision"] = _evaluate_stop_rules(rep)
    rep["inputs"] = {
        "artifact": str(art_path),
        "players_artifact": str(p_art_path),
        "params": str(params_path),
        "csvs": [str(p) for p in csv_paths],
        "speed": str(args.speed or "fast"),
    }

    out_path = Path(args.out)
    out_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    g = rep.get("global") or {}
    print("OK: backtest pipeline A+B+C (replay frozen) concluido")
    print(f"- rows_total: {rep.get('rows_total')}")
    print(
        "- global logloss: base={:.6f} final={:.6f} gain={:.6f}".format(
            float(((g.get("base") or {}).get("logloss")) or float("nan")),
            float(((g.get("final") or {}).get("logloss")) or float("nan")),
            float((g.get("gain_logloss_vs_base") or 0.0)),
        )
    )
    print(
        "- global brier:   base={:.6f} final={:.6f} gain={:.6f}".format(
            float(((g.get("base") or {}).get("brier")) or float("nan")),
            float(((g.get("final") or {}).get("brier")) or float("nan")),
            float((g.get("gain_brier_vs_base") or 0.0)),
        )
    )
    print(f"- report: {out_path}")
    pdc = rep.get("promotion_decision") or {}
    print(f"- decision: {pdc.get('decision')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
