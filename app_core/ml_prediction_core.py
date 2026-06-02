"""Pure ML prediction computation extracted from plays_app.py.

Two functions cover the full prediction pipeline:

1. compute_ml_core_prediction — cache-able block:
   league resolution → p_map_v2 (forward + symmetry reverse) →
   microseg calibration → fused post-calibration.

2. compute_ml_post_layers — always-run block (not cached):
   WF correction → p_series → fit scales + players context.

All I/O and Streamlit session state remain in plays_app.py; these
functions receive data and callbacks, return result dicts.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, Optional


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _f(v: Any, default: float = float("nan")) -> float:
    try:
        r = float(v)
        return r if math.isfinite(r) else default
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Core prediction (cache-able)
# ---------------------------------------------------------------------------

def compute_ml_core_prediction(
    *,
    # Matchup
    team_a: str,
    team_b: str,
    artifact_path: str,
    as_of_date: Any,
    achievement_path: Optional[str],
    # Runtime config
    ml_runtime_cfg: Dict[str, Any],
    # Filter context (for microseg segment hints)
    filter_year: Optional[int],
    filter_league: Optional[str],
    filter_split: Optional[str],
    filter_playoffs: Any,
    bo: int,
    league_mode: str,
    # Sigs for cached microseg building
    csv_sig: Any,
    art_sig: Any,
    fit_params_path: Optional[str],
    # Callbacks — injected by plays_app to keep caching/IO there
    resolve_leagues_fn: Callable,
    # signature: (team_a, team_b, year, league_mode, fixed_league) -> dict
    p_map_v2_fn: Callable,
    # signature: (artifact_path, team_blue, team_red, as_of, *, ach_override_path,
    #             league_hint_blue, league_hint_red, tier_hint_blue, tier_hint_red)
    #           -> Optional[dict]
    build_microseg_table_fn: Callable,
    # signature: (csv_sig, art_sig, lookback_games, shrink_k) -> dict
    apply_microseg_fn: Callable,
    # signature: (p_map_cal, *, league, split, side, bo, phase, table,
    #             min_n, strength, cap_pp, hierarchical, hierarchy_decay)
    #           -> (float, dict)
    apply_fused_postcal_fn: Callable,
    # signature: (p_map_cal, *, league_hint, use_fitted) -> (float, dict)
    load_fitted_params_fn: Optional[Callable] = None,
    # signature: (file_sig_tuple) -> dict
    file_sig_fn: Optional[Callable] = None,
    # signature: (path_str) -> (str, int, int)
) -> Dict[str, Any]:
    """Compute p_map + calibration for a matchup, returning a cache-able result dict.

    Returns
    -------
    Dict with keys:
      ml_info, p_map_raw, p_map_cal,
      league_a, league_b, tier_a, tier_b,
      microseg_info, fused_post_cal_info
    """
    p_map_raw = float("nan")
    p_map_cal = float("nan")
    ml_info: Optional[Dict[str, Any]] = None
    league_a = league_b = tier_a = tier_b = ""
    microseg_info: Optional[Dict[str, Any]] = None
    fused_post_cal_info: Optional[Dict[str, Any]] = None

    # 1. League resolution
    fixed_league = str(filter_league or "") if league_mode == "fixed" else ""
    try:
        _lg = resolve_leagues_fn(
            team_a, team_b, filter_year, str(league_mode), fixed_league
        )
        league_a = str(_lg.get("league_a") or "")
        league_b = str(_lg.get("league_b") or "")
        tier_a = str(_lg.get("tier_a") or "")
        tier_b = str(_lg.get("tier_b") or "")
    except (OSError, TypeError, ValueError):
        pass

    # 2. Forward ML
    try:
        ml_info = p_map_v2_fn(
            artifact_path,
            team_a,
            team_b,
            as_of_date,
            ach_override_path=achievement_path,
            league_hint_blue=league_a or None,
            league_hint_red=league_b or None,
            tier_hint_blue=tier_a or None,
            tier_hint_red=tier_b or None,
        )
    except Exception:
        ml_info = None

    if ml_info is not None:
        p_map_raw = _f(ml_info.get("p_raw"))
        p_map_cal = _f(ml_info.get("p_cal"))

        # 3. Reverse ML (symmetry: p(A,B) ≈ 1 − p(B,A))
        try:
            _rev = p_map_v2_fn(
                artifact_path,
                team_b,
                team_a,
                as_of_date,
                ach_override_path=achievement_path,
                league_hint_blue=league_b or None,
                league_hint_red=league_a or None,
                tier_hint_blue=tier_b or None,
                tier_hint_red=tier_a or None,
            )
            if _rev is not None:
                _p_cal_rev = _f(_rev.get("p_cal"))
                _p_raw_rev = _f(_rev.get("p_raw"))
                if math.isfinite(p_map_cal) and math.isfinite(_p_cal_rev):
                    p_map_cal = 0.5 * (p_map_cal + (1.0 - _p_cal_rev))
                if math.isfinite(p_map_raw) and math.isfinite(_p_raw_rev):
                    p_map_raw = 0.5 * (p_map_raw + (1.0 - _p_raw_rev))
        except Exception:
            pass

        # 4. Microseg calibration
        if math.isfinite(p_map_cal) and bool(ml_runtime_cfg.get("ml_microseg_enabled")):
            try:
                seg_tbl: Dict[str, Any] = {}
                seg_src = "live"
                if load_fitted_params_fn is not None and file_sig_fn is not None and fit_params_path:
                    try:
                        _fit_live = load_fitted_params_fn(file_sig_fn(fit_params_path))
                        _ms_pack = (_fit_live or {}).get("microseg_calibration") if isinstance(_fit_live, dict) else {}
                        _tbl_fit = (_ms_pack or {}).get("table") if isinstance(_ms_pack, dict) else {}
                        if isinstance(_tbl_fit, dict) and len(_tbl_fit) > 0:
                            seg_tbl = _tbl_fit
                            seg_src = "fitted"
                    except (OSError, TypeError, ValueError):
                        seg_tbl = {}

                if not seg_tbl:
                    seg_tbl = build_microseg_table_fn(
                        csv_sig=csv_sig,
                        art_sig=art_sig,
                        lookback_games=int(ml_runtime_cfg.get("ml_microseg_lookback_games", 1200)),
                        shrink_k=float(ml_runtime_cfg.get("ml_microseg_shrink_k", 90.0)),
                    )

                _split_hint = str(filter_split or "")
                _phase_hint = (
                    "playoffs"
                    if str(filter_playoffs or "").lower() in {"1", "true", "playoffs"}
                    else "regular"
                )
                _bo_hint = str(int(bo)) if str(int(bo)) in {"1", "3", "5"} else "1"
                p_map_cal, _seg_info = apply_microseg_fn(
                    float(p_map_cal),
                    league=str(league_a or ""),
                    split=_split_hint,
                    side="blue",
                    bo=_bo_hint,
                    phase=_phase_hint,
                    table=seg_tbl,
                    min_n=int(ml_runtime_cfg.get("ml_microseg_min_n", 30)),
                    strength=float(ml_runtime_cfg.get("ml_microseg_strength", 0.5)),
                    cap_pp=float(ml_runtime_cfg.get("ml_microseg_cap_pp", 3.0)),
                    hierarchical=bool(ml_runtime_cfg.get("ml_microseg_hierarchical", True)),
                    hierarchy_decay=float(ml_runtime_cfg.get("ml_microseg_hier_decay", 0.80)),
                )
                if isinstance(_seg_info, dict):
                    _seg_info["source"] = str(seg_src)
                microseg_info = _seg_info
            except (AttributeError, KeyError, OSError, TypeError, ValueError):
                pass

        # 5. Fused post-calibration
        if math.isfinite(p_map_cal):
            try:
                p_map_cal, _fp_info = apply_fused_postcal_fn(
                    float(p_map_cal),
                    league_hint=str(league_a or ""),
                    use_fitted=bool(ml_runtime_cfg.get("ml_fused_post_cal_use_fitted", True)),
                )
                if isinstance(_fp_info, dict):
                    fused_post_cal_info = _fp_info
            except (TypeError, ValueError):
                pass

    return {
        "ml_info": ml_info,
        "p_map_raw": float(p_map_raw),
        "p_map_cal": float(p_map_cal),
        "league_a": str(league_a),
        "league_b": str(league_b),
        "tier_a": str(tier_a),
        "tier_b": str(tier_b),
        "microseg_info": microseg_info,
        "fused_post_cal_info": fused_post_cal_info,
    }


# ---------------------------------------------------------------------------
# Post layers (not cached — runs every render)
# ---------------------------------------------------------------------------

def compute_ml_post_layers(
    *,
    ml_info: Optional[Dict[str, Any]],
    p_map_cal: float,
    bo: int,
    ml_runtime_cfg: Dict[str, Any],
    wf_report: Optional[Dict[str, Any]],
    # Callbacks
    wf_correct_p_map_fn: Callable,
    # signature: (report, p_in, *, league_hint, strength) -> (float, dict)
    fit_scales_for_league_fn: Callable,
    # signature: (league_hint) -> (team_scale, players_scale, league_used)
    fit_players_context_for_league_fn: Callable,
    # signature: (league_hint) -> (cfg_dict, source_str)
    prob_win_series_fn: Callable,
    # signature: (p_map, bo) -> float
) -> Dict[str, Any]:
    """Apply WF correction, compute p_series, and resolve fit scales.

    Returns
    -------
    Dict with keys:
      p_map_cal, p_series, wf_corr_info,
      fit_team_scale, fit_players_scale, fit_league_used,
      players_context_cfg, players_context_src
    """
    wf_corr_info: Optional[Dict[str, Any]] = None

    # 1. WF correction
    if math.isfinite(p_map_cal) and bool(ml_runtime_cfg.get("wf_apply_ml_correction")):
        try:
            _league_hint = ""
            if isinstance(ml_info, dict) and not ml_info.get("__error__"):
                _lb = str(((ml_info.get("blue") or {}).get("league")) or "").strip()
                _lr = str(((ml_info.get("red") or {}).get("league")) or "").strip()
                if _lb and _lb == _lr:
                    _league_hint = _lb
            p_corr, corr_info = wf_correct_p_map_fn(
                wf_report if isinstance(wf_report, dict) else None,
                float(p_map_cal),
                league_hint=_league_hint,
                strength=float(ml_runtime_cfg.get("wf_ml_corr_strength", 0.60)),
            )
            if math.isfinite(float(p_corr)):
                p_map_cal = float(p_corr)
            if isinstance(corr_info, dict):
                wf_corr_info = corr_info
        except (TypeError, ValueError):
            pass

    # 2. p_series
    p_series = float("nan")
    if math.isfinite(p_map_cal):
        try:
            p_series = float(prob_win_series_fn(float(p_map_cal), int(bo)))
        except (TypeError, ValueError, OverflowError):
            p_series = float("nan")

    # 3. Fit scales + players context
    fit_league_hint = ""
    if isinstance(ml_info, dict) and not ml_info.get("__error__"):
        _lb = str(((ml_info.get("blue") or {}).get("league")) or "").strip()
        _lr = str(((ml_info.get("red") or {}).get("league")) or "").strip()
        if _lb and _lb == _lr:
            fit_league_hint = _lb

    try:
        fit_team_scale, fit_players_scale, fit_league_used = fit_scales_for_league_fn(fit_league_hint)
    except Exception:
        fit_team_scale, fit_players_scale, fit_league_used = 1.0, 1.0, ""

    try:
        players_context_cfg, players_context_src = fit_players_context_for_league_fn(fit_league_hint)
    except Exception:
        players_context_cfg, players_context_src = {}, ""

    return {
        "p_map_cal": float(p_map_cal),
        "p_series": float(p_series),
        "wf_corr_info": wf_corr_info,
        "fit_team_scale": float(fit_team_scale),
        "fit_players_scale": float(fit_players_scale),
        "fit_league_used": str(fit_league_used),
        "players_context_cfg": players_context_cfg if isinstance(players_context_cfg, dict) else {},
        "players_context_src": str(players_context_src),
    }


__all__ = ["compute_ml_core_prediction", "compute_ml_post_layers"]
