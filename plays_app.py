# -*- coding: utf-8 -*-
# plays_app.py
# Streamlit app: Plays (ML + Totais)
# - Lê ml_artifact.json (ML core v2) para p_map (calibrado) e calcula odds de série (BO1/3/5)
# - Lê CSV OracleElixir (team rows) para calcular Totais (kills/towers/dragons/barons/inhibitors/time)
# - Calcula odds justas de Over/Under e combos ML+Over/Under (helper conjunto com fallback independente)

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from datetime import date
import inspect as _inspect
import json
import sys

import math
import re

from app_core.render_ctx_core import build_render_ctx as _build_render_ctx


def _pick_ctx(*names):
    """ctx EXPLÍCITO por lista de chaves (força-tarefa 23/07).

    Nomeia exatamente o que a função chamada lê (incluindo as chaves que ela
    repassa pra baixo), em vez de vazar o namespace inteiro via ctx=globals().
    Usa globals().get para PRESERVAR o comportamento das chaves de runtime que
    podem legitimamente não existir num certo caminho (None, não NameError).
    Os contratos só-de-import já foram convertidos com referência direta (falha
    alta); aqui, casos com valores de runtime/repasse usam este helper seguro."""
    g = globals()
    return {n: g.get(n) for n in names}


def _pick_ctx_from_modules(*module_names):
    """ctx EXPLÍCITO auto-derivado das fontes de VÁRIOS módulos do fecho.

    Para os casos em que a função repassa ctx pra baixo CRUZANDO módulos (ex.:
    csv_bootstrap_gate -> ensure_csv_runtime_ready + collect_maintenance_status;
    params_tab -> params_sections_core), extrai TODAS as chaves ctx.get/_ctx do
    fecho inteiro via build_render_ctx — completo e à prova de drift (re-deriva
    a cada run, nada de lista de 31/90 nomes na mão que apodrece). Só listar
    aqui os módulos do fecho (verificado que nenhum vai mais fundo)."""
    import importlib
    src = "\n".join(
        _inspect.getsource(importlib.import_module(n)) for n in module_names
    )
    return _build_render_ctx(globals(), renderer_source=src,
                             renderer_name="+".join(module_names), validate=False)

import pandas as pd
import numpy as np
import streamlit as st

from mlcore.artifact import MLArtifact
from mlcore.bo import prob_win_series
from mlcore.tiers import tier_base_points, league_base_points
from mlcore.players_layer import PlayersArtifact
from mlcore.achievements import load_achievements, team_boost_points
from mlcore.utils import clip_prob
from mlcore.walkforward_report import run_walkforward
from mlcore.fit_ml_params import fit_params as _fit_ml_params_run
from mlcore.layer_validation import run_layer_validation
from mlcore.calibration_diagnostics import run_calibration_diagnostics
from mlcore.league_context import league_macro_key as shared_league_macro_key
from app_core.market import (
    parse_lines_text,
    parse_time_lines_text,
    matchup_key as build_matchup_key,
    odd_from_prob as _odd_from_p,
)
from app_core.matchup_filters_core import resolve_prev_season_with_fallback as _resolve_prev_season_with_fallback
from app_core.tab_dispatcher import (
    TAB_PARAMS,
    TAB_VISAO,
    TAB_CONS,
    TAB_LINE_ANALYSIS,
    TAB_OPORTUNIDADES,
    SECONDARY_TAB_ORDER,
    desenhar_aba as _desenhar_aba,
    dispatch_secondary_tabs,
    iniciar_registro_de_falhas as _iniciar_registro_de_falhas,
)
from app_core.winner_pricing_core import compute_winner_pricing_bundle as core_compute_winner_pricing_bundle
from app_core.line_store import load_json_store, persist_json_store, ensure_session_store
from app_core.lineup_state import (
    POS_CANON as _POS_CANON,
    ensure_lineup_runtime_state as _ensure_lineup_runtime_state_impl,
    get_lineup_loaded_key as _get_lineup_loaded_key_impl,
    get_lineup_runtime_settings as _get_lineup_runtime_settings_impl,
    set_lineup_loaded_key as _set_lineup_loaded_key_impl,
    norm_pos as _norm_pos,
    norm_pos_ml as _norm_pos_ml,
    parse_pct as _parse_pct,
    load_lineup_for_matchup as _load_lineup_for_matchup_impl,
    save_lineup_for_matchup as _save_lineup_for_matchup_impl,
    get_lineup_selected as _get_lineup_selected_impl,
)
from app_core.lines_state import load_lines_for_matchup as _load_lines_for_matchup_impl, save_lines_for_matchup as _save_lines_for_matchup_impl
from app_core.navigation import TAB_ALL as _TAB_ALL, pick_tabs as _pick_tabs
from app_core.navigation_state_core import (
    DEFAULT_UI_PAGE_MODE as NAV_DEFAULT_UI_PAGE_MODE,
    TOP_NAV_OPTIONS as NAV_TOP_NAV_OPTIONS,
    get_ui_page_mode as core_get_ui_page_mode,
    resolve_nav_page as core_resolve_nav_page,
    set_flash_saved_profile_msg as core_set_flash_saved_profile_msg,
)
from app_core.ui_labels import (
    fmt_prob_pct as _format_pct,
    fmt_num as _format_num,
    min_to_mmss as _min_to_mmss,
    metric_label_pt as _metric_label_pt,
    side_label_pt as _side_label_pt,
    fmt_line_disp as _fmt_line_disp,
    fmt_recortes_disp as _fmt_recortes_disp,
)
from app_core.odds_core import (
    tail_df as core_tail_df,
    recency_slices as core_recency_slices,
)
from app_core.resumo_core import (
    wr_laplace as core_wr_laplace,
    counts_ml_totals as core_counts_ml_totals,
    make_pricing_adapters as core_make_pricing_adapters,
    finalize_resumo_dataframe as core_finalize_resumo_dataframe,
    build_ml_rows as core_build_ml_rows,
    build_metric_rows as core_build_metric_rows,
    build_combo_rows as core_build_combo_rows,
)
from app_core.players_core import (
    build_player_means_rows as core_build_player_means_rows,
    build_player_market_rows as core_build_player_market_rows,
    build_recent_player_stats_rows as core_build_recent_player_stats_rows,
)
from app_core.players_feature_trace_core import (
    append_players_recent_stats_panel_trace as core_append_players_recent_stats_panel_trace,
    append_players_fair_panel_trace as core_append_players_fair_panel_trace,
    append_players_markets_panel_trace as core_append_players_markets_panel_trace,
    append_players_panels_bundle_trace as core_append_players_panels_bundle_trace,
)
from app_core.players_state import (
    parse_players_text as core_parse_players_text,
    resolve_players as core_resolve_players,
    build_lane_rows as core_build_lane_rows,
    ensure_players_text_state as core_ensure_players_text_state,
    ensure_players_filter_state as core_ensure_players_filter_state,
    ensure_player_line_input_state as core_ensure_player_line_input_state,
    apply_players_submission_state as core_apply_players_submission_state,
    apply_players_autofill_state as core_apply_players_autofill_state,
    build_per_player_lines_by_idx as core_build_per_player_lines_by_idx,
)
from app_core.players_data_core import (
    load_player_rows as core_load_player_rows,
    apply_filters_players as core_apply_filters_players,
    fuzzy_match_one as core_fuzzy_match_one,
)
from app_core.ui_cache_core import cached_champion_vocab as core_champion_vocab
from app_core.players_lineup_impact_core import (
    load_players_impact as core_load_players_impact,
    apply_shrink_m as core_apply_shrink_m,
    best_match as core_best_match,
    latest_lineup_for_team as core_latest_lineup_for_team,
    latest_lineup_names as core_latest_lineup_names,
)
from app_core.players_elo_core import (
    load_player_rows_multi as core_load_player_rows_multi,
    compute_player_elo_global as core_compute_player_elo_global,
    elo_rank_table as _elo_rank_table_core,
)
from app_core.display_tables_core import (
    df_contract_view as core_df_contract_view,
    display_ou_table as core_display_ou_table,
    display_ml_totals_table as core_display_ml_totals_table,
)
from app_core.csv_bootstrap_runtime_core import (
    apply_bootstrap_selection as core_apply_bootstrap_selection,
    build_runtime_config_defaults as core_build_runtime_config_defaults,
    discover_season_csvs as _discover_season_csvs,
    list_csv_candidates as _list_csv_candidates,
    request_csv_runtime_refresh as core_request_csv_runtime_refresh,
    reset_bootstrap_selection as core_reset_bootstrap_selection,
    resolve_active_csv_and_artifact as core_resolve_active_csv_and_artifact,
    resolve_ml_paths as core_resolve_ml_paths,
    resolve_season_context as core_resolve_season_context,
)
from app_core.csv_prepare_core import (
    csv_diag_path as core_csv_diag_path,
    csv_header_check_path as core_csv_header_check_path,
)
from app_core.flow_runtime_core import (
    apply_pending_load as core_apply_pending_load,
    consume_analysis_force_once as core_consume_analysis_force_once,
    consume_consistency_refresh_pending as core_consume_consistency_refresh_pending,
    clear_matchup_selection as core_clear_matchup_selection,
    consume_pending_reset_matchup as core_consume_pending_reset_matchup,
    ensure_matchup_selection_state as core_ensure_matchup_selection_state,
    get_flow_stage as core_get_flow_stage,
    get_last_season_label as core_get_last_season_label,
    get_lines_loaded_key as core_get_lines_loaded_key,
    reset_flow_state as core_reset_flow_state,
    resolve_players_artifact_path as core_resolve_players_artifact_path,
    request_analysis_refresh as core_request_analysis_refresh,
    set_last_season_label as core_set_last_season_label,
    set_flow_stage as core_set_flow_stage,
    set_lines_loaded_key as core_set_lines_loaded_key,
    set_matchup_key as core_set_matchup_key,
    set_selected_team as core_set_selected_team,
)
from app_core.schedule_import_core import (
    load_schedule_aliases as core_load_schedule_aliases,
    normalize_schedule_team_key as core_normalize_schedule_team_key,
    parse_schedule_text as core_parse_schedule_text,
    resolve_schedule_team as core_resolve_schedule_team,
    save_schedule_aliases as core_save_schedule_aliases,
    suggest_schedule_teams as core_suggest_schedule_teams,
)
from app_core.schedule_state_core import (
    append_schedule_games as core_append_schedule_games,
    bind_schedule_store_path as core_bind_schedule_store_path,
    clear_pending_schedule_import as core_clear_pending_schedule_import,
    clear_schedule_games as core_clear_schedule_games,
    clear_schedule_text as core_clear_schedule_text,
    ensure_schedule_alias_state as core_ensure_schedule_alias_state,
    get_pending_schedule_import as core_get_pending_schedule_import,
    get_schedule_games as core_get_schedule_games,
    has_schedule_unknown_aliases as core_has_schedule_unknown_aliases,
    persist_schedule_runtime_state as core_persist_schedule_runtime_state,
    restore_schedule_runtime_state as core_restore_schedule_runtime_state,
    save_pending_schedule_import as core_save_pending_schedule_import,
    set_schedule_unknown_aliases as core_set_schedule_unknown_aliases,
)
from app_core.pre_delivery_checks_core import (
    assess_anchor_regression as core_assess_anchor_regression,
    assess_confidence_baseline_file as core_assess_confidence_baseline_file,
    assess_combined_trace_file as core_assess_combined_trace_file,
    assess_feature_trace_health as core_assess_feature_trace_health,
    assess_navigation_integrity as core_assess_navigation_integrity,
    assess_patch_calibration_freshness as core_assess_patch_calibration_freshness,
    assess_params_baseline_stability as core_assess_params_baseline_stability,
    assess_ranking_coverage as core_assess_ranking_coverage,
    assess_session_trace as core_assess_session_trace,
    assess_state_artifact_file as core_assess_state_artifact_file,
    assess_utf8_file as core_assess_utf8_file,
    run_pre_delivery_smokes as core_run_pre_delivery_smokes,
)
from app_core.pre_delivery_runtime_core import run_pre_delivery_checks as core_run_pre_delivery_checks_runtime
from app_core.runtime_session_state_core import (
    get_wf_last_report as core_get_wf_last_report,
)
from app_core.daily_pipeline_runtime_core import run_daily_pipeline as core_run_daily_pipeline
from app_core.analysis_runtime_state_core import (
    build_analysis_signature as core_build_analysis_signature,
    build_consistency_analysis_signature as core_build_consistency_analysis_signature,
    compute_sim_seed_series as core_compute_sim_seed_series,
    resolve_active_line_texts as core_resolve_active_line_texts,
    stable_seed_from_parts as _stable_seed_from_parts,
)
from app_core.stats_config import flow_line_keys as _flow_line_keys
from app_core.maintenance_runtime_core import (
    read_artifact_summary_path as core_read_artifact_summary_path,
)
from app_core.bootstrap_maintenance_state_core import (
    read_json_file_safe as core_read_json_file_safe,
)
from app_core.app_state import (
    bootstrap_state as core_bootstrap_state,
    apply_recommended_preset as core_apply_recommended_preset,
    apply_excellent_value_preset as core_apply_excellent_value_preset,
    apply_twenty_ten_preset as core_apply_twenty_ten_preset,
    get_state_schema as core_get_state_schema,
    get_bool as state_get_bool,
    get_float as state_get_float,
    get_int as state_get_int,
    get_str as state_get_str,
)
from app_core.champions_state_core import (
    ensure_champions_filter_state as core_ensure_champions_filter_state,
    reset_champions_league_dependents as core_reset_champions_league_dependents,
    resolve_blue_side_choice as core_resolve_blue_side_choice,
    sync_blue_side_choice as core_sync_blue_side_choice,
)
from app_core.resumo_state_core import (
    apply_resumo_combo_preset as core_apply_resumo_combo_preset,
    apply_resumo_filter_values as core_apply_resumo_filter_values,
    delete_active_resumo_filter_profile as core_delete_active_resumo_filter_profile,
    ensure_resumo_combo_state as core_ensure_resumo_combo_state,
    list_resumo_filter_presets as core_list_resumo_filter_presets,
    load_resumo_filter_custom as core_load_resumo_filter_custom,
    save_resumo_filter_custom as core_save_resumo_filter_custom,
    save_resumo_filter_profile as core_save_resumo_filter_profile,
)
from app_core.resumo_guardrail_core import (
    build_resumo_guardrail_cfg as core_build_resumo_guardrail_cfg,
)
from app_core.resumo_runtime_core import (
    build_market_trace_rows as core_build_market_trace_rows,
    build_statscamps_scope_frame as core_build_statscamps_scope_frame,
    compute_statscamps_pct as core_compute_statscamps_pct,
    ensure_metric_lines as core_ensure_metric_lines,
    format_statscamps_badge as core_format_statscamps_badge,
    infer_matchup_league as core_infer_matchup_league,
)
from app_core.settings_core import (
    settings_path as core_settings_path,
    load_settings_from_disk as core_load_settings_from_disk,
    apply_settings_to_session as core_apply_settings_to_session,
    save_settings_to_disk as core_save_settings_to_disk,
    process_pending_settings_actions as core_process_pending_settings_actions,
    init_settings_once as core_init_settings_once,
)
from app_core.settings_ui import render_settings_sidebar as core_render_settings_sidebar
from app_core.rankings_tab_core import render_rankings_tab as core_render_rankings_tab
from app_core.schedule_tab_core import render_schedule_tab as core_render_schedule_tab
from app_core.series_tab_core import render_series_tab as core_render_series_tab
from app_core.statscamps_tab_core import render_statscamps_tab as core_render_statscamps_tab
from app_core.line_analysis_tab_core import render_line_analysis_tab as core_render_line_analysis_tab
from app_core.oportunidades_tab_core import render_oportunidades_tab as core_render_oportunidades_tab
from mlcore.lines_engine import prob_over_from_total as core_prob_over_from_total
from app_core.players_tab_core import render_players_tab as core_render_players_tab
from app_core.champions_tab_core import render_champions_tab as core_render_champions_tab
from app_core.resumo_tab_core import render_resumo_tab as core_render_resumo_tab
from app_core.identity_tab_core import render_identity_tab as core_render_identity_tab
from app_core.live_bet_tab_core import render_live_bet_tab as core_render_live_bet_tab
from app_core.radar_tab_core import render_radar_tab as core_render_radar_tab
from app_core.meta_tab_core import render_meta_tab as core_render_meta_tab
from app_core.identity_registry_core import (
    load_identity_registry as core_load_identity_registry,
    team_identity_candidates as core_team_identity_candidates,
    team_identity_league_candidates as core_team_identity_league_candidates,
)
from app_core.league_transfer_features_core import (
    load_league_transfer_features as core_load_league_transfer_features,
)
from app_core.schedule_agenda_ui_core import (
    render_schedule_agenda_expander as core_render_schedule_agenda_expander,
)
from app_core.lines_stage_ui_core import (
    render_lines_stage as core_render_lines_stage,
)
from app_core.nav_pages_core import (
    render_live_bet_page as core_render_live_bet_page,
    render_radar_page as core_render_radar_page,
)
from app_core.matchup_selection_core import (
    render_matchup_selection as core_render_matchup_selection,
    team_with_league_label as _team_with_league_label,
    canon_team_key as _canon_team_key,
    team_canon_maps as _team_canon_maps,
)
from app_core.lines_parsing_core import (
    parse_single_float as _parse_single_float,
)
from app_core.ml_oos_gate_core import (
    wf_correct_p_map as _wf_correct_p_map_core,
)
from app_core.process_runner_core import run_cmd as _run_cmd_core
from app_core.ml_probability_adjustments_core import (
    apply_ml_uncertainty_adjust as _apply_ml_uncertainty_adjust_core,
    apply_ml_marginal_trust_adjust as _apply_ml_marginal_trust_adjust_core,
    apply_ml_microseg_calibration as _apply_ml_microseg_calibration_core,
)
from app_core.anchor_snapshot_core import compute_anchor_snapshot as _compute_anchor_snapshot
from app_core.ml_microseg_core import build_ml_microseg_table as _build_ml_microseg_table_core
from app_core.ml_prediction_core import (
    compute_ml_core_prediction as _compute_ml_core_prediction,
    compute_ml_post_layers as _compute_ml_post_layers,
)
from app_core.schedule_alias_ui_core import render_schedule_alias_mapping as core_render_schedule_alias_mapping
from app_core.plays_bootstrap_ui_core import (
    apply_season_change_reset as core_apply_season_change_reset,
    ensure_achievement_path as core_ensure_achievement_path,
    get_boot_hist_csvs as core_get_boot_hist_csvs,
    normalize_matchup_selection_teams as core_normalize_matchup_selection_teams,
)
from app_core.matchup_league_resolution_core import (
    resolve_runtime_team_leagues as core_resolve_runtime_team_leagues,
)
from app_core.csv_bootstrap_selector_ui_core import render_bootstrap_selector as core_render_bootstrap_selector
from app_core.ml_quality_alarm_ui_core import render_ml_quality_alarm as core_render_ml_quality_alarm
from app_core.technical_runtime_config_ui_core import render_technical_runtime_config_panel as core_render_technical_runtime_config_panel
from app_core.trace_core import (
    build_combined_trace as core_build_combined_trace,
    coerce_feature_flag as core_coerce_feature_flag,
)
from app_core.ml_settings_runtime_core import (
    shared_ml_defaults as core_shared_ml_defaults,
    build_runtime_param_defaults as core_build_runtime_param_defaults,
    local_runtime_defaults as core_local_runtime_defaults,
)
from app_core.ml_session_runtime_core import (
    apply_fit_runtime_state_to_session as core_apply_fit_runtime_state_to_session,
    apply_players_context_runtime_override as core_apply_players_context_runtime_override,
    clear_ml_fused_post_cal_info as core_clear_ml_fused_post_cal_info,
    clear_ml_microseg_info as core_clear_ml_microseg_info,
    clear_wf_ml_corr_info as core_clear_wf_ml_corr_info,
    get_achievement_path as core_get_achievement_path,
    get_analysis_gate_state as core_get_analysis_gate_state,
    get_feature_trace_state as core_get_feature_trace_state,
    get_fit_runtime_snapshot as core_get_fit_runtime_snapshot,
    get_ml_engine_runtime_settings as core_get_ml_engine_runtime_settings,
    get_ml_fused_post_cal_info as core_get_ml_fused_post_cal_info,
    get_ml_microseg_info as core_get_ml_microseg_info,
    get_mlcore_cache_state as core_get_mlcore_cache_state,
    get_ml_trace_snapshot as core_get_ml_trace_snapshot,
    persist_combined_trace_file as core_persist_combined_trace_file,
    set_achievement_path as core_set_achievement_path,
    set_analysis_signature as core_set_analysis_signature,
    set_consistency_analysis_signature as core_set_consistency_analysis_signature,
    set_fit_runtime_labels as core_set_fit_runtime_labels,
    set_fit_used_scales as core_set_fit_used_scales,
    set_ml_fused_post_cal_info as core_set_ml_fused_post_cal_info,
    set_ml_microseg_info as core_set_ml_microseg_info,
    set_mlcore_cache_state as core_set_mlcore_cache_state,
    set_wf_ml_corr_info as core_set_wf_ml_corr_info,
)
from app_core.results_runtime_state_core import (
    resolve_hc_kills_team as core_resolve_hc_kills_team,
    resolve_results_runtime_settings as core_resolve_results_runtime_settings,
)
from app_core.calibration_schedule import build_patch_snapshot as core_build_patch_snapshot, recommend_recalibration as core_recommend_recalibration
from app_core.fusion_core import (
    fuse_with_coherence_guard as core_fuse_with_coherence_guard,
)
from app_core.params_tuning_core import (
    enrich_params_with_areal_prob_tuning as _enrich_params_with_areal_prob_tuning,
    enrich_params_with_ml_marginal_band_coeffs as core_enrich_params_with_ml_marginal_band_coeffs,
)
from app_core.fit_runtime_core import (
    apply_fused_post_calibration as core_apply_fused_post_calibration,
    build_fit_runtime_state as core_build_fit_runtime_state,
    fit_form_for_league as core_fit_form_for_league,
    fit_players_context_for_league as core_fit_players_context_for_league,
    fit_players_lane_for_league as core_fit_players_lane_for_league,
    fit_players_league_weight_for_league as core_fit_players_league_weight_for_league,
    fit_scales_for_league as core_fit_scales_for_league,
)
from app_core.ml_league_runtime_core import (
    MAJOR_LEAGUES as CORE_ML_MAJOR_LEAGUES,
    canon_league_display_label as core_canon_league_display_label,
    is_marginal_league_for_ml as core_is_marginal_league_for_ml,
    league_is_excluded as core_league_is_excluded,
    ml_league_conf_band as core_ml_league_conf_band,
    ml_marginal_band_profile as core_ml_marginal_band_profile,
    norm_league as core_norm_league,
    norm_league_key as core_norm_league_key,
    sanitize_ml_marginal_band_coeffs as core_sanitize_ml_marginal_band_coeffs,
    tier_from_league as core_tier_from_league,
)
from app_core.ml_league_inference_core import (
    infer_match_league_from_csv as core_infer_match_league_from_csv,
    infer_team_league_from_csv as core_infer_team_league_from_csv,
)
from app_core.ml_artifact_pricing_core import (
    mlcore_p_map_v2 as core_mlcore_p_map_v2,
    p_from_diff_points as core_p_from_diff_points,
    strength_breakdown as core_strength_breakdown,
    team_meta_from_artifact as _team_meta_from_artifact,
)
from mlcore.lines_engine import (
    build_profile,
    filter_team_games,
    matchup_expected_totals,
    simulate_series_total,
    total_over_prob,
    normalize_map_mode,
    _combine_mean,
    _combine_sd,
    MatchupTotals,
)
from app_core.window_blend_core import (
    GERAL_WINDOWS as _GERAL_WINDOWS,
    blend_matchup_totals as _blend_matchup_totals,
    geral_window_weight as _geral_window_weight,
)
from mlcore.state_team_artifact import (
    load_team_state_artifact as core_load_team_state_artifact,
)

from mlcore.stats_teams import Filters, build_team_games, load_team_rows, apply_filters

from app_core.text_normalization import (
    _fix_mojibake_text,
    _normalize_text_key,
    _canonicalize_tab_labels,
    _patch_streamlit_text_rendering,
)
from app_core.params_tab_core import render_params_tab as _render_params_tab
from app_core.visao_tab_core import render_visao_tab as _render_visao_tab
from app_core.consistencia_tab_core import render_consistencia_tab as _render_consistencia_tab

# NOTE: plays_app passa ctx=globals() para render_visao_tab, que lê dezenas de
# core_* via ctx.get("core_x"). Esses imports são "usados" só por string —
# ferramentas de lint (F401) não enxergam o uso. Mantidos abaixo com noqa.
# fmt: off
from app_core.confidence_governor_core import apply_confidence_governor as core_apply_confidence_governor
from app_core.consistency_ui_core import render_stateful_tab_selector as core_render_stateful_tab_selector
from app_core.lineup_runtime_core import (
    autofill_lineup_state as core_autofill_lineup_state,
    build_manual_lineup_choices as core_build_manual_lineup_choices,
    build_ml_lineup_choices as core_build_ml_lineup_choices,
    resolve_players_layer_config as core_resolve_players_layer_config,
    score_manual_lineup_team as core_score_manual_lineup_team,
)
from app_core.lineup_ui_core import render_lineup_selector_column as core_render_lineup_selector_column
from app_core.ml_explainability_core import (
    build_confidence_summary as core_build_confidence_summary,
    build_pipeline_explainability as core_build_pipeline_explainability,
    build_pipeline_step_rows as core_build_pipeline_step_rows,
)
from app_core.ml_live_feature_trace_core import append_ml_live_feature_traces as core_append_ml_live_feature_traces
from app_core.ml_orchestrator_core import run_ml_post_layers as core_run_ml_post_layers
from app_core.ml_pre_pipeline_core import run_ml_pre_pipeline as core_run_ml_pre_pipeline
from app_core.ml_session_runtime_core import (
    get_wf_ml_corr_info as core_get_wf_ml_corr_info,
    set_latest_ml_trace as core_set_latest_ml_trace,
    set_ml_scope as core_set_ml_scope,
)
from app_core.ml_shadow_feature_trace_core import append_ml_shadow_feature_traces as core_append_ml_shadow_feature_traces
from app_core.ml_shadow_layers_core import run_ml_shadow_layers as core_run_ml_shadow_layers
from app_core.ml_trace_payload_core import build_ml_trace_payload as core_build_ml_trace_payload
from app_core.runtime_session_state_core import get_lv_last_report as core_get_lv_last_report
from app_core.state_strength_areal_core import compute_state_shadow_areal as core_compute_state_shadow_areal
from app_core.state_strength_core import compute_state_shadow_alite as core_compute_state_shadow_alite
from app_core.visao_geral_ml_pipeline_core import (
    build_ml_trace_context as core_build_ml_trace_context,
    build_pre_engine_input as core_build_pre_engine_input,
    build_pre_live_input as core_build_pre_live_input,
    build_runtime_input_signature as core_build_runtime_input_signature,
    persist_runtime_analysis_state as core_persist_runtime_analysis_state,
    unpack_post_layer_output as core_unpack_post_layer_output,
    unpack_shadow_output as core_unpack_shadow_output,
)
from app_core.visao_geral_runtime_core import (
    apply_runtime_tuning_to_session as core_apply_runtime_tuning_to_session,
    build_microseg_caption as core_build_microseg_caption,
    resolve_shared_league_hint as core_resolve_shared_league_hint,
)
from mlcore.fusion_core import (
    current_season_override as core_current_season_override,
    hybrid_momentum_blend as core_hybrid_momentum_blend,
    season_form_blend as core_season_form_blend,
)
from mlcore.roster_signal_core import (
    lineup_continuity_from_details as core_lineup_continuity_from_details,
    transfer_signal_from_details as core_transfer_signal_from_details,
)
from mlcore.series_bo_core import (
    apply_series_bo_dplite_live as core_apply_series_bo_dplite_live,
    enforce_series_economic_coherence as core_enforce_series_economic_coherence,
)
from app_core.analysis_runtime_state_core import ml_consistency_signature as _ml_consistency_signature
from app_core.consistency_core import (
    build_audit_base_options as core_build_audit_base_options,
    build_audit_market_options as core_build_audit_market_options,
    build_audit_view as core_build_audit_view,
    build_ml_totals_laplace_payload as core_build_ml_totals_laplace_payload,
    build_ml_totals_model_payload as core_build_ml_totals_model_payload,
    build_quick_metric_options as core_build_quick_metric_options,
    build_quick_selector_rows as core_build_quick_selector_rows,
    build_simple_audit_view as core_build_simple_audit_view,
    has_metric_history as core_has_metric_history,
    quick_outcome_probs as core_quick_outcome_probs,
    quick_team_frame as core_quick_team_frame,
)
from app_core.consistency_ui_core import (
    render_market_context_hero as core_render_market_context_hero,
    render_market_context_panel as core_render_market_context_panel,
    render_market_mode_section as core_render_market_mode_section,
    render_summary_block as core_render_summary_block,
)
from app_core.display_tables_core import totals_table as _totals_table
from app_core.lineup_state import (
    POS_CANON_ML as _POS_CANON_ML,
    lineup_key as _lineup_key,
    safe_key as _safe_key,
)
from app_core.market_stats_ui_core import render_market_stats_tab as core_render_market_stats_tab
from app_core.ml_confidence_scoring_core import ml_confidence_from_layer_validation as _ml_confidence_from_layer_validation
from app_core.ml_probability_adjustments_core import (
    _safe_logit,
    _safe_sigmoid,
    apply_series_gamma as _apply_series_gamma,
)
from app_core.ml_session_runtime_core import get_ml_scope as core_get_ml_scope
from app_core.odds_core import (
    event_block as core_event_block,
    laplace_odds as core_laplace_odds,
    ou_block as core_ou_block,
)
from app_core.opponent_profile_ui_core import render_opponent_profile_tab as core_render_opponent_profile_tab
from app_core.players_elo_core import delta_players_effect as _delta_players_effect
from app_core.quick_selector_ui_core import render_quick_selector_controls as core_render_quick_selector_controls
from app_core.ui_labels import MARKET_TAB_NAMES as _MARKET_TAB_NAMES
from mlcore.players_layer import compute_delta_and_confidence
from mlcore.tiers import tier_priority
from app_core.ml_output_models import MlPrePipelineOutput as CoreMlPrePipelineOutput
from mlcore.utils import safe_float_or_none as _fnum
# fmt: on
from app_core.global_css_core import inject_global_ui_css as _inject_global_ui_css
from app_core.global_banners_ui_core import (
    render_global_feature_trace_banner as _render_global_feature_trace_banner,
    render_global_maintenance_banner as _render_global_maintenance_banner,
)
from app_core.calibracoes_ui_core import render_calibracoes as _render_calibracoes
from app_core.csv_bootstrap_flow_core import (
    csv_bootstrap_gate as _csv_bootstrap_gate_flow,
    collect_maintenance_status as _collect_maintenance_status_flow,
    run_auto_maintenance_now as _run_auto_maintenance_now_flow,
)
from app_core.odds_cards_ui_core import render_odds_cards as _render_odds_cards_core
from app_core.achievements_resolve_core import ach_layer_for_artifact as _ach_layer_for_artifact_core
from app_core.rank_table_core import mlcore_rank_table_v2 as _mlcore_rank_table_v2_core
from app_core.team_state_persist_core import generate_and_persist_team_state_artifact as _generate_and_persist_team_state_artifact_core
from app_core.elo_matchup_core import elo_season_players_p_map as _elo_season_players_p_map_core
from app_core.backup_core import backup_file_if_exists as _backup_file_if_exists_core
from app_core.calibrate_p_core import calibrate_p_from_artifact as _calibrate_p_from_artifact_core
from app_core.patch_guard_core import patch_meta_guard_payload as _patch_meta_guard_payload_core, patch_changed_leagues_set as _patch_changed_leagues_set_core
from app_core.lines_table_core import lines_table as _lines_table_core, lines_table_with_p_ml as _lines_table_with_p_ml_core
from app_core.series_totals_core import series_totals_table as _series_totals_table_core
from app_core.confidence_runtime_core import (
    load_confidence_baseline_runtime as _load_confidence_baseline_runtime_core,
    series_gamma_for_league as _series_gamma_for_league_core,
    runtime_confidence_governor_budget_for_league as _runtime_confidence_governor_budget_for_league_core,
    runtime_series_coherence_post_cap_for_league as _runtime_series_coherence_post_cap_for_league_core,
)
from app_core.ml_confidence_baseline_persist_core import generate_and_persist_ml_confidence_baseline as _generate_and_persist_ml_confidence_baseline_core
from app_core.feature_trace_append_core import append_feature_trace as _append_feature_trace_core
from app_core.players_artifact_runtime_core import resolve_runtime_players_artifact_path as _resolve_runtime_players_artifact_path_core


# Helpers movidos p/ runtime_wrappers_core (fatiamento 18/07); re-importados
# aqui para o namespace/ctx do app seguir idêntico.
from app_core.runtime_wrappers_core import (  # noqa: E402,F401 - re-export
    _clear_streamlit_cache_data,
    _df_contract_view,
    _ensure_lineup_runtime_state,
    _expected_totals_dc,
    _feature_flag_enabled,
    _get_lineup_loaded_key,
    _get_lineup_runtime_settings,
    _get_lineup_selected,
    _league_macro_key,
    _lines_table,
    _lines_table_with_p_ml,
    _load_lineup_for_matchup,
    _render_odds_cards,
    _request_streamlit_rerun,
    _save_lineup_for_matchup,
    _set_lineup_loaded_key,
)


# _team_with_league_label imported from app_core.matchup_selection_core









_patch_streamlit_text_rendering()


# -----------------------------
# App settings (persistência em disco)
# -----------------------------
# Config de persistência movida p/ app_settings_config_core (fatiamento
# 18/07); re-importada aqui para o namespace/ctx seguir idêntico.
from app_core.app_settings_config_core import (  # noqa: E402 - re-export
    _SETTINGS_FILE,
    _PERSIST_KEYS,
)

def _settings_path() -> Path:
    return core_settings_path(Path(__file__).resolve().parent, _SETTINGS_FILE)

def _load_app_settings_from_disk() -> Dict[str, Any]:
    return core_load_settings_from_disk(_settings_path(), date_keys=("ml_as_of_date",))

def _apply_settings_to_session(settings: Dict[str, Any], force: bool = False) -> None:
    core_apply_settings_to_session(st.session_state, settings or {}, persist_keys=_PERSIST_KEYS, force=bool(force))

def _save_app_settings_to_disk() -> None:
    core_save_settings_to_disk(_settings_path(), st.session_state, persist_keys=_PERSIST_KEYS)

_STATE_SCHEMA = core_get_state_schema()
_PARAM_DEFAULTS: Dict[str, Any] = core_build_runtime_param_defaults(_STATE_SCHEMA.get("defaults", {}))
_STATE_MIGRATIONS: Dict[str, str] = dict(_STATE_SCHEMA.get("migrations", {}))
_STATE_CONSTRAINTS: Dict[str, Tuple[float, float]] = dict(_STATE_SCHEMA.get("constraints", {}))

_SHARED_ML_DEFAULTS: Dict[str, Any] = core_shared_ml_defaults()

# Bootstrap central de estado (defaults + migrações + saneamento).
core_bootstrap_state(
    st.session_state,
    defaults=_PARAM_DEFAULTS,
    migrations=_STATE_MIGRATIONS,
    constraints=_STATE_CONSTRAINTS,
)

# Defaults locais (não dependem de schema externo).
_LOCAL_DEFAULTS: Dict[str, Any] = core_local_runtime_defaults()
for _k, _v in _LOCAL_DEFAULTS.items():
    st.session_state.setdefault(_k, _v)
st.session_state.setdefault("auto_maint_fast_mode", True)
st.session_state.setdefault("auto_maint_run_layer_validation", False)
st.session_state.setdefault("auto_maint_force_fast", True)
st.session_state.setdefault("auto_maint_force_full", False)
st.session_state.setdefault("auto_maint_fast_new_games_max", 30)
st.session_state.setdefault("auto_maint_cmd_timeout_s", 1200)
st.session_state.setdefault("auto_maint_params_timeout_s", 14000)
st.session_state.setdefault("auto_maint_lock_ttl_s", 600)


def _reset_all_tuning_to_defaults() -> None:
    core_apply_recommended_preset(st.session_state, "Padrão")
    for k, v in _PARAM_DEFAULTS.items():
        st.session_state[k] = v


def _render_settings_sidebar() -> None:
    core_render_settings_sidebar(
        save_settings_fn=_save_app_settings_to_disk,
        settings_path=_settings_path(),
    )


def _process_pending_settings_actions() -> None:
    core_process_pending_settings_actions(
        st.session_state,
        load_settings_fn=_load_app_settings_from_disk,
        apply_settings_fn=_apply_settings_to_session,
        apply_recommended_preset_fn=lambda prof: core_apply_recommended_preset(st.session_state, profile=prof),
        apply_excellent_preset_fn=lambda: core_apply_excellent_value_preset(st.session_state),
        apply_twenty_ten_preset_fn=lambda: core_apply_twenty_ten_preset(st.session_state),
        reset_all_tuning_fn=_reset_all_tuning_to_defaults,
        param_defaults=_PARAM_DEFAULTS,
    )


def _init_app_settings_once() -> None:
    core_init_settings_once(
        st.session_state,
        load_settings_fn=_load_app_settings_from_disk,
        apply_settings_fn=_apply_settings_to_session,
        process_pending_fn=_process_pending_settings_actions,
    )


# -----------------------------
# Helpers
# -----------------------------
# Helpers movidos p/ artifact_loaders_core (fatiamento 18/07); re-importados
# aqui para o namespace/ctx do app seguir idêntico.
from app_core.artifact_loaders_core import (  # noqa: E402,F401 - re-export
    _artifact_sig,
    _file_sig,
    _load_achievements_cached,
    _load_artifact_cached,
    _load_fitted_params_cached,
    _load_league_transfer_features_cached,
    _load_ml_confidence_baseline_cached,
    _load_players_artifact_cached,
    _load_players_impact,
    _load_team_state_artifact_cached,
    _patch_changed_leagues_set,
    _resolve_relpath,
)




@st.cache_data(show_spinner=False)
def _csv_header_check(csv_sig: Tuple[str, int, int]) -> Dict[str, Any]:
    csv_path, _size, _mtime = csv_sig
    return core_csv_header_check_path(csv_path)




def _csv_bootstrap_gate(
    *,
    csv_path: str,
    hist_csvs: Optional[List[str]] = None,
    artifact_path: str = "",
) -> None:
    """Tela separada de preparo do CSV + manuten\u00e7\u00e3o autom\u00e1tica quando o CSV muda."""
    # Fecho cross-módulo (força-tarefa 23/07): o gate repassa ctx para
    # ensure_csv_runtime_ready E collect_maintenance_status. Auto-derivado das
    # fontes dos 3 módulos do fecho (nenhum vai mais fundo) — completo e sem
    # lista de 31 nomes na mão.
    return _csv_bootstrap_gate_flow(csv_path=csv_path, hist_csvs=hist_csvs, artifact_path=artifact_path, st=st, ctx=_pick_ctx_from_modules(
        "app_core.csv_bootstrap_flow_core", "app_core.csv_runtime_ready_core",
        "app_core.csv_maintenance_runner_core"))



@st.cache_data(show_spinner=False)
def _csv_diag(csv_sig: Tuple[str, int, int]) -> Dict[str, Any]:
    csv_path, _size, _mtime = csv_sig
    return core_csv_diag_path(csv_path)



@st.cache_data(show_spinner=False)
def _load_team_games(csv_sig: Tuple[str, int, int]) -> pd.DataFrame:
    csv_path, _size, _mtime = csv_sig
    rows = load_team_rows(csv_path)
    df = build_team_games(rows)

    # Anotações manuais de fase (ex.: EWC qualify vs main) — define `split` por
    # liga+intervalo de datas. NO-OP enquanto competition_phases.json tiver
    # 'rules' vazio. (Cache: editar o JSON exige rerun/limpar cache.)
    try:
        from app_core.competition_phases_core import (
            apply_competition_phases,
            apply_ewc_regional_phases,
        )
        # Automático: rotula jogos da EWC por qualifier regional (intra-região →
        # "Qualify KR/NA/EU/APAC/CN") vs evento principal (cross-região → "Main").
        df = apply_ewc_regional_phases(df)
        # Manual: regras extras por liga+data (no-op enquanto o JSON estiver vazio).
        df = apply_competition_phases(df, path=Path(__file__).resolve().parent / "competition_phases.json")
    except Exception:
        pass

    # Canonicaliza nomes de times para evitar que capitalização diferente (ex.: "Kia" vs "KIA")
    # faça o mesmo time aparecer como se fosse outro e caia em liga errada no modo auto.
    maps = _team_canon_maps(csv_sig)
    key_to_best = maps.get("variant_to_best_key") if isinstance(maps, dict) else None
    if isinstance(key_to_best, dict) and len(key_to_best) > 0 and "team" in df.columns:
        def _canonize_name(x: Any) -> str:
            s = ("" if x is None else str(x)).strip()
            s = re.sub(r"\s+", " ", s)
            k = _canon_team_key(s)
            return str(key_to_best.get(k, s))
        df["team"] = df["team"].map(_canonize_name)
        if "opponent" in df.columns:
            df["opponent"] = df["opponent"].map(_canonize_name)
    # Canonicaliza ligas em aliases conhecidos (ex.: CCWS -> PRM) para não fragmentar filtros/rankings.
    if "league" in df.columns:
        df["league"] = df["league"].map(core_canon_league_display_label)
    # EWC: divide por região (KR/EU/CN/NA/...), inferida da liga nativa de cada time.
    from app_core.ewc_region_split import annotate_ewc_region_split
    df = annotate_ewc_region_split(df)
    return df
# _canon_team_key imported from app_core.matchup_selection_core


@st.cache_data(show_spinner=False)




@st.cache_data(show_spinner=False)
def _list_teams(csv_sig: Tuple[str, int, int]) -> List[str]:
    maps = _team_canon_maps(csv_sig)
    teams = maps.get("best_list") if isinstance(maps, dict) else None
    if not isinstance(teams, list) or len(teams) == 0:
        # fallback (não deveria acontecer)
        csv_path, _size, _mtime = csv_sig
        rows = load_team_rows(csv_path)
        teams = sorted(rows["teamname"].dropna().unique().tolist())
    return teams


@st.cache_data(show_spinner=False)
def _liga_por_time(csv_sig: Tuple[str, int, int]) -> Dict[str, str]:
    """Time -> liga em que ele joga nesta season.

    POR QUE (16/09/2026): a agenda trouxe "UP2U Meavedron" num jogo do
    Hitpoint Masters, e a lista de palpites ofereceu em PRIMEIRO "UP2UMEDIA
    Cebulaki" -- time POLONES, de outra liga, com 4 jogos de historico. Ele
    escolheu, e a analise saiu inteira sobre o time errado. Nome parecido
    entre ligas nao e coincidencia: e o mesmo patrocinador em paises
    diferentes. A liga desempata.

    Quando um time aparece em mais de uma liga fica a que ele mais jogou.
    """
    csv_path, _size, _mtime = csv_sig
    rows = load_team_rows(csv_path)
    fora: Dict[str, str] = {}
    try:
        contagem = rows.groupby(["teamname", "league"]).size().reset_index(name="n")
        contagem = contagem.sort_values("n", ascending=False)
        for _, linha in contagem.iterrows():
            nome = str(linha["teamname"])
            if nome and nome not in fora:
                fora[nome] = str(linha["league"])
    except (KeyError, ValueError, TypeError):
        return {}
    return fora


@st.cache_data(show_spinner=False)
def _load_player_rows(csv_sig: Tuple[str, int, int]) -> pd.DataFrame:
    """Carrega rows de players (participantid 1..10) do OracleElixir."""
    csv_path, _size, _mtime = csv_sig
    return core_load_player_rows(
        csv_path=str(csv_path),
        canon_league_display_label_fn=core_canon_league_display_label,
        norm_pos_ml_fn=_norm_pos_ml,
    )



# _stable_seed_from_parts, _ml_consistency_signature imported from app_core.analysis_runtime_state_core


@st.cache_data(show_spinner=False)
def _series_sims_cached(
    bo: int,
    p_blue_map: float,
    total_obj,
    n_sims: int,
    seed: int = 1337,
) -> np.ndarray:
    """Cache Monte Carlo sims for series totals (per metric)."""
    # total_obj is a frozen dataclass (MatchupTotals), safe to cache by value.
    return simulate_series_total(
        bo=int(bo),
        p_blue_map=float(p_blue_map),
        total=total_obj,
        n_sims=int(n_sims),
        seed=int(seed),
    )


# -----------------------------
# ML core v2: carregar artifact, calcular total_strength, ML e ranking
# -----------------------------



















@st.cache_data(show_spinner=False)
def _patch_meta_guard_payload(
    csv_sig: Tuple[str, int, int],
    fit_sig: Tuple[str, int, int],
) -> Dict[str, Any]:
    return _patch_meta_guard_payload_core(csv_sig, fit_sig, ctx={"_load_fitted_params_cached": _load_fitted_params_cached})





def _ach_layer_for_artifact(art: MLArtifact, artifact_path: str, ach_override_path: Optional[str] = None) -> Dict[str, Any]:
    return _ach_layer_for_artifact_core(art, artifact_path, ach_override_path, ctx={"_file_sig": _file_sig, "_load_achievements_cached": _load_achievements_cached})


# Helpers movidos p/ ml_adjust_helpers_core (fatiamento 18/07); re-importados
# aqui para o namespace/ctx do app seguir idêntico.
from app_core.ml_adjust_helpers_core import (  # noqa: E402,F401 - re-export
    _apply_ml_marginal_trust_adjust,
    _apply_ml_uncertainty_adjust,
    _fuse_probs_by_precision,
    _p_from_diff_points,
    _strength_breakdown,
    _wf_correct_p_map,
)




# -----------------------------
# Helpers: infer league/tier for ML core v2 (to avoid artifact mislabeling)
# -----------------------------
# Bloco movido p/ ml_league_pricing_runtime_core (fatiamento 16/08/2026).
# RE-IMPORTADO aqui porque o padrao globals()->ctx exige os nomes visiveis
# neste namespace: sem isso as abas recebem None e quebram longe daqui.
from app_core.ml_league_pricing_runtime_core import (  # noqa: F401 - ctx
    _MAJOR_LEAGUES,
    _load_identity_registry_cached,
    _identity_registry_sig,
    _identity_team_name_candidates,
    _identity_team_league_candidates,
    _league_inference_csv_sigs,
    _infer_team_league_from_csv,
    _infer_match_league_from_csv,
    _mlcore_p_map_v2,
    _build_ml_microseg_table,
    _apply_ml_microseg_calibration,
    configurar_runtime as _configurar_ml_league_runtime,
)








# -----------------------------
# ML engine alternativo: Elo season (time) + Elo global (players)
# -----------------------------


@st.cache_data(show_spinner=False)
def _load_player_rows_multi_cached(sig_list: Tuple[Tuple[str, int, int], ...]) -> pd.DataFrame:
    return core_load_player_rows_multi(
        sig_list=sig_list,
        load_player_rows_fn=_load_player_rows,
    )



@st.cache_data(show_spinner=False)
def _compute_player_elo_global_cached(
    sig_list: Tuple[Tuple[str, int, int], ...],
    *,
    half_life_days: float,
    k_player: float,
    shrink_m: float,
    base_rating: float = 1500.0,
    scale: float = 400.0,
) -> Dict[str, Any]:
    return core_compute_player_elo_global(
        sig_list=sig_list,
        load_player_rows_multi_fn=_load_player_rows_multi_cached,
        half_life_days=half_life_days,
        k_player=k_player,
        shrink_m=shrink_m,
        base_rating=base_rating,
        scale=scale,
    )




def _elo_season_players_p_map(
    *,
    team_games: pd.DataFrame,
    csv_path: str,
    teamA: str,
    teamB: str,
    filters: Filters,
    team_half_life_days: float,
    player_half_life_days: float,
    k_team: float,
    k_player: float,
    shrink_m: float,
    w_players: float,
    base_rating: float = 1500.0,
    scale: float = 400.0,
) -> Dict[str, Any]:
    return _elo_season_players_p_map_core(
        team_games=team_games,
        csv_path=csv_path,
        teamA=teamA,
        teamB=teamB,
        filters=filters,
        team_half_life_days=team_half_life_days,
        player_half_life_days=player_half_life_days,
        k_team=k_team,
        k_player=k_player,
        shrink_m=shrink_m,
        w_players=w_players,
        base_rating=base_rating,
        scale=scale,
        ctx=_pick_ctx("_file_sig", "_compute_player_elo_global_cached", "core_discover_player_csv_paths"),
        st=st,
    )



def _mlcore_rank_table_v2(artifact_path: str, as_of: date, top_n: int = 200) -> pd.DataFrame:
    # rank_table_v2 repassa ctx para ach_layer_for_artifact (achievements_resolve_
    # core), que lê _load_achievements_cached — por isso a 3ª chave entra (fecho
    # cross-módulo; achievements não repassa adiante).
    return _mlcore_rank_table_v2_core(artifact_path, as_of, top_n, ctx=_pick_ctx(
        "_file_sig", "_load_artifact_cached", "_load_achievements_cached"))




# -----------------------------
# Linhas por confronto (persistem enquanto os times não mudam)
# -----------------------------


# Persistência das linhas (para não perder ao fechar o app)
_LINES_STORE_DEFAULTS_KEY = "__defaults__"  # padrão global (fallback quando o confronto não tem linhas salvas)
_LINES_STORE_FILE = Path(__file__).resolve().parent / "user_lines_store.json"


def _load_lines_store_disk() -> dict:
    return load_json_store(_LINES_STORE_FILE)


def _persist_lines_store_disk(store: dict) -> None:
    persist_json_store(_LINES_STORE_FILE, store)


def _lines_store() -> dict:
    # Session-only: NOT seeded from disk. Every new session starts with no saved
    # lines, so each matchup opens with the standard default lines. The store
    # still carries the lines the user types from the fill step into the Resumo
    # within the SAME analysis. (User decision 2026-06-02: "sempre padrão".)
    return ensure_session_store(st.session_state, "_lines_store", {})


def _load_lines_for_matchup(key: str) -> None:
    _load_lines_for_matchup_impl(st.session_state, _lines_store(), key, defaults_key=_LINES_STORE_DEFAULTS_KEY)


def _save_lines_for_matchup(key: str) -> None:
    # Update the session store only — no disk persistence (lines are session-only).
    store = _lines_store()
    _save_lines_for_matchup_impl(st.session_state, store, key)


# -----------------------------
# Lineup (Players) — store + scoring (ajuste do ML)
# -----------------------------


















_apply_shrink_m = core_apply_shrink_m
_best_match = core_best_match


def _latest_lineup_for_team(
    df_player_rows: pd.DataFrame,
    team: str,
    filters: Filters,
    league_fixed: str | None = None,
    *,
    pos_col: str = "pos",
    player_col: str = "player",
    pos_list: list[str] | None = None,
) -> dict:
    return core_latest_lineup_for_team(
        df_player_rows=df_player_rows,
        team=team,
        filters=filters,
        league_fixed=league_fixed,
        pos_col=pos_col,
        player_col=player_col,
        pos_list=(pos_list or list(_POS_CANON)),
        norm_pos_fn=_norm_pos,
        norm_pos_ml_fn=_norm_pos_ml,
    )


def _calibrate_p_from_artifact(artifact_path: str, p_raw: float) -> float:
    # Contrato explícito (força-tarefa 23/07): calibrate_p_from_artifact lê só
    # estas 2 chaves e não repassa ctx. NameError alto se um import sumir.
    return _calibrate_p_from_artifact_core(
        artifact_path, p_raw,
        ctx={"_file_sig": _file_sig, "_load_artifact_cached": _load_artifact_cached},
    )




# -----------------------------
# Ranking (força tipo ML) - Elo com recência (half-life)
# -----------------------------

def _elo_rank_table(
    team_games: pd.DataFrame,
    *,
    filters: Filters,
    half_life_days: float,
    k_factor: float = 24.0,
    base_rating: float = 1500.0,
    scale: float = 400.0,
) -> pd.DataFrame:
    return _elo_rank_table_core(
        team_games,
        filters=filters,
        half_life_days=half_life_days,
        k_factor=k_factor,
        base_rating=base_rating,
        scale=scale,
        format_pct_fn=_format_pct,
        format_num_fn=_format_num,
    )
# -----------------------------
# Helpers de exibição (tirar colunas irrelevantes)
# -----------------------------


def _display_ou_table(df: pd.DataFrame) -> pd.DataFrame:
    return core_display_ou_table(
        df,
        df_contract_view_fn=_df_contract_view,
        format_pct_fn=_format_pct,
        format_num_fn=_format_num,
    )


def _display_ml_totals_table(df: pd.DataFrame, team_label: Optional[str] = None) -> pd.DataFrame:
    return core_display_ml_totals_table(
        df,
        df_contract_view_fn=_df_contract_view,
        format_pct_fn=_format_pct,
        format_num_fn=_format_num,
        team_label=team_label,
    )












# _format_pct (fmt_prob_pct), _format_num (fmt_num) imported from app_core.ui_labels





# _totals_table imported from app_core.display_tables_core

def _series_totals_table(tot_avg) -> pd.DataFrame:
    return _series_totals_table_core(tot_avg, st=st, ctx=_pick_ctx(
        "_series_sims_cached", "bo", "n_sims", "p_map_cal", "totals_mode"))


# -----------------------------
# UI (fluxo: Times -> Linhas -> Resultados)
# -----------------------------
st.set_page_config(page_title="Plays (ML + Totais)", layout="wide")
_inject_global_ui_css(st)

# Hydrate session_state from persisted preferences (silent on first run)
try:
    from app_core.ui_state_persistence_core import sync_session_with_persistence as _sync_persist
    _sync_persist(st.session_state)
except Exception:
    pass
st.markdown(
    """
<div class="gb-hero">
  <div class="title">GABINETE</div>
  <div class="sub">dev: Bolin</div>
</div>
    """,
    unsafe_allow_html=True,
)
st.caption("Fluxo: escolher Season/Times -> preencher linhas -> ver resultados (modelo + histórico).")

APP_ROOT = Path(__file__).resolve().parent

# Configura o modulo fatiado em 16/08/2026. TEM que vir depois do APP_ROOT:
# o bloco original ficava ANTES dele e so o usava em tempo de execucao, dentro
# das funcoes — ao virar chamada de topo, a ordem passou a importar.
_configurar_ml_league_runtime(
    app_root=APP_ROOT,
    load_team_games=_load_team_games,
    ach_layer_for_artifact=_ach_layer_for_artifact,
)
_FIT_PARAMS_PATH = APP_ROOT / "params_fitted.json"
_ODDS_ANCHOR_BASELINE_PATH = APP_ROOT / "odds_anchor_baseline.json"
_TEAM_STATE_ARTIFACT_PATH = APP_ROOT / "team_state_artifact.json"
_ML_CONFIDENCE_BASELINE_PATH = APP_ROOT / "ml_confidence_baseline.json"
_LEAGUE_TRANSFER_FEATURES_PATH = APP_ROOT / "league_transfer_features.json"
_WF_LAST_REPORT_PATH = APP_ROOT / "wf_last_report.json"
_LV_LAST_REPORT_PATH = APP_ROOT / "lv_last_report.json"
_CSV_BOOTSTRAP_MAINT_CACHE_PATH = APP_ROOT / "csv_bootstrap_maintenance_cache.json"
_CSV_BOOTSTRAP_MAINT_LOCK_PATH = APP_ROOT / "csv_bootstrap_maintenance.lock.json"
_CSV_BOOTSTRAP_MAINT_STATE_PATH = APP_ROOT / "csv_bootstrap_maintenance_state.json"


# _compute_anchor_snapshot imported from app_core.anchor_snapshot_core


def _persist_combined_trace_file() -> None:
    """Persist unified trace (ml base + resumo markets + players) into ml_trace_last.json."""
    try:
        core_persist_combined_trace_file(
            st.session_state,
            app_root=APP_ROOT,
            build_combined_trace_fn=core_build_combined_trace,
            app_version="gabinete-2026.02.12",
        )
    except (OSError, TypeError, ValueError):
        pass

_fit_cfg = {}
try:
    if _FIT_PARAMS_PATH.exists():
        _fit_cfg = _load_fitted_params_cached(_file_sig(str(_FIT_PARAMS_PATH))) or {}
except (OSError, TypeError, ValueError, json.JSONDecodeError):
    _fit_cfg = {}

_fit_form_cfg: Dict[str, Any] = {}
_fit_form_cfg = core_apply_fit_runtime_state_to_session(
    st.session_state,
    _fit_cfg,
    build_fit_runtime_state_fn=core_build_fit_runtime_state,
    sanitize_marginal_band_coeffs_fn=core_sanitize_ml_marginal_band_coeffs,
)

def _fit_runtime_snapshot() -> Dict[str, Any]:
    return core_get_fit_runtime_snapshot(st.session_state)

def _fit_scales_for_league(league_hint: str) -> tuple[float, float, str]:
    _fit_rt = _fit_runtime_snapshot()
    return core_fit_scales_for_league(
        _fit_cfg,
        float(_fit_rt.get("_fit_team_scale", 1.0) or 1.0),
        float(_fit_rt.get("_fit_players_scale", 1.0) or 1.0),
        league_hint,
    )


def _fit_form_for_league(league_hint: str) -> tuple[Dict[str, Any], str]:
    return core_fit_form_for_league(
        _fit_cfg,
        _fit_form_cfg,
        league_hint,
        league_macro_key_fn=_league_macro_key,
    )


def _fit_players_lane_for_league(league_hint: str) -> tuple[Dict[str, float], str]:
    _fit_rt = _fit_runtime_snapshot()
    return core_fit_players_lane_for_league(
        _fit_rt.get("_fit_lane_weights_cfg"),
        league_hint,
        league_macro_key_fn=_league_macro_key,
    )


def _fit_players_league_weight_for_league(league_hint: str) -> tuple[float, str]:
    _fit_rt = _fit_runtime_snapshot()
    return core_fit_players_league_weight_for_league(
        _fit_rt.get("_fit_players_league_weights_cfg"),
        league_hint,
        league_macro_key_fn=_league_macro_key,
    )


def _fit_players_context_for_league(league_hint: str) -> tuple[Dict[str, Any], str]:
    _fit_rt = _fit_runtime_snapshot()
    return core_fit_players_context_for_league(
        _fit_rt.get("_fit_players_context_cfg"),
        league_hint,
        league_macro_key_fn=_league_macro_key,
    )



def _apply_fused_post_calibration(
    p_map_cal: float,
    *,
    league_hint: str,
    use_fitted: bool = True,
) -> tuple[float, Dict[str, Any]]:
    _fit_rt = _fit_runtime_snapshot()
    return core_apply_fused_post_calibration(
        p_map_cal,
        _fit_rt.get("_fit_fused_post_cal_cfg"),
        league_hint=league_hint,
        use_fitted=use_fitted,
    )


def _series_gamma_for_league(league_hint: str, bo: int) -> tuple:
    # series_gamma_for_league lê tudo de st.session_state e IGNORA o ctx
    # (confirmado no core) — nada a vazar aqui.
    return _series_gamma_for_league_core(league_hint, bo, st=st, ctx={})


def _confidence_runtime_ctx() -> Dict[str, Any]:
    """Contrato EXPLÍCITO das funções de confidence-runtime (ex-`ctx=globals()`).

    Força-tarefa 23/07: em vez de vazar o namespace inteiro, declaramos as 4
    chaves que a árvore de chamada de fato usa (o governor/coherence repassam o
    ctx para load_confidence_baseline_runtime — por isso as 3 do baseline entram
    junto). Se algum destes imports/globais sumir, isto estoura NameError AQUI e
    AGORA, em vez de virar None calado lá dentro."""
    return {
        "_ML_CONFIDENCE_BASELINE_PATH": _ML_CONFIDENCE_BASELINE_PATH,
        "_load_ml_confidence_baseline_cached": _load_ml_confidence_baseline_cached,
        "_file_sig": _file_sig,
        "_fit_cfg": _fit_cfg,
    }


def _load_confidence_baseline_runtime() -> Dict[str, Any]:
    return _load_confidence_baseline_runtime_core(ctx=_confidence_runtime_ctx())


def _runtime_confidence_governor_budget_for_league(
    league_hint: str,
    confidence_baseline: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return _runtime_confidence_governor_budget_for_league_core(league_hint, confidence_baseline, st=st, ctx=_confidence_runtime_ctx())


def _runtime_series_coherence_post_cap_for_league(
    *,
    league_hint: str,
    bo: int,
    confidence_baseline: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return _runtime_series_coherence_post_cap_for_league_core(league_hint=league_hint, bo=bo, confidence_baseline=confidence_baseline, st=st, ctx=_confidence_runtime_ctx())


def _boot_select_csvs(root: Path) -> None:
    core_render_bootstrap_selector(
        session_state=st.session_state,
        root=root,
        list_csv_candidates_fn=_list_csv_candidates,
        apply_bootstrap_selection_fn=core_apply_bootstrap_selection,
    )




# -----------------------------
# Boot: carregar config salva + sidebar (antes do fluxo)
# -----------------------------
_init_app_settings_once()
_render_settings_sidebar()

# Deferred save used by one-click profile actions in tuning UI.
if bool(st.session_state.pop("_pending_save_settings_after_apply", False)):
    _save_app_settings_to_disk()
    core_set_flash_saved_profile_msg(st.session_state, "Perfil aplicado e salvo como padrao.")


# Tela inicial (antes de qualquer fluxo)
_boot_select_csvs(APP_ROOT)

# Navegacao (centraliza calibracao/retreino em um lugar so)
_nav_options = list(NAV_TOP_NAV_OPTIONS)
_nav_main_cur = core_resolve_nav_page(st.session_state)
if str(st.session_state.get("nav_main", "") or "") not in _nav_options:
    st.session_state["nav_main"] = _nav_main_cur if _nav_main_cur in _nav_options else _nav_options[0]
nav_page = st.radio("Pagina", _nav_options, horizontal=True, key="nav_main")

def _reset_flow(keep_config: bool = True):
    core_reset_flow_state(st.session_state, keep_config=bool(keep_config))



# Aplica carregamentos pendentes ANTES de instanciar widgets (evita erro de session_state em widgets como BO)
core_apply_pending_load(st.session_state, reset_flow_fn=_reset_flow)
# -----------------------------
# Configurações (raramente muda)
# -----------------------------
seasons = _discover_season_csvs(APP_ROOT)
_runtime_cfg_defaults = core_build_runtime_config_defaults(st.session_state, app_root=APP_ROOT, seasons=seasons)

if nav_page == "Tecnico":
    core_render_technical_runtime_config_panel(
        session_state=st.session_state,
        seasons=seasons,
        runtime_cfg_defaults=_runtime_cfg_defaults,
        request_csv_runtime_refresh_fn=core_request_csv_runtime_refresh,
        reset_bootstrap_selection_fn=core_reset_bootstrap_selection,
    )




def _paths_for_ml(root: Path) -> tuple[str, list[str], str]:
    return core_resolve_ml_paths(st.session_state, root)


def _resolve_players_artifact_path(artifact_path: str, root: Path) -> str:
    return core_resolve_players_artifact_path(
        artifact_path,
        root,
        load_artifact_fn=lambda p: _load_artifact_cached(_artifact_sig(str(p))),
    )




def _append_feature_trace(
    *,
    feature: str,
    event: str,
    enabled=None,
    payload: Optional[Dict[str, Any]] = None,
    dedupe_signature: Optional[str] = None,
    max_items: int = 200,
    persist_files: bool = False,
) -> None:
    return _append_feature_trace_core(
        feature=feature, event=event, enabled=enabled, payload=payload,
        dedupe_signature=dedupe_signature, max_items=max_items,
        persist_files=persist_files, st=st,
        ctx={"APP_ROOT": APP_ROOT, "_persist_combined_trace_file": _persist_combined_trace_file},
    )



def _resolve_runtime_players_artifact_path(artifact_path: str) -> str:
    # Contrato explícito (força-tarefa 23/07): 3 chaves, sem repasse de ctx.
    return _resolve_runtime_players_artifact_path_core(
        artifact_path,
        ctx={"APP_ROOT": APP_ROOT, "_file_sig": _file_sig, "_load_artifact_cached": _load_artifact_cached},
    )


def _players_artifact_output_path(artifact_path: str) -> Path:
    resolved = Path(_resolve_runtime_players_artifact_path(str(artifact_path))).expanduser()
    try:
        if resolved.exists():
            return resolved
    except OSError:
        pass
    artifact_raw = str(artifact_path or "").strip()
    if artifact_raw:
        return Path(artifact_raw).expanduser().with_name("players_artifact.json")
    return APP_ROOT / "players_artifact.json"


def _maintenance_ctx() -> Dict[str, Any]:
    """Contrato explícito dos fluxos de manutenção (união das chaves do
    csv_maintenance_runner_core; ambos os fluxos leem deste conjunto)."""
    return _pick_ctx(
        "APP_ROOT", "_LV_LAST_REPORT_PATH", "_WF_LAST_REPORT_PATH",
        "_backup_file_if_exists", "_file_sig",
        "_generate_and_persist_ml_confidence_baseline",
        "_generate_and_persist_team_state_artifact", "_load_fitted_params_cached",
        "_load_team_state_artifact_cached", "_patch_meta_guard_payload",
        "_paths_for_ml", "_players_artifact_output_path",
        "_resolve_runtime_players_artifact_path", "_run_layer_validation_cached",
        "_run_walkforward_cached",
    )


def _collect_maintenance_status(csv_path_s: str, artifact_path_s: str) -> Dict[str, Any]:
    return _collect_maintenance_status_flow(csv_path_s, artifact_path_s, st=st, ctx=_maintenance_ctx())


def _run_auto_maintenance_now(
    csv_path_s: str,
    artifact_path_s: str,
    status=None,
    *,
    force_full: bool = False,
    progress_cb=None,
) -> Dict[str, Any]:
    return _run_auto_maintenance_now_flow(csv_path_s, artifact_path_s, status, force_full=force_full, progress_cb=progress_cb, st=st, ctx=_maintenance_ctx())


# Helpers movidos p/ diagnostics_helpers_core (fatiamento 18/07); re-importados
# aqui para o namespace/ctx do app seguir idêntico.
from app_core.diagnostics_helpers_core import (  # noqa: E402,F401 - re-export
    _enrich_params_with_ml_marginal_band_coeffs,
    _generate_and_persist_ml_confidence_baseline,
    _read_artifact_summary,
    _read_json_file_safe,
    _run_calibration_diag_cached,
    _run_cmd,
    _run_layer_validation_cached,
    _run_walkforward_cached,
)















def _backup_file_if_exists(path_like, *, tag: str = "manual") -> str:
    return _backup_file_if_exists_core(path_like, tag=tag, app_root=APP_ROOT)











def _generate_and_persist_team_state_artifact(
    *,
    root: Path,
    csv_paths: List[str],
    keep_playoffs: Optional[bool] = None,
) -> Dict[str, Any]:
    return _generate_and_persist_team_state_artifact_core(root=root, csv_paths=csv_paths, keep_playoffs=keep_playoffs, ctx={"_file_sig": _file_sig, "_load_fitted_params_cached": _load_fitted_params_cached})


def _run_daily_pipeline(
    root: Path,
    *,
    csv_path_s: str,
    artifact_path_s: str,
    run_smoke: bool = True,
    fast_mode: bool = True,
) -> Dict[str, Any]:
    return core_run_daily_pipeline(
        st.session_state,
        root,
        csv_path_s=csv_path_s,
        artifact_path_s=artifact_path_s,
        run_smoke=bool(run_smoke),
        fast_mode=bool(fast_mode),
        baseline_path=_ODDS_ANCHOR_BASELINE_PATH,
        paths_for_ml_fn=_paths_for_ml,
        resolve_players_artifact_path_fn=_resolve_players_artifact_path,
        compute_anchor_snapshot_fn=_compute_anchor_snapshot,
        fit_ml_params_run_fn=_fit_ml_params_run,
        enrich_params_with_areal_prob_tuning_fn=_enrich_params_with_areal_prob_tuning,
        run_layer_validation_cached_fn=_run_layer_validation_cached,
        run_calibration_diag_cached_fn=_run_calibration_diag_cached,
        run_walkforward_cached_fn=_run_walkforward_cached,
        load_fitted_params_cached_fn=_load_fitted_params_cached,
        file_sig_fn=_file_sig,
        generate_ml_confidence_baseline_fn=_generate_and_persist_ml_confidence_baseline,
        generate_team_state_artifact_fn=_generate_and_persist_team_state_artifact,
        run_pre_delivery_checks_fn=_run_pre_delivery_checks,
        clear_team_state_cache_fn=lambda: _load_team_state_artifact_cached.clear(),
    )






# _ml_confidence_from_layer_validation imported from app_core.ml_confidence_scoring_core


# Página Técnico (só aqui tem drift/retreino/update)
if nav_page == "Tecnico":
    # ctx explícito auto-derivado da fonte do renderer (força-tarefa 23/07):
    # sem repasse de ctx no core, então as chaves extraídas são completas.
    _render_calibracoes(APP_ROOT, st=st, ctx=_build_render_ctx(
        globals(), renderer_source=_inspect.getsource(_render_calibracoes),
        renderer_name="render_calibracoes", validate=False,
    ))
    st.stop()

# -----------------------------
# Etapa 1 — escolher Season + Times
# -----------------------------
_season_ctx = core_resolve_season_context(seasons, selected_label=str(st.session_state.get("season_label", "") or ""))
_season_options = list(_season_ctx.get("options") or ["S15"])
_season_default = _season_options[int(_season_ctx.get("selected_idx", 0) or 0)] if _season_options else "S15"
if str(st.session_state.get("season_label", "") or "") not in _season_options:
    st.session_state["season_label"] = _season_default
season_label = st.selectbox(
    "Temporada",
    _season_options,
    key="season_label",
)
_season_ctx = core_resolve_season_context(seasons, selected_label=str(season_label or ""))
season_info = dict(_season_ctx.get("season_info") or {})
season_year = int(_season_ctx.get("season_year", 2025) or 2025)

# Decide caminhos ativos
csv_path, artifact_path = core_resolve_active_csv_and_artifact(
    st.session_state,
    app_root=APP_ROOT,
    season_label=season_label,
    season_year=season_year,
    season_csv_path=str(season_info.get("csv_path") or ""),
    seasons_available=bool(_season_ctx.get("has_seasons", False)),
)

# Tela separada de preparo do CSV + manutenção automática quando houver troca.
_csv_bootstrap_gate(
    csv_path=csv_path,
    hist_csvs=core_get_boot_hist_csvs(st.session_state),
    artifact_path=artifact_path,
)

# Selo do modo visualização (nuvem): frescor dos dados no topo + upload de CSV.
from app_core.viewer_mode_core import render_csv_upload_panel as _render_csv_upload_panel
from app_core.viewer_mode_core import render_viewer_badge as _render_viewer_badge

# Nomes que a aba Parametros pede via ctx.get e que NUNCA chegaram ao
# globals() do plays_app (bug desde 02/06: 35 viravam None -> a aba
# quebrava no modo Completo). Import explicito conserta o contrato.
from app_core.feature_flags_ui_core import (  # noqa: F401 - ctx da aba Parametros
    render_feature_flags_shadow_trace_panel as core_render_feature_flags_shadow_trace_panel,
)
from app_core.flow_runtime_core import (  # noqa: F401 - ctx da aba Parametros
    build_training_csv_list as _build_training_csv_list,
)
from app_core.governance_report_core import (  # noqa: F401 - ctx da aba Parametros
    build_anchor_cases_rows as core_build_anchor_cases_rows,
    build_leakage_file_rows as core_build_leakage_file_rows,
    build_parts_rows as core_build_parts_rows,
    build_phase12_by_league_rows as core_build_phase12_by_league_rows,
    build_stop_rules_banner as core_build_stop_rules_banner,
    build_stop_rules_global_band_rows as core_build_stop_rules_global_band_rows,
    build_stop_rules_league_band_rows as core_build_stop_rules_league_band_rows,
    build_stop_rules_major_rows as core_build_stop_rules_major_rows,
    decision_banner_parts as core_decision_banner_parts,
)
from app_core.governance_runtime_core import (  # noqa: F401 - ctx da aba Parametros
    append_governance_log as core_append_governance_log,
    combine_governance_decisions as core_combine_governance_decisions,
    normalize_governance_decision as core_normalize_governance_decision,
    run_governance_commands as core_run_governance_commands,
    run_governance_operation as core_run_governance_operation,
)
from app_core.ml_oos_gate_core import (  # noqa: F401 - ctx da aba Parametros
    wf_gate_multiplier as _wf_gate_multiplier,
)
from app_core.ml_session_runtime_core import (  # noqa: F401 - ctx da aba Parametros
    get_fit_scale_state as core_get_fit_scale_state,
    get_pre_delivery_report as core_get_pre_delivery_report,
    set_fit_base_scales as core_set_fit_base_scales,
    set_pending_apply_param_values as core_set_pending_apply_param_values,
    set_pre_delivery_report as core_set_pre_delivery_report,
)
from app_core.navigation_state_core import (  # noqa: F401 - ctx da aba Parametros
    consume_flash_saved_profile_msg as core_consume_flash_saved_profile_msg,
)
from app_core.runtime_session_state_core import (  # noqa: F401 - ctx da aba Parametros
    get_cal_diag_last_report as core_get_cal_diag_last_report,
    get_daily_pipeline_report as core_get_daily_pipeline_report,
    get_governance_last_log as core_get_governance_last_log,
    set_daily_pipeline_report as core_set_daily_pipeline_report,
    set_governance_last_log as core_set_governance_last_log,
    set_lv_last_report as core_set_lv_last_report,
    set_ml_confidence_baseline_last_report as core_set_ml_confidence_baseline_last_report,
    set_quick_maint_last_log as core_set_quick_maint_last_log,
    set_team_state_artifact_last_report as core_set_team_state_artifact_last_report,
    set_wf_last_report as core_set_wf_last_report,
)
from app_core.technical_calibration_ui_core import (  # noqa: F401 - ctx da aba Parametros
    render_calibration_support_panels as core_render_calibration_support_panels,
)
from app_core.technical_fit_calibration_ui_core import (  # noqa: F401 - ctx da aba Parametros
    render_fit_calibration_panel as core_render_fit_calibration_panel,
)
_render_viewer_badge(st, csv_path)
_render_csv_upload_panel(st, csv_path)

# Alerta global visível: drift/falta de parâmetros/calibração.
_render_global_maintenance_banner(st, csv_path, artifact_path, collect_status_fn=_collect_maintenance_status)
# Alerta global visível: observabilidade/shadow features (se houver falha de trace).
_render_global_feature_trace_banner(st)
# Alerta global visível: NOTA do ML caiu vs baseline (escrito pelo qualidade_alarme da manutenção).
core_render_ml_quality_alarm(st=st, root=APP_ROOT)

# Achievements path default (para ML core v2 e aba Vencedores)
# - Mantém em sessão para que o ML use o mesmo arquivo que você edita na aba "Vencedores"
core_ensure_achievement_path(
    session_state=st.session_state,
    artifact_path=str(artifact_path),
    app_root=APP_ROOT,
    get_achievement_path_fn=core_get_achievement_path,
    set_achievement_path_fn=core_set_achievement_path,
    load_artifact_fn=_load_artifact_cached,
    artifact_sig_fn=_artifact_sig,
    resolve_relpath_fn=_resolve_relpath,
)


# Se trocou season, reseta fluxo (pra não misturar times/linhas)
core_apply_season_change_reset(
    session_state=st.session_state,
    season_label=season_label,
    get_last_season_label_fn=core_get_last_season_label,
    set_last_season_label_fn=core_set_last_season_label,
    reset_flow_fn=_reset_flow,
    clear_matchup_selection_fn=core_clear_matchup_selection,
)

csv_sig = _file_sig(csv_path)

# Carrega times — APENAS os do CSV ativo (season atual / 2026). Times que só
# jogaram em 2024/2025 (ex.: LDL, sem dado em 2026) NÃO entram nos seletores,
# mesmo o modelo tendo rating antigo deles — a pedido: só times da season atual.
try:
    teams = _list_teams(csv_sig)
except (OSError, TypeError, ValueError, pd.errors.EmptyDataError, pd.errors.ParserError) as e:
    st.error(f"Falha ao ler CSV para listar times: {e}")
    st.stop()

# A liga de cada time viaja pelo estado, e nao por parametro novo: assinatura
# que muda entre o app e um modulo derrubou o site inteiro em 13/09/2026.
# Quem le usa `.get` e continua funcionando se a chave nao existir.
try:
    st.session_state["_liga_por_time"] = _liga_por_time(csv_sig)
except Exception:
    st.session_state["_liga_por_time"] = {}

# Normaliza grafias (ex.: "Dplus Kia" vs "Dplus KIA") para evitar cair na liga errada no modo auto.
core_normalize_matchup_selection_teams(
    session_state=st.session_state,
    csv_sig=csv_sig,
    team_canon_maps_fn=_team_canon_maps,
    canon_team_key_fn=_canon_team_key,
    ensure_matchup_selection_state_fn=core_ensure_matchup_selection_state,
    set_selected_team_fn=core_set_selected_team,
)

if nav_page == "Live-Bet":
    core_render_live_bet_page(
        st.session_state,
        season_year=season_year,
        teams=teams,
        csv_sig=csv_sig,
        artifact_path=artifact_path,
        load_team_games_fn=_load_team_games,
        load_player_rows_fn=_load_player_rows,
        state_get_str_fn=state_get_str,
        format_num_fn=_format_num,
        min_to_mmss_fn=_min_to_mmss,
    )


if nav_page == "Radar":
    core_render_radar_page(
        csv_sig=csv_sig,
        artifact_path=artifact_path,
        load_team_games_fn=_load_team_games,
        load_player_rows_fn=_load_player_rows,
        format_num_fn=_format_num,
        min_to_mmss_fn=_min_to_mmss,
    )


if nav_page == "Meta":
    core_render_meta_tab(st=st, ctx={"csv_sig": csv_sig})
    st.stop()


# Se pediu reset manual do confronto, aplica ANTES dos widgets (evita erro de session_state)
if core_consume_pending_reset_matchup(st.session_state):
    _reset_flow(keep_config=True)
    core_clear_matchup_selection(st.session_state)

flow_stage = core_get_flow_stage(st.session_state)


# -----------------------------
# Jogos (agenda) - adicionar por colagem (na página Plays)
# -----------------------------
_schedule_store_path = APP_ROOT / "user_schedule_store.json"
core_restore_schedule_runtime_state(st.session_state, _schedule_store_path)
core_bind_schedule_store_path(st.session_state, _schedule_store_path)
core_get_schedule_games(st.session_state)
core_ensure_schedule_alias_state(st.session_state)
core_set_schedule_unknown_aliases(st.session_state, core_has_schedule_unknown_aliases(st.session_state))

core_render_schedule_agenda_expander(
    st.session_state,
    app_root=APP_ROOT,
    teams=teams,
)


teamA, teamB, bo = core_render_matchup_selection(
    st.session_state,
    flow_stage=flow_stage,
    teams=teams,
    season_label=season_label,
    matchup_key_fn=build_matchup_key,
    save_lines_for_matchup_fn=_save_lines_for_matchup,
    load_lines_for_matchup_fn=_load_lines_for_matchup,
    reset_flow_fn=_reset_flow,
)

core_render_schedule_alias_mapping(
    st.session_state,
    alias_path=(APP_ROOT / "user_team_aliases.json"),
    teams=teams,
)


def _run_pre_delivery_checks(app_root: Path, csv_path_s: str, artifact_path_s: str, run_smoke: bool = False) -> Dict[str, Any]:
    return core_run_pre_delivery_checks_runtime(
        st.session_state,
        app_root=app_root,
        csv_path_s=csv_path_s,
        artifact_path_s=artifact_path_s,
        run_smoke=bool(run_smoke),
        assess_confidence_baseline_file_fn=core_assess_confidence_baseline_file,
        assess_state_artifact_file_fn=core_assess_state_artifact_file,
        assess_patch_calibration_freshness_fn=core_assess_patch_calibration_freshness,
        assess_combined_trace_file_fn=core_assess_combined_trace_file,
        assess_feature_trace_health_fn=core_assess_feature_trace_health,
        assess_session_trace_fn=core_assess_session_trace,
        assess_navigation_integrity_fn=core_assess_navigation_integrity,
        assess_utf8_file_fn=core_assess_utf8_file,
        assess_ranking_coverage_fn=core_assess_ranking_coverage,
        assess_params_baseline_stability_fn=core_assess_params_baseline_stability,
        assess_anchor_regression_fn=core_assess_anchor_regression,
        run_pre_delivery_smokes_fn=core_run_pre_delivery_smokes,
        build_patch_snapshot_fn=core_build_patch_snapshot,
        recommend_recalibration_fn=core_recommend_recalibration,
        compute_anchor_snapshot_fn=_compute_anchor_snapshot,
        get_feature_trace_state_fn=core_get_feature_trace_state,
        get_ml_trace_snapshot_fn=core_get_ml_trace_snapshot,
        pick_tabs_fn=_pick_tabs,
        required_tabs=_TAB_ALL,
        rank_table_fn=_mlcore_rank_table_v2,
        anchor_baseline_path=_ODDS_ANCHOR_BASELINE_PATH,
        python_executable=sys.executable,
        resolve_players_artifact_path_fn=_resolve_runtime_players_artifact_path,
    )

if flow_stage == "select":
    _can_continue_preview = bool(teamA) and bool(teamB) and (str(teamA) != str(teamB))
    if _can_continue_preview:
        st.info("Clique em **Analisar Confronto** para abrir o preenchimento das linhas.")
    else:
        st.info("Escolha os times e clique **Analisar Confronto**.")
    st.stop()

# -----------------------------
# Etapa 2 — preencher linhas
# -----------------------------
if flow_stage == "lines":
    core_render_lines_stage(
        st.session_state,
        season_label=season_label,
        team_a=teamA,
        team_b=teamB,
        matchup_key_fn=build_matchup_key,
        load_lines_for_matchup_fn=_load_lines_for_matchup,
        save_lines_for_matchup_fn=_save_lines_for_matchup,
        lines_store_fn=_lines_store,
        persist_lines_store_fn=_persist_lines_store_disk,
        lines_store_defaults_key=_LINES_STORE_DEFAULTS_KEY,
        reset_flow_fn=_reset_flow,
        request_rerun_fn=_request_streamlit_rerun,
    )

# -----------------------------
# Etapa 3 — resultados
# -----------------------------
# Load base dataframe (team_games) uma vez (cacheado)
team_games = _load_team_games(csv_sig)
_prev_season_info = next(
    (
        dict(info)
        for info in (seasons or [])
        if int(info.get("year", 0) or 0) == int(season_year) - 1
    ),
    {},
)
_prev_season_label = str(_prev_season_info.get("season") or "")
_prev_season_year = int(_prev_season_info.get("year", 0) or 0)
_prev_season_csv_path = str(_prev_season_info.get("csv_path") or "").strip()
_prev_team_games = pd.DataFrame()
if _prev_season_csv_path and Path(_prev_season_csv_path).exists():
    try:
        _prev_team_games = _load_team_games(_file_sig(_prev_season_csv_path))
    except (OSError, TypeError, ValueError, pd.errors.EmptyDataError, pd.errors.ParserError):
        _prev_team_games = pd.DataFrame()

# Janela rápida (layout estilo print: Ano Todo / 10 / 5 / Geral)
# "Geral" = consolidado recency-ponderado das 3 janelas (só afeta os TOTAIS;
# o ML do vencedor vem do artefato Elo e independe da janela). Ver
# app_core/window_blend_core.py.
win_map = {
    "Geral": "Geral",
    "Ano todo": "All",
    "Últimos 10": "Last 10",
    "Últimos 5": "Last 5",
}
if str(st.session_state.get("window_short", "") or "") not in win_map:
    st.session_state["window_short"] = next(iter(win_map.keys()))
window_short = st.radio("Janela (Histórico)", list(win_map.keys()), horizontal=True, key="window_short")
window_opt = win_map.get(window_short, "All")

# Controles de engine/filtros foram movidos para a aba Técnico/Parâmetros.
# Aqui no Plays apenas consumimos os valores já definidos no session_state.
years = sorted([int(y) for y in team_games["year"].dropna().unique().tolist()])
_results_runtime = core_resolve_results_runtime_settings(
    st.session_state,
    season_year=season_year,
    years=years,
)
default_year = int(_results_runtime["default_year"])
year_opt = _results_runtime["year_opt"]
split_opt = _results_runtime["split_opt"]
playoffs_opt = _results_runtime["playoffs_opt"]
fixed_league = _results_runtime["fixed_league"]
totals_mode = _results_runtime["totals_mode"]
ml_mode = _results_runtime["ml_mode"]
map_mode_ui = _results_runtime["map_mode_ui"]
league_mode = _results_runtime["league_mode"]
weight_mode = _results_runtime["weight_mode"]
half_life_days = _results_runtime["half_life_days"]
n_sims = int(_results_runtime["n_sims"])

# Seed determinística para simulações (evita variação por rerun sem mudança real de inputs).
_sim_seed_series = core_compute_sim_seed_series(
    st.session_state,
    stable_seed_fn=_stable_seed_from_parts,
    season_label=season_label,
    team_a=teamA,
    team_b=teamB,
    bo=int(bo),
    year_opt=year_opt,
    split_opt=split_opt,
    playoffs_opt=playoffs_opt,
    league_mode=league_mode,
    map_mode_ui=map_mode_ui,
    weight_mode=weight_mode,
    half_life_days=half_life_days,
    n_sims=n_sims,
    totals_mode=totals_mode,
    ml_mode=ml_mode,
)

# Recorte -> max_games
# "Geral" mantém max_games=None (= ano todo) para TODO o resto do app
# (ML, outras abas, filtros); o consolidado recency-ponderado é aplicado só
# nos totais, mais abaixo, quando is_geral é True.
max_games = None
is_geral = window_opt == "Geral"
if window_opt.startswith("Last"):
    try:
        max_games = int(window_opt.split()[-1])
    except (TypeError, ValueError):
        max_games = None

# Linhas (texto): em "results", prefira o store (evita perder valores quando os widgets não estão renderizados)
_active_match_key = build_matchup_key(season_label, teamA, teamB)
_saved = (_lines_store().get(_active_match_key) or {}) if flow_stage == "results" else {}
_line_texts = core_resolve_active_line_texts(
    st.session_state,
    flow_stage=str(flow_stage),
    saved_lines=_saved,
)
# line_keys vêm do registro central (ordem travada em test_flow_line_keys_registry:
# kills, towers, dragons, barons, inhib, time) — sem literais "lines_X" aqui.
_lk_kills, _lk_towers, _lk_dragons, _lk_barons, _lk_inhib, _lk_time = _flow_line_keys()
kills_lines = _line_texts[_lk_kills]
towers_lines = _line_texts[_lk_towers]
dragons_lines = _line_texts[_lk_dragons]
barons_lines = _line_texts[_lk_barons]
inhib_lines = _line_texts[_lk_inhib]
time_lines = _line_texts[_lk_time]

teamA_kills_line_text = _line_texts["teamA_kills_line_text"]
teamB_kills_line_text = _line_texts["teamB_kills_line_text"]
hc_kills_text = _line_texts["hc_kills_text"]
hc_towers_text = _line_texts["hc_towers_text"]
hc_dragons_text = _line_texts["hc_dragons_text"]
combo_kills_text = _line_texts["combo_kills_text"]
combo_time_text = _line_texts["combo_time_text"]

kills = parse_lines_text(kills_lines)
towers = parse_lines_text(towers_lines)
dragons = parse_lines_text(dragons_lines)
barons = parse_lines_text(barons_lines)
inhib = parse_lines_text(inhib_lines)
time_m = parse_time_lines_text(time_lines)

# mapeia as linhas preenchidas (por mercado) para reutilizar em ML+Totais
lines_for = {
    "kills": kills,
    "towers": towers,
    "dragons": dragons,
    "barons": barons,
    "inhibitors": inhib,
    "time": time_m,
}


def _analysis_signature() -> int:
    return core_build_analysis_signature(
        st.session_state,
        stable_seed_fn=_stable_seed_from_parts,
        sanitize_marginal_band_coeffs_fn=core_sanitize_ml_marginal_band_coeffs,
        season_label=season_label,
        team_a=teamA,
        team_b=teamB,
        bo=int(bo),
        year_opt=year_opt,
        split_opt=split_opt,
        playoffs_opt=playoffs_opt,
        league_mode=league_mode,
        fixed_league=fixed_league,
        window_opt=window_opt,
        weight_mode=weight_mode,
        half_life_days=half_life_days,
        n_sims=n_sims,
        totals_mode=totals_mode,
        ml_mode=ml_mode,
        map_mode_ui=map_mode_ui,
        line_texts=_line_texts,
    )


def _consistency_analysis_signature() -> int:
    return core_build_consistency_analysis_signature(
        st.session_state,
        stable_seed_fn=_stable_seed_from_parts,
        sanitize_marginal_band_coeffs_fn=core_sanitize_ml_marginal_band_coeffs,
        season_label=season_label,
        team_a=teamA,
        team_b=teamB,
        bo=int(bo),
        year_opt=year_opt,
        split_opt=split_opt,
        playoffs_opt=playoffs_opt,
        league_mode=league_mode,
        fixed_league=fixed_league,
        window_opt=window_opt,
        weight_mode=weight_mode,
        half_life_days=half_life_days,
        n_sims=n_sims,
        totals_mode=totals_mode,
        map_mode_ui=map_mode_ui,
        line_texts=_line_texts,
    )

if core_consume_consistency_refresh_pending(st.session_state):
    core_set_consistency_analysis_signature(st.session_state, _consistency_analysis_signature())

# Build Filters object
filters = Filters(
    year=None if year_opt == "All" else int(year_opt),
    league=None,  # handled by league_mode
    split=None if split_opt == "All" else str(split_opt),
    playoffs=None if playoffs_opt == "all" else (True if playoffs_opt == "true" else False),
)

league_fixed_value: Optional[str] = None
if league_mode == "fixed" and fixed_league and fixed_league != "All":
    league_fixed_value = fixed_league
    filters = Filters(
        year=filters.year,
        league=league_fixed_value,
        split=filters.split,
        playoffs=filters.playoffs,
    )

_prev_filters_active, _prev_dfA_context_year_full, _prev_dfB_context_year_full, _prev_reference_note = (
    _resolve_prev_season_with_fallback(
        _prev_team_games,
        filters=filters,
        team_a=teamA,
        team_b=teamB,
        prev_season_year=_prev_season_year,
        league_mode=league_mode,
        map_mode=map_mode_ui,
        filter_team_games_fn=filter_team_games,
    )
)
_prev_history_slices: Dict[str, pd.DataFrame] = {}
if not _prev_dfA_context_year_full.empty and not _prev_dfB_context_year_full.empty:
    _prev_df_h2h_context_year_full_A = _prev_dfA_context_year_full[
        _prev_dfA_context_year_full["opponent"] == teamB
    ].copy()
    _prev_history_slices = core_recency_slices(
        df_a=_prev_dfA_context_year_full,
        df_b=_prev_dfB_context_year_full,
        df_h2h=_prev_df_h2h_context_year_full_A,
        id_col="gameid",
        date_col="date",
        dedupe_league=True,
        backfill_unique_targets=True,
    )

# -----------------------------
# ML odds (engine)
# -----------------------------
_ml_runtime_cfg = core_get_ml_engine_runtime_settings(st.session_state)
ml_engine = _ml_runtime_cfg["ml_engine"]
as_of_date = _ml_runtime_cfg.get("ml_as_of_date") or date.today()

p_map_raw = p_map_cal = float("nan")
_ml_info = None
_lgA = _lgB = _tierA = _tierB = ""

# Calcula ML core v2 somente quando necessário (engine=mlcore ou comparação no debug).
if ml_engine == "mlcore_v2" or bool(_ml_runtime_cfg["ml_engine_compare"]):
    core_clear_ml_fused_post_cal_info(st.session_state)
    core_clear_ml_microseg_info(st.session_state)

    _art_sig = ("", 0, 0)
    try:
        if artifact_path:
            _art_sig = _file_sig(artifact_path)
    except OSError:
        _art_sig = ("", 0, 0)
    _fit_sig_ml = ("", 0, 0)
    try:
        if _FIT_PARAMS_PATH.exists():
            _fit_sig_ml = _file_sig(str(_FIT_PARAMS_PATH))
    except OSError:
        _fit_sig_ml = ("", 0, 0)

    _mlcore_cache_key = (
        "mlcore_v2",
        csv_sig,
        _art_sig,
        _fit_sig_ml,
        str(teamA).strip().casefold(),
        str(teamB).strip().casefold(),
        str(as_of_date),
        league_mode,
        str(getattr(filters, "league", "")) if league_mode == "fixed" else "",
        getattr(filters, "year", None),
        core_get_achievement_path(st.session_state),
        bool(_ml_runtime_cfg["ml_microseg_enabled"]),
        int(_ml_runtime_cfg["ml_microseg_lookback_games"]),
        float(_ml_runtime_cfg["ml_microseg_shrink_k"]),
        int(_ml_runtime_cfg["ml_microseg_min_n"]),
        float(_ml_runtime_cfg["ml_microseg_strength"]),
        float(_ml_runtime_cfg["ml_microseg_cap_pp"]),
        bool(_ml_runtime_cfg["ml_microseg_hierarchical"]),
        float(_ml_runtime_cfg["ml_microseg_hier_decay"]),
        bool(_ml_runtime_cfg["ml_fused_post_cal_use_fitted"]),
    )
    _ml_cache_state = core_get_mlcore_cache_state(st.session_state)
    _cache = _ml_cache_state.get("value")
    if _ml_cache_state.get("key") == _mlcore_cache_key and isinstance(_cache, dict):
        _ml_info = _cache.get("ml_info")
        p_map_raw = float(_cache.get("p_raw", float("nan")))
        p_map_cal = float(_cache.get("p_cal", float("nan")))
        if isinstance(_cache.get("microseg_info"), dict):
            core_set_ml_microseg_info(st.session_state, _cache.get("microseg_info"))
        if isinstance(_cache.get("fused_post_cal_info"), dict):
            core_set_ml_fused_post_cal_info(st.session_state, _cache.get("fused_post_cal_info"))
        _lgA = str(_cache.get("league_a", _cache.get("match_league", "")) or "")
        _lgB = str(_cache.get("league_b", _cache.get("match_league", "")) or "")
        _tierA = str(_cache.get("tier_a", _cache.get("match_tier", "")) or "")
        _tierB = str(_cache.get("tier_b", _cache.get("match_tier", "")) or "")
    else:
        def _resolve_leagues_for_matchup(ta, tb, year, lmode, fixed_lg):
            return core_resolve_runtime_team_leagues(
                team_a=ta, team_b=tb, year=year, league_mode=str(lmode),
                fixed_league=fixed_lg,
                infer_team_league_fn=lambda team, yr: _infer_team_league_from_csv(csv_sig, team, yr),
                infer_match_league_fn=lambda a, b, yr: _infer_match_league_from_csv(csv_sig, a, b, yr),
                tier_from_league_fn=core_tier_from_league,
                team_aliases_fn=_identity_team_name_candidates,
            )

        _core_result = _compute_ml_core_prediction(
            team_a=teamA,
            team_b=teamB,
            artifact_path=artifact_path,
            as_of_date=as_of_date,
            achievement_path=core_get_achievement_path(st.session_state),
            ml_runtime_cfg=_ml_runtime_cfg,
            filter_year=getattr(filters, "year", None),
            filter_league=getattr(filters, "league", None),
            filter_split=getattr(filters, "split", None),
            filter_playoffs=getattr(filters, "playoffs", None),
            bo=int(bo),
            league_mode=str(league_mode),
            csv_sig=csv_sig,
            art_sig=_art_sig,
            fit_params_path=str(_FIT_PARAMS_PATH) if _FIT_PARAMS_PATH.exists() else None,
            resolve_leagues_fn=_resolve_leagues_for_matchup,
            p_map_v2_fn=_mlcore_p_map_v2,
            build_microseg_table_fn=_build_ml_microseg_table,
            apply_microseg_fn=_apply_ml_microseg_calibration,
            apply_fused_postcal_fn=_apply_fused_post_calibration,
            load_fitted_params_fn=_load_fitted_params_cached,
            file_sig_fn=_file_sig,
        )

        _ml_info = _core_result.get("ml_info")
        st.session_state["_ml_v2_last_error"] = str(_core_result.get("ml_error", "") or "")
        p_map_raw = float(_core_result.get("p_map_raw", float("nan")))
        p_map_cal = float(_core_result.get("p_map_cal", float("nan")))
        _lgA = str(_core_result.get("league_a", ""))
        _lgB = str(_core_result.get("league_b", ""))
        _tierA = str(_core_result.get("tier_a", ""))
        _tierB = str(_core_result.get("tier_b", ""))

        if isinstance(_core_result.get("microseg_info"), dict):
            core_set_ml_microseg_info(st.session_state, _core_result["microseg_info"])
        if isinstance(_core_result.get("fused_post_cal_info"), dict):
            core_set_ml_fused_post_cal_info(st.session_state, _core_result["fused_post_cal_info"])

        core_set_mlcore_cache_state(st.session_state, _mlcore_cache_key, {
            "ml_info": _ml_info,
            "p_raw": p_map_raw,
            "p_cal": p_map_cal,
            "microseg_info": core_get_ml_microseg_info(st.session_state),
            "fused_post_cal_info": core_get_ml_fused_post_cal_info(st.session_state),
            "match_league": _lgA,
            "match_tier": _tierA,
            "league_a": _lgA,
            "league_b": _lgB,
            "tier_a": _tierA,
            "tier_b": _tierB,
        })

# Post layers: WF correction, p_series, fit scales + players context.
core_clear_wf_ml_corr_info(st.session_state)
_post_result = _compute_ml_post_layers(
    ml_info=_ml_info,
    p_map_cal=p_map_cal,
    bo=int(bo),
    ml_runtime_cfg=_ml_runtime_cfg,
    wf_report=core_get_wf_last_report(st.session_state),
    wf_correct_p_map_fn=_wf_correct_p_map,
    fit_scales_for_league_fn=_fit_scales_for_league,
    fit_players_context_for_league_fn=_fit_players_context_for_league,
    prob_win_series_fn=prob_win_series,
)
p_map_cal = float(_post_result.get("p_map_cal", p_map_cal))
p_series = float(_post_result.get("p_series", float("nan")))
if isinstance(_post_result.get("wf_corr_info"), dict):
    core_set_wf_ml_corr_info(st.session_state, _post_result["wf_corr_info"])
_ts_used = float(_post_result.get("fit_team_scale", 1.0))
_ps_used = float(_post_result.get("fit_players_scale", 1.0))
_lg_used = str(_post_result.get("fit_league_used", ""))
_pcfg_used = _post_result.get("players_context_cfg") or {}
_pcfg_src = str(_post_result.get("players_context_src", ""))
core_set_fit_used_scales(st.session_state, team_scale=_ts_used, players_scale=_ps_used)
core_set_fit_runtime_labels(
    st.session_state,
    scale_league_used=_lg_used,
    players_context_source_used=_pcfg_src,
)
core_apply_players_context_runtime_override(
    st.session_state,
    _pcfg_used,
    _pcfg_src,
    use_fitted=bool(_ml_runtime_cfg["ml_players_context_use_fitted"]),
)

if ml_engine == "mlcore_v2" and not math.isfinite(p_map_cal):
    _ml_v2_err = str(st.session_state.get("_ml_v2_last_error", "") or "")
    st.warning(
        "Não consegui calcular p_map via ML core v2 com esse ml_artifact.json. "
        "(ML fica indisponível, mas Totais continuam.)"
        + (f"\n\nMotivo: `{_ml_v2_err}`" if _ml_v2_err else "")
    )


map_mode = normalize_map_mode(map_mode_ui)
hl_txt = "Uniforme" if half_life_days is None else f"{half_life_days}d"

# -----------------------------
# Totals (map or series)
# -----------------------------
dfA_used = filter_team_games(team_games, team=teamA, filters=filters, league_mode=league_mode, map_mode=map_mode, max_games=max_games)
dfB_used = filter_team_games(team_games, team=teamB, filters=filters, league_mode=league_mode, map_mode=map_mode, max_games=max_games)

pA = build_profile(team_games, team=teamA, filters=filters, league_mode=league_mode, map_mode=map_mode, half_life_days=half_life_days, max_games=max_games)
pB = build_profile(team_games, team=teamB, filters=filters, league_mode=league_mode, map_mode=map_mode, half_life_days=half_life_days, max_games=max_games)

if pA.n_games == 0 or pB.n_games == 0:
    st.error("Sem jogos suficientes com esses filtros. Ajuste Split/Playoffs/League mode ou a janela.")
    st.caption("Aviso: os mercados do confronto podem ficar incompletos, mas abas independentes (ex.: Players/Campeões) continuam disponíveis.")




totals = _expected_totals_dc(team_games, pA, pB)

# AVG maps baseline (gol.gg style)
pA_avg = pA
pB_avg = pB
avg_totals = None
if map_mode != "avg":
    pA_avg = build_profile(team_games, team=teamA, filters=filters, league_mode=league_mode, map_mode="avg", half_life_days=half_life_days, max_games=max_games)
    pB_avg = build_profile(team_games, team=teamB, filters=filters, league_mode=league_mode, map_mode="avg", half_life_days=half_life_days, max_games=max_games)
    avg_totals = _expected_totals_dc(team_games, pA_avg, pB_avg)

totals_map = totals
totals_avg = avg_totals if avg_totals is not None else totals

# --- Modo "Geral": consolida as 3 janelas (recency-ponderado) nos TOTAIS ---
# Recalcula os totais para cada janela (Ano/L10/L5) e blendeia. O ML do
# vencedor não é tocado (vem do artefato Elo, independe da janela).
# totals_breakdown guarda o detalhe por janela p/ exibir abaixo da tabela.
totals_breakdown: Dict[str, Any] = {}
if is_geral:
    def _totals_for_window(_mg: Optional[int]) -> tuple[Dict[str, Any], Dict[str, Any]]:
        _pA = build_profile(team_games, team=teamA, filters=filters, league_mode=league_mode, map_mode=map_mode, half_life_days=half_life_days, max_games=_mg)
        _pB = build_profile(team_games, team=teamB, filters=filters, league_mode=league_mode, map_mode=map_mode, half_life_days=half_life_days, max_games=_mg)
        _tm = _expected_totals_dc(team_games, _pA, _pB) if (_pA.n_games > 0 and _pB.n_games > 0) else {}
        if map_mode != "avg":
            _pAa = build_profile(team_games, team=teamA, filters=filters, league_mode=league_mode, map_mode="avg", half_life_days=half_life_days, max_games=_mg)
            _pBa = build_profile(team_games, team=teamB, filters=filters, league_mode=league_mode, map_mode="avg", half_life_days=half_life_days, max_games=_mg)
            _ta = _expected_totals_dc(team_games, _pAa, _pBa) if (_pAa.n_games > 0 and _pBa.n_games > 0) else _tm
        else:
            _ta = _tm
        return _tm, _ta

    _per_map: list = []
    _per_avg: list = []
    for _lbl, _mg in _GERAL_WINDOWS:
        _w = _geral_window_weight(_mg)
        _tm, _ta = _totals_for_window(_mg)
        if _tm:
            _per_map.append((_w, _tm))
        if _ta:
            _per_avg.append((_w, _ta))
        # breakdown segue o mesmo modo (map/avg) exibido na tabela
        totals_breakdown[_lbl] = (_tm if totals_mode == "map" else _ta)
    _blend_map = _blend_matchup_totals(_per_map, totals_cls=MatchupTotals)
    _blend_avg = _blend_matchup_totals(_per_avg, totals_cls=MatchupTotals)
    if _blend_map:
        totals_map = _blend_map
    if _blend_avg:
        totals_avg = _blend_avg

totals_for_lines = totals_map if totals_mode == "map" else totals_avg

_prev_totals_map: Dict[str, Any] = {}
_prev_totals_avg: Dict[str, Any] = {}
_prev_totals_for_lines: Dict[str, Any] = {}
if (
    isinstance(_prev_team_games, pd.DataFrame)
    and not _prev_team_games.empty
    and _prev_filters_active is not None
):
    _prev_pA = build_profile(
        _prev_team_games,
        team=teamA,
        filters=_prev_filters_active,
        league_mode=league_mode,
        map_mode=map_mode,
        half_life_days=half_life_days,
        max_games=max_games,
    )
    _prev_pB = build_profile(
        _prev_team_games,
        team=teamB,
        filters=_prev_filters_active,
        league_mode=league_mode,
        map_mode=map_mode,
        half_life_days=half_life_days,
        max_games=max_games,
    )
    if _prev_pA.n_games > 0 and _prev_pB.n_games > 0:
        _prev_totals_map = _expected_totals_dc(_prev_team_games, _prev_pA, _prev_pB)
        if map_mode != "avg":
            _prev_pA_avg = build_profile(
                _prev_team_games,
                team=teamA,
                filters=_prev_filters_active,
                league_mode=league_mode,
                map_mode="avg",
                half_life_days=half_life_days,
                max_games=max_games,
            )
            _prev_pB_avg = build_profile(
                _prev_team_games,
                team=teamB,
                filters=_prev_filters_active,
                league_mode=league_mode,
                map_mode="avg",
                half_life_days=half_life_days,
                max_games=max_games,
            )
            if _prev_pA_avg.n_games > 0 and _prev_pB_avg.n_games > 0:
                _prev_totals_avg = _expected_totals_dc(_prev_team_games, _prev_pA_avg, _prev_pB_avg)
        if not _prev_totals_avg:
            _prev_totals_avg = dict(_prev_totals_map)
        _prev_totals_for_lines = _prev_totals_map if totals_mode == "map" else _prev_totals_avg

# -----------------------------
# Main result tabs (formato dos prints)
# -----------------------------
with st.sidebar:
    st.markdown("### Navega\u00e7\u00e3o")
    _page_modes = ["Fluxo R\u00e1pido", "Mercados", "An\u00e1lise", "Completo", "Dev"]
    _page_mode_cur = _fix_mojibake_text(core_get_ui_page_mode(st.session_state, NAV_DEFAULT_UI_PAGE_MODE) or NAV_DEFAULT_UI_PAGE_MODE)
    if _page_mode_cur not in _page_modes:
        _page_mode_cur = NAV_DEFAULT_UI_PAGE_MODE
    if str(st.session_state.get("ui_page_mode", "") or "") not in _page_modes:
        st.session_state["ui_page_mode"] = _page_mode_cur
    _page_mode_selected = st.radio(
        "Modo de p\u00e1ginas",
        options=_page_modes,
        key="ui_page_mode",
        help="Reduz a quantidade de abas vis\u00edveis sem remover funcionalidades.",
    )

# Gate de análise: em "results", só recalcula após clique explícito.
if flow_stage == "results":
    _analysis_gate_state = core_get_analysis_gate_state(st.session_state)
    _sig_now = _analysis_signature()
    _force_once = core_consume_analysis_force_once(st.session_state)
    _sig_last = _analysis_gate_state.get("analysis_sig_last")
    if _sig_last is None or _force_once:
        core_set_analysis_signature(st.session_state, _sig_now)
        _sig_last = int(_sig_now)
    _needs_reanalyze = int(_sig_last if _sig_last is not None else _sig_now) != int(_sig_now)
    ga1, ga2 = st.columns([4, 1])
    with ga1:
        if _needs_reanalyze:
            st.warning("Par\u00e2metros/linhas mudaram. Clique em **Analisar confronto** para atualizar as odds.")
        else:
            st.caption("An\u00e1lise em dia para os par\u00e2metros atuais.")
    with ga2:
        if st.button("Analisar confronto", type="primary", width='stretch', key="analyze_gate_btn"):
            core_set_analysis_signature(st.session_state, _sig_now)
            core_set_consistency_analysis_signature(st.session_state, _consistency_analysis_signature())
            _request_streamlit_rerun()
    if _needs_reanalyze:
        st.stop()

_page_mode_now = _fix_mojibake_text(core_get_ui_page_mode(st.session_state, NAV_DEFAULT_UI_PAGE_MODE) or NAV_DEFAULT_UI_PAGE_MODE)
_active_tabs = _canonicalize_tab_labels(_pick_tabs(_page_mode_now), _TAB_ALL)
_tab_norm = lambda t: _normalize_text_key(t)
_TAB_VISAO = TAB_VISAO
_TAB_CONS = TAB_CONS
_TAB_PARAMS = TAB_PARAMS
if _page_mode_now in ("Fluxo R\u00e1pido", "Mercados"):
    # An\u00e1lise de Linha agora ocupa o slot onde antes ficava Consist\u00eancia das
    # linhas (que foi movida para o modo Dev junto com Par\u00e2metros/Identidade).
    from app_core.tab_dispatcher import TAB_LINE_ANALYSIS as _TAB_LA
    _active_norm = {_tab_norm(t) for t in _active_tabs}
    if _tab_norm(_TAB_LA) not in _active_norm:
        _visao_label = next((t for t in _active_tabs if _tab_norm(t) == _tab_norm(_TAB_VISAO)), None)
        if _visao_label is not None:
            _ix = _active_tabs.index(_visao_label) + 1
            _active_tabs = [*_active_tabs[:_ix], _TAB_LA, *_active_tabs[_ix:]]
        else:
            _active_tabs = [_TAB_VISAO, _TAB_LA, *list(_active_tabs)]

# Dedupe final por rótulo canônico (evita variantes quebradas/duplicadas no topo).
_active_tabs = _canonicalize_tab_labels(_active_tabs, _TAB_ALL)

tab_refs = {n: t for n, t in zip(_active_tabs, st.tabs(_active_tabs))}

# ISOLAMENTO DE FALHA POR ABA — zerado uma vez, aqui, antes de qualquer aba.
# Em 13/09/2026 o site inteiro caiu porque UMA aba recebeu um argumento que a
# versao antiga do arquivo no servidor nao conhecia. Aba com defeito custa uma
# aba, nao o app. Ver app_core/tab_dispatcher.py.
_iniciar_registro_de_falhas(st)

# Fecho cross-módulo (força-tarefa 23/07): params_tab repassa ctx para
# _render_manutencao_ml/_render_governanca_ml, que vivem em params_sections_core.
# Auto-derivado das fontes dos 2 módulos (nenhum vai mais fundo).
_desenhar_aba(st, tab_refs.get(_TAB_PARAMS), _TAB_PARAMS, lambda: _render_params_tab(
    st=st, ctx=_pick_ctx_from_modules(
        "app_core.params_tab_core", "app_core.params_sections_core")))

# Explicit minimal ctx: only the keys render_visao_tab actually reads, built
# from globals(). Decouples the renderer from plays_app internals and
# validates the contract (loud-fail on missing core_* import).
_desenhar_aba(st, tab_refs.get(_TAB_VISAO), _TAB_VISAO, lambda: _render_visao_tab(
    st=st, ctx=_build_render_ctx(
        globals(), renderer_source=_inspect.getsource(_render_visao_tab),
        renderer_name="render_visao_tab")))

_desenhar_aba(st, tab_refs.get(_TAB_CONS), _TAB_CONS, lambda: _render_consistencia_tab(
    st=st, ctx=_build_render_ctx(
        globals(), renderer_source=_inspect.getsource(_render_consistencia_tab),
        renderer_name="render_consistencia_tab")))

    
# -----------------------------
# Secondary tabs extracted from plays_app
# -----------------------------
def _oportunidades_calcular_totais(casa: str, fora: str, mapa: str):
    """Os totais do confronto, pelo MESMO caminho da tela de analise.

    build_profile + _expected_totals_dc, com as regulagens que ele tem na
    barra lateral neste momento. PRINCIPIO V: nao existe uma segunda conta
    aqui -- se existisse, o mesmo confronto daria dois numeros e nenhum dos
    dois mereceria confianca.

    Devolve None quando nao da (nome de time que nao casa com o CSV, ou jogos
    de menos). None chega a tela como "nao consegui", com o nome dos times --
    nunca como lista vazia calada.
    """
    a_csv = _oportunidades_resolver_time(casa)
    b_csv = _oportunidades_resolver_time(fora)
    if not a_csv or not b_csv:
        return None
    _pA = build_profile(team_games, team=a_csv, filters=filters, league_mode=league_mode,
                        map_mode=mapa, half_life_days=half_life_days, max_games=max_games)
    _pB = build_profile(team_games, team=b_csv, filters=filters, league_mode=league_mode,
                        map_mode=mapa, half_life_days=half_life_days, max_games=max_games)
    if _pA.n_games == 0 or _pB.n_games == 0:
        return None
    return _expected_totals_dc(team_games, _pA, _pB)


def _oportunidades_resolver_time(nome: str) -> str:
    """O nome da casa -> o nome do CSV, usando os apelidos JA APRENDIDOS.

    A Pinnacle escreve "Liquid", "9z", "Invictus"; o CSV tem "Team Liquid",
    "9z Globant", "Invictus Gaming". NAO se adivinha: o mesmo resolvedor da
    aba Jogos decide, e o que ele nao casar aparece na tela pelo nome, para
    ele ensinar uma vez. Adivinhar aqui seria analisar o time errado com toda
    a confianca do mundo.
    """
    try:
        achado, ok = core_resolve_schedule_team(str(nome), list(teams),
                                           _oportunidades_apelidos())
    except Exception:
        return ""
    return str(achado) if ok else ""


def _oportunidades_apelidos():
    try:
        return core_load_schedule_aliases(st.session_state, APP_ROOT / "user_team_aliases.json")
    except Exception:
        return {}


def _oportunidades_jogos_por_time(nome: str) -> int:
    """Quantos jogos o CSV tem desse time. Conta fina tem de aparecer."""
    alvo = _oportunidades_resolver_time(nome)
    if not alvo:
        return -1
    try:
        return int((team_games["team"].astype(str) == alvo).sum())
    except Exception:
        return -1


def _oportunidades_times_nao_casados() -> list:
    from app_core.odds_coletadas_core import carregar_odds_coletadas, times_da_coleta
    try:
        _odds = carregar_odds_coletadas(APP_ROOT)
    except Exception:
        return []
    return [n for n in times_da_coleta(_odds) if not _oportunidades_resolver_time(n)]


_secondary_tab_renderers = {
    TAB_OPORTUNIDADES: lambda: core_render_oportunidades_tab(
        st=st,
        ctx={
            "raiz": APP_ROOT,
            "calcular_totais": _oportunidades_calcular_totais,
            "prob_over": core_prob_over_from_total,
            "jogos_por_time": _oportunidades_jogos_por_time,
            "times_nao_casados": _oportunidades_times_nao_casados(),
        },
    ),
    "Rankings": lambda: core_render_rankings_tab(
        st=st,
        team_games=team_games,
        Filters=Filters,
        artifact_path=artifact_path,
        as_of_date=as_of_date,
        half_life_days=float(half_life_days),
        mlcore_rank_table_v2_fn=_mlcore_rank_table_v2,
        elo_rank_table_fn=_elo_rank_table,
        format_num_fn=_format_num,
        team_a=teamA,
        team_b=teamB,
    ),
    "Jogos": lambda: core_render_schedule_tab(st=st, bo=int(bo), teams=teams),
    "Series": lambda: core_render_series_tab(
        st=st,
        ctx={
            "ml_info": _ml_info,
            "teamA": teamA,
            "teamB": teamB,
            "bo": int(bo),
            "p_map_cal": float(p_map_cal),
            "state_get_float_fn": state_get_float,
            "state_get_int_fn": state_get_int,
            "state_get_str_fn": state_get_str,
            "winner_pricing_bundle_fn": core_compute_winner_pricing_bundle,
            "prob_win_series_fn": prob_win_series,
            "odd_from_prob_fn": _odd_from_p,
            "team_with_league_label_fn": _team_with_league_label,
            "format_num_fn": _format_num,
            "format_pct_fn": _format_pct,
            "df_contract_view_fn": _df_contract_view,
            "parse_lines_fn": parse_lines_text,
            "series_sims_cached_fn": _series_sims_cached,
            "combine_mean_fn": _combine_mean,
            "combine_sd_fn": _combine_sd,
            "matchup_totals_cls": MatchupTotals,
            "n_sims": int(n_sims),
            "totals_avg": totals_avg,
            "profile_a": pA,
            "profile_b": pB,
        },
    ),
    "StatsCamps": lambda: core_render_statscamps_tab(
        st=st,
        team_games=team_games,
        Filters=Filters,
        apply_filters_fn=apply_filters,
        parse_lines_fn=parse_lines_text,
        parse_time_lines_fn=parse_time_lines_text,
        min_to_mmss_fn=_min_to_mmss,
        format_num_fn=_format_num,
        df_contract_view_fn=_df_contract_view,
    ),
    TAB_LINE_ANALYSIS: lambda: core_render_line_analysis_tab(
        st=st,
        team_games=team_games,
        Filters=Filters,
        apply_filters_fn=apply_filters,
        min_to_mmss_fn=_min_to_mmss,
        session_state=st.session_state,
        resumo_renderer=lambda: core_render_resumo_tab(
            st=st,
            ctx={
                "teamA": teamA,
                "teamB": teamB,
                "team_games": team_games,
                "Filters": Filters,
                "filters": filters,
                "apply_filters_fn": apply_filters,
                "ml_info": _ml_info,
                "map_mode_ui": map_mode,
                "kills": kills,
                "towers": towers,
                "dragons": dragons,
                "barons": barons,
                "inhibitors": inhib,
                "time_m": time_m,
                "totals_for_lines": totals_for_lines,
                "dfA_used": dfA_used,
                "dfB_used": dfB_used,
                "state_get_bool_fn": state_get_bool,
                "state_get_float_fn": state_get_float,
                "state_get_int_fn": state_get_int,
                "state_get_str_fn": state_get_str,
                "save_app_settings_to_disk_fn": _save_app_settings_to_disk,
                "parse_lines_fn": parse_lines_text,
                "parse_time_lines_fn": parse_time_lines_text,
                "odd_from_prob_fn": _odd_from_p,
                "fmt_recortes_disp_fn": _fmt_recortes_disp,
                "fmt_line_disp_fn": _fmt_line_disp,
                "metric_label_fn": _metric_label_pt,
                "side_label_fn": _side_label_pt,
                "format_num_fn": _format_num,
                "df_contract_view_fn": _df_contract_view,
                "total_over_prob_fn": total_over_prob,
                "persist_combined_trace_file_fn": _persist_combined_trace_file,
                "list_resumo_filter_presets_fn": core_list_resumo_filter_presets,
                "load_resumo_filter_custom_fn": core_load_resumo_filter_custom,
                "apply_resumo_filter_values_fn": core_apply_resumo_filter_values,
                "save_resumo_filter_custom_fn": core_save_resumo_filter_custom,
                "save_resumo_filter_profile_fn": core_save_resumo_filter_profile,
                "delete_active_resumo_filter_profile_fn": core_delete_active_resumo_filter_profile,
                "ensure_resumo_combo_state_fn": core_ensure_resumo_combo_state,
                "apply_resumo_combo_preset_fn": core_apply_resumo_combo_preset,
                "build_statscamps_scope_frame_fn": core_build_statscamps_scope_frame,
                "compute_statscamps_pct_fn": core_compute_statscamps_pct,
                "format_statscamps_badge_fn": core_format_statscamps_badge,
                "recency_slices_fn": core_recency_slices,
                "make_pricing_adapters_fn": core_make_pricing_adapters,
                "ensure_metric_lines_fn": core_ensure_metric_lines,
                "infer_matchup_league_fn": core_infer_matchup_league,
                "build_resumo_guardrail_cfg_fn": core_build_resumo_guardrail_cfg,
                "build_ml_rows_fn": core_build_ml_rows,
                "build_metric_rows_fn": core_build_metric_rows,
                "build_combo_rows_fn": core_build_combo_rows,
                "build_market_trace_rows_fn": core_build_market_trace_rows,
                "finalize_resumo_dataframe_fn": core_finalize_resumo_dataframe,
                "wr_laplace_fn": core_wr_laplace,
                "counts_ml_totals_fn": core_counts_ml_totals,
                "tail_df_fn": core_tail_df,
            },
        ),
    ),
    "Campeões": lambda: core_render_champions_tab(
        st=st,
        ctx={
            "team_games": team_games,
            "teamA": teamA,
            "teamB": teamB,
            "csv_sig": csv_sig,
            "Filters": Filters,
            "state_get_str_fn": state_get_str,
            "state_get_int_fn": state_get_int,
            "load_player_rows_fn": _load_player_rows,
            "apply_filters_players_fn": core_apply_filters_players,
            "champion_vocab_fn": core_champion_vocab,
            "fuzzy_match_one_fn": core_fuzzy_match_one,
            "df_contract_view_fn": _df_contract_view,
            "format_num_fn": _format_num,
            "ensure_champions_filter_state_fn": core_ensure_champions_filter_state,
            "reset_champions_league_dependents_fn": core_reset_champions_league_dependents,
            "resolve_blue_side_choice_fn": core_resolve_blue_side_choice,
            "sync_blue_side_choice_fn": core_sync_blue_side_choice,
        },
    ),
    "Players": lambda: core_render_players_tab(
        st=st,
        ctx={
            "team_games": team_games,
            "Filters": Filters,
            "csv_sig": csv_sig,
            "teamA": teamA,
            "teamB": teamB,
            "load_player_rows_fn": _load_player_rows,
            # Rating INDIVIDUAL de jogador (o mesmo que o pipeline do ML usa).
            # A aba calculava rating como logit(vitorias/jogos) = taxa de vitoria
            # do TIME colada em cada jogador (todos do Gen.G davam +1.070) — sem
            # nenhuma informacao individual. O laboratorio de escalacao precisa
            # da fonte de verdade p/ nao mentir na troca de roster (achado 22/07).
            "players_artifact_fn": (
                lambda: _load_players_artifact_cached(
                    _file_sig(str(_players_artifact_output_path(artifact_path)))
                )
            ),
            "apply_filters_players_fn": core_apply_filters_players,
            "latest_lineup_names_fn": core_latest_lineup_names,
            "norm_pos_fn": _norm_pos,
            "parse_players_text_fn": core_parse_players_text,
            "resolve_players_fn": core_resolve_players,
            "fuzzy_match_one_fn": core_fuzzy_match_one,
            "build_lane_rows_fn": core_build_lane_rows,
            "ensure_players_filter_state_fn": core_ensure_players_filter_state,
            "ensure_players_text_state_fn": core_ensure_players_text_state,
            "apply_players_autofill_state_fn": core_apply_players_autofill_state,
            "ensure_player_line_input_state_fn": core_ensure_player_line_input_state,
            "apply_players_submission_state_fn": core_apply_players_submission_state,
            "build_per_player_lines_by_idx_fn": core_build_per_player_lines_by_idx,
            "build_player_means_rows_fn": core_build_player_means_rows,
            "build_recent_player_stats_rows_fn": core_build_recent_player_stats_rows,
            "build_player_market_rows_fn": core_build_player_market_rows,
            "append_players_recent_stats_panel_trace_fn": core_append_players_recent_stats_panel_trace,
            "append_players_fair_panel_trace_fn": core_append_players_fair_panel_trace,
            "append_players_markets_panel_trace_fn": core_append_players_markets_panel_trace,
            "append_players_panels_bundle_trace_fn": core_append_players_panels_bundle_trace,
            "append_feature_trace_fn": _append_feature_trace,
            "feature_flag_enabled_fn": _feature_flag_enabled,
            "df_contract_view_fn": _df_contract_view,
            "format_num_fn": _format_num,
            "format_pct_fn": _format_pct,
            "format_pct1_fn": _format_pct,
            "odd_from_prob_fn": _odd_from_p,
            "state_get_float_fn": state_get_float,
            "state_get_int_fn": state_get_int,
            "parse_lines_fn": parse_lines_text,
            "fuse_probs_by_precision_fn": _fuse_probs_by_precision,
            "persist_combined_trace_file_fn": _persist_combined_trace_file,
            "playoffs_opt": playoffs_opt,
        },
    ),
    "Identidade": lambda: core_render_identity_tab(
        st=st,
        ctx={
            "registry_path": (APP_ROOT / "identity_registry.json"),
        },
    ),
}

dispatch_secondary_tabs(st, tab_refs, _secondary_tab_renderers, order=SECONDARY_TAB_ORDER)


# -----------------------------
# Vencedores (Achievements) - removido (bloco legado desativado)
# -----------------------------

                                                