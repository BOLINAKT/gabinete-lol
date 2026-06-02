"""Players tab renderer."""

from __future__ import annotations

import json
import math
from typing import Any, Mapping

import numpy as np
import pandas as pd

from app_core.tab_filters_core import collect_year_split_league_options
from app_core.tab_state_core import blank_space_label
from app_core.tab_ui_core import render_tab_hero, render_tab_section
from mlcore.utils import sigmoid as _sigmoid


def _team_rating(
    *,
    by_player: pd.DataFrame,
    players: list[str],
    format_num_fn,
) -> tuple[float, pd.DataFrame]:
    if not players:
        return 0.0, pd.DataFrame([])
    sub = by_player[by_player["player"].isin(players)].copy()
    if sub.empty:
        return 0.0, pd.DataFrame([])
    sub["w"] = sub["games"].clip(upper=20).astype(float)
    rating = float((sub["rating"] * sub["w"]).sum() / max(sub["w"].sum(), 1.0))
    view = sub[["player", "games", "wins", "p_smooth", "rating"]].copy()
    view["Win Rate"] = (100.0 * (view["wins"] / view["games"])).apply(lambda x: format_num_fn(x, 1))
    view["p_smooth"] = (100.0 * view["p_smooth"]).apply(lambda x: format_num_fn(x, 1))
    view["rating"] = view["rating"].apply(lambda x: format_num_fn(x, 3))
    view = view.rename(
        columns={"player": "Player", "games": "Games", "wins": "Wins", "p_smooth": "Smooth Win%", "rating": "Rating"}
    )
    return rating, view


def _build_trace_rows(out_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trace_rows = []
    for row in out_rows:
        trace_rows.append(
            {
                "lane": str(row.get("Lane", "")),
                "team": str(row.get("Team", "")),
                "player": str(row.get("Player", "")),
                "mercado": str(row.get("Mercado", "")),
                "lado": str(row.get("Lado", "")),
                "linha": str(row.get("Linha", "")),
                "odd_model": row.get("_odd_model_raw"),
                "odd_hist": row.get("_odd_hist_raw"),
                "odd_h2h": row.get("_odd_h2h_raw"),
                "odd_mix": row.get("_odd_mix_raw"),
                "calib_reason": str(row.get("_calib_reason", "")),
                "calib_source": str(row.get("_calib_source", "")),
                "h2h_n": row.get("_h2h_n"),
                "h2h_used": row.get("_h2h_used"),
                "obs_odds": str(row.get("Obs Odds", "")),
                "obs_mix": str(row.get("Obs Mix", "")),
            }
        )
    return trace_rows


def render_players_tab(*, st: Any, ctx: Mapping[str, Any]) -> None:
    session_state = st.session_state
    render_tab_hero(st, title="Players", subtitle="ML por lineup com fusão Team + Players e mercados individuais por linha.")

    team_games = ctx["team_games"]
    Filters = ctx["Filters"]
    csv_sig = ctx["csv_sig"]
    team_a = ctx["teamA"]
    team_b = ctx["teamB"]
    load_player_rows_fn = ctx["load_player_rows_fn"]
    apply_filters_players_fn = ctx["apply_filters_players_fn"]
    latest_lineup_names_fn = ctx["latest_lineup_names_fn"]
    norm_pos_fn = ctx["norm_pos_fn"]
    parse_players_text_fn = ctx["parse_players_text_fn"]
    resolve_players_fn = ctx["resolve_players_fn"]
    fuzzy_match_one_fn = ctx["fuzzy_match_one_fn"]
    build_lane_rows_fn = ctx["build_lane_rows_fn"]
    ensure_players_filter_state_fn = ctx["ensure_players_filter_state_fn"]
    ensure_players_text_state_fn = ctx["ensure_players_text_state_fn"]
    apply_players_autofill_state_fn = ctx["apply_players_autofill_state_fn"]
    ensure_player_line_input_state_fn = ctx["ensure_player_line_input_state_fn"]
    apply_players_submission_state_fn = ctx["apply_players_submission_state_fn"]
    build_per_player_lines_by_idx_fn = ctx["build_per_player_lines_by_idx_fn"]
    build_player_means_rows_fn = ctx["build_player_means_rows_fn"]
    build_recent_player_stats_rows_fn = ctx["build_recent_player_stats_rows_fn"]
    build_player_market_rows_fn = ctx["build_player_market_rows_fn"]
    append_players_recent_stats_panel_trace_fn = ctx["append_players_recent_stats_panel_trace_fn"]
    append_players_fair_panel_trace_fn = ctx["append_players_fair_panel_trace_fn"]
    append_players_markets_panel_trace_fn = ctx["append_players_markets_panel_trace_fn"]
    append_players_panels_bundle_trace_fn = ctx["append_players_panels_bundle_trace_fn"]
    append_feature_trace_fn = ctx["append_feature_trace_fn"]
    feature_flag_enabled_fn = ctx["feature_flag_enabled_fn"]
    df_contract_view_fn = ctx["df_contract_view_fn"]
    format_num_fn = ctx["format_num_fn"]
    format_pct_fn = ctx["format_pct_fn"]
    format_pct1_fn = ctx["format_pct1_fn"]
    odd_from_prob_fn = ctx["odd_from_prob_fn"]
    state_get_float_fn = ctx["state_get_float_fn"]
    state_get_int_fn = ctx["state_get_int_fn"]
    parse_lines_fn = ctx["parse_lines_fn"]
    fuse_probs_by_precision_fn = ctx["fuse_probs_by_precision_fn"]
    persist_combined_trace_file_fn = ctx["persist_combined_trace_file_fn"]
    playoffs_opt = ctx["playoffs_opt"]

    years, splits, leagues = collect_year_split_league_options(team_games)
    ensure_players_filter_state_fn(session_state)

    def _ensure_choice(key: str, options: list[str], fallback: str | None = None) -> str:
        default = str(fallback if fallback is not None else (options[0] if options else ""))
        current = str(session_state.get(key, default) or default)
        allowed = {str(x) for x in options}
        if current not in allowed:
            current = default
            session_state[key] = current
        return current

    def _on_pl_league_change() -> None:
        session_state["pl_split"] = ""

    def _splits_for_league(league_sel: str) -> list[str]:
        """Splits available for the selected league (fallback: all splits)."""
        try:
            if (league_sel and team_games is not None and not team_games.empty
                    and "league" in team_games.columns and "split" in team_games.columns):
                return sorted(
                    str(x)
                    for x in team_games.loc[team_games["league"].astype(str) == str(league_sel), "split"]
                    .fillna("").astype(str).unique().tolist()
                    if str(x)
                )
        except Exception:
            pass
        return splits

    # Single clean filter row: Ano | Liga | Split | Playoffs.
    with st.container(border=True):
        render_tab_section(st, title="Filtros", subtitle="Feche o recorte antes de abrir lineup, props e medias por jogador.")
        pc1, pc2, pc3, pc4 = st.columns(4)
        with pc1:
            year_options = [""] + [str(y) for y in years]
            _ensure_choice("pl_year", year_options, "")
            p_year = st.selectbox("Ano", options=year_options, key="pl_year", format_func=blank_space_label)
        with pc2:
            league_options = ["", *leagues]
            _ensure_choice("pl_league", league_options, "")
            p_league = st.selectbox(
                "Liga",
                options=league_options,
                key="pl_league",
                format_func=blank_space_label,
                on_change=_on_pl_league_change,
            )
        # Splits depend on the league just picked; compute before rendering Split.
        splits_pl = _splits_for_league(p_league)
        with pc3:
            split_options = ["", *splits_pl]
            _ensure_choice("pl_split", split_options, "")
            p_split = st.selectbox("Split", options=split_options, key="pl_split", format_func=blank_space_label)
        with pc4:
            playoffs_options = ["", "Regular", "Playoffs"]
            _ensure_choice("pl_playoffs", playoffs_options, "")
            p_playoffs = st.selectbox(
                "Playoffs",
                options=playoffs_options,
                key="pl_playoffs",
                format_func=blank_space_label,
            )

    base_filters = Filters(
        year=None if not p_year else int(p_year),
        league=None if not p_league else p_league,
        split=None if not p_split else p_split,
        playoffs=None if not p_playoffs else (True if p_playoffs == "Playoffs" else False),
    )

    with st.spinner("Carregando players do CSV (1x por sessão / cache)..."):
        df_pl = load_player_rows_fn(csv_sig)

    if df_pl is None or df_pl.empty:
        st.warning("Não achei rows de players nesse CSV.")
        dfb = pd.DataFrame()
    else:
        dfb = apply_filters_players_fn(df_pl, base_filters).copy()

    if dfb.empty:
        st.info("Sem jogos nesse recorte.")
        return

    group_df = dfb.copy()
    group_df["win"] = (pd.to_numeric(group_df.get("result"), errors="coerce").fillna(0).astype(int) > 0).astype(int)
    by_player = group_df.groupby("player").agg(games=("win", "size"), wins=("win", "sum")).reset_index()
    by_player["p_smooth"] = (by_player["wins"] + 2.0) / (by_player["games"] + 4.0)
    by_player["rating"] = np.log(by_player["p_smooth"] / (1.0 - by_player["p_smooth"]))

    vocab = sorted([x for x in by_player["player"].fillna("").astype(str).unique().tolist() if x])
    vocab_a = sorted([x for x in dfb[dfb["team"].astype(str) == str(team_a)]["player"].fillna("").astype(str).unique().tolist() if x])
    vocab_b = sorted([x for x in dfb[dfb["team"].astype(str) == str(team_b)]["player"].fillna("").astype(str).unique().tolist() if x])
    if not vocab_a:
        vocab_a = vocab
    if not vocab_b:
        vocab_b = vocab

    render_tab_section(st, title="Cole os players", subtitle="Cole os nomes por time ou use o autofill do lineup mais recente.")
    st.caption("Um por linha. O matching é fuzzy (se errar um pouco o nome, ele sugere).")
    a0, a1 = st.columns([1.4, 2.6])
    with a0:
        if st.button("Auto-preencher players dos times", key="pl_autofill_players"):
            auto_a = latest_lineup_names_fn(df_in=dfb, team_name=team_a, norm_pos_fn=norm_pos_fn)
            auto_b = latest_lineup_names_fn(df_in=dfb, team_name=team_b, norm_pos_fn=norm_pos_fn)
            apply_players_autofill_state_fn(session_state, team_a_players=auto_a, team_b_players=auto_b)
            try:
                st.rerun()
            except Exception:
                st.experimental_rerun()
    with a1:
        st.caption("Preenche Top/JG/Mid/ADC/Sup com o lineup mais recente encontrado no recorte atual.")

    ensure_players_text_state_fn(session_state)
    players_a = parse_players_text_fn(session_state.get("pl_txtA_applied", ""))
    players_b = parse_players_text_fn(session_state.get("pl_txtB_applied", ""))
    resolved_a, notes_a = resolve_players_fn(
        names=players_a,
        vocab=vocab_a,
        fuzzy_match_fn=lambda nm, vv, c: fuzzy_match_one_fn(nm, vv, cutoff=c),
        cutoff=0.6,
    )
    resolved_b, notes_b = resolve_players_fn(
        names=players_b,
        vocab=vocab_b,
        fuzzy_match_fn=lambda nm, vv, c: fuzzy_match_one_fn(nm, vv, cutoff=c),
        cutoff=0.6,
    )
    resolved_a_view = resolved_a if resolved_a else players_a
    resolved_b_view = resolved_b if resolved_b else players_b

    if notes_a or notes_b:
        with st.expander("Ver matching / sugestões", expanded=False):
            if notes_a:
                st.markdown("**Time A**")
                st.write(notes_a)
            if notes_b:
                st.markdown("**Time B**")
                st.write(notes_b)

    tr_a, df_a = _team_rating(by_player=by_player, players=resolved_a, format_num_fn=format_num_fn)
    tr_b, df_b = _team_rating(by_player=by_player, players=resolved_b, format_num_fn=format_num_fn)

    p_players_raw = _sigmoid(tr_a - tr_b)
    p_team_ref = state_get_float_fn(session_state, "_p_map_used", float("nan"))
    if not math.isfinite(p_team_ref):
        p_team_ref = 0.5
    games_a = int(pd.to_numeric(df_a.get("Games"), errors="coerce").fillna(0).sum()) if not df_a.empty else 0
    games_b = int(pd.to_numeric(df_b.get("Games"), errors="coerce").fillna(0).sum()) if not df_b.empty else 0
    n_players_eff = float(min(games_a, games_b))
    n_team_eff = state_get_float_fn(session_state, "_ml_team_games_min", float("nan"))
    fused = fuse_probs_by_precision_fn(
        p_team=p_team_ref,
        p_players=p_players_raw,
        n_team=n_team_eff,
        n_players=n_players_eff,
        team_scale=state_get_float_fn(session_state, "_fit_team_scale_used", state_get_float_fn(session_state, "_fit_team_scale", 1.0)),
        players_scale=state_get_float_fn(
            st.session_state,
            "_fit_players_scale_used",
            state_get_float_fn(st.session_state, "_fit_players_scale", 1.0),
        ),
        coverage=float(max(0.0, min(1.0, n_players_eff / max(1.0, n_team_eff + n_players_eff)))),
        transfer_signal=0.0,
        season_phase=("playoffs" if str(playoffs_opt).lower() in {"playoffs", "true", "1"} else "auto"),
    )
    p_team_a = float(max(0.02, min(0.98, float(fused.get("p_fused", p_team_ref)))))
    w_players = float(fused.get("w_players", float("nan")))
    odd_a = odd_from_prob_fn(p_team_a)
    odd_b = odd_from_prob_fn(1.0 - p_team_a)

    render_tab_section(st, title="Resultado (ML por players)", subtitle="Mostra o blend entre players e time para o confronto atual.")
    st.markdown(f"**Time A:** {format_num_fn(odd_a, 2)}  |  **Time B:** {format_num_fn(odd_b, 2)}")
    st.caption(
        f"Conexão com ML de times: p_players={format_pct_fn(p_players_raw)} | "
        f"p_time={format_pct_fn(p_team_ref)} | blend={format_pct_fn(p_team_a)} "
        f"(w_players={format_num_fn(100.0 * w_players, 0)}% | n_team={format_num_fn(n_team_eff, 1)} | n_players={format_num_fn(n_players_eff, 1)})"
    )

    cta, ctb = st.columns(2)
    with cta:
        st.markdown("**Detalhe Time A**")
        if df_a.empty:
            st.info("Nenhum player reconhecido na base.")
        else:
            st.dataframe(df_a, width="stretch", hide_index=True)
    with ctb:
        st.markdown("**Detalhe Time B**")
        if df_b.empty:
            st.info("Nenhum player reconhecido na base.")
        else:
            st.dataframe(df_b, width="stretch", hide_index=True)

    st.divider()
    render_tab_section(st, title="Mercados de players", subtitle="Defina linhas por lane e por jogador; a atualizacao so roda quando voce confirmar a analise.")
    st.caption('Defina linhas por lane/jogador. Atualiza apenas ao clicar em "Analisar players".')

    lane_rows = build_lane_rows_fn(resolved_a_view, resolved_b_view, ["top", "jng", "mid", "bot", "sup"])
    ensure_player_line_input_state_fn(session_state, lanes=len(lane_rows))

    with st.form("players_input_form", clear_on_submit=False):
        col_a, col_b = st.columns(2)
        with col_a:
            st.text_area("Time A — players (5)", height=120, key="pl_txtA_input")
        with col_b:
            st.text_area("Time B — players (5)", height=120, key="pl_txtB_input")
        submitted_top = st.form_submit_button("Analisar players", type="primary", key="pl_submit_top")
        st.caption('As lanes e odds abaixo atualizam quando clicar em "Analisar players".')
        st.markdown("##### Linhas individuais (10 jogadores)")
        st.caption("Para cada jogador, informe linhas separadas por vírgula (ex.: 2.5,3.5). O cálculo é individual: passou ou não passou da linha.")
        for idx, row in enumerate(lane_rows):
            c0, c1, c2 = st.columns([1.1, 1.45, 1.45])
            with c0:
                st.markdown(f"**{row['Lane']}**  \nTime A: {row['A'] or '-'}  \nTime B: {row['B'] or '-'}")
            with c1:
                st.markdown(f"**{row['A'] or '-'}**")
                st.text_input(f"Kills A ({row['Lane']})", key=f"pl_in_{idx}_kills_A")
                st.text_input(f"Deaths A ({row['Lane']})", key=f"pl_in_{idx}_deaths_A")
                st.text_input(f"Assists A ({row['Lane']})", key=f"pl_in_{idx}_assists_A")
            with c2:
                st.markdown(f"**{row['B'] or '-'}**")
                st.text_input(f"Kills B ({row['Lane']})", key=f"pl_in_{idx}_kills_B")
                st.text_input(f"Deaths B ({row['Lane']})", key=f"pl_in_{idx}_deaths_B")
                st.text_input(f"Assists B ({row['Lane']})", key=f"pl_in_{idx}_assists_B")
        submitted_bottom = st.form_submit_button("Analisar players", type="primary", key="pl_submit_bottom")
        submitted_players = bool(submitted_top or submitted_bottom)

    if submitted_players:
        apply_players_submission_state_fn(session_state, lanes=len(lane_rows))
        try:
            st.rerun()
        except Exception:
            st.experimental_rerun()

    if not any(str(x.get("A") or "").strip() or str(x.get("B") or "").strip() for x in lane_rows):
        st.info("Informe players para abrir os mercados por lane.")
        return

    wf_m = state_get_float_fn(session_state, "resumo_mix_w_model", 40.0)
    wf_h = state_get_float_fn(session_state, "resumo_mix_w_laplace", 40.0)
    wf_s = state_get_float_fn(session_state, "resumo_mix_w_sc", 20.0)
    min_h2h_players = max(1, state_get_int_fn(session_state, "resumo_min_sample_h2h", 3))
    ff_players_shadow_trace = feature_flag_enabled_fn("ff_players_panels_shadow_trace", default=True)

    med_rows = build_player_means_rows_fn(dfb=dfb, lane_rows=lane_rows, team_a=team_a, team_b=team_b, format_num_fn=format_num_fn)
    if med_rows:
        st.markdown("#### Médias por jogador")
        st.caption("Base estatística usada no modelo de players por lane.")
        dfm = pd.DataFrame(med_rows)
        dfm = df_contract_view_fn(
            dfm,
            ["Lane", "Time", "Player", "Amostra", "Kills (media)", "Kills (sd)", "Deaths (media)", "Deaths (sd)", "Assists (media)", "Assists (sd)"],
            context="Players > Médias",
            fill_value="-",
        )
        st.dataframe(dfm, width="stretch", hide_index=True)
        st.divider()

    recent_rows = build_recent_player_stats_rows_fn(
        dfb=dfb,
        lane_rows=lane_rows,
        team_a=team_a,
        team_b=team_b,
        format_num_fn=format_num_fn,
        max_games_per_player=8,
    )
    if recent_rows:
        st.markdown("#### Stats recentes dos players")
        st.caption("Últimos jogos por player/lane: campeão, resultado, KDA, KP%, duração e adversário.")
        dfr = pd.DataFrame(recent_rows)
        rows_before = len(dfr)
        rf1, rf2, rf3, rf4 = st.columns(4)
        with rf1:
            rf_team_opts = ["Todos", *sorted([x for x in dfr["Time"].astype(str).unique().tolist() if str(x).strip()])]
            _ensure_choice("pl_stats_filter_team", rf_team_opts, "Todos")
            rf_team = st.selectbox("Stats - Time", rf_team_opts, key="pl_stats_filter_team")
        with rf2:
            rf_lane_opts = ["Todos", *sorted(dfr["Lane"].astype(str).unique().tolist())]
            _ensure_choice("pl_stats_filter_lane", rf_lane_opts, "Todos")
            rf_lane = st.selectbox("Stats - Lane", rf_lane_opts, key="pl_stats_filter_lane")
        with rf3:
            rf_player_opts = ["Todos", *sorted(dfr["Player"].astype(str).unique().tolist())]
            _ensure_choice("pl_stats_filter_player", rf_player_opts, "Todos")
            rf_player = st.selectbox("Stats - Player", rf_player_opts, key="pl_stats_filter_player")
        with rf4:
            rf_opp_opts = ["Todos", *sorted(dfr["Oponente"].astype(str).unique().tolist())]
            _ensure_choice("pl_stats_filter_opp", rf_opp_opts, "Todos")
            rf_opp = st.selectbox("Stats - Oponente", rf_opp_opts, key="pl_stats_filter_opp")
        if rf_team != "Todos":
            dfr = dfr[dfr["Time"].astype(str) == str(rf_team)].copy()
        if rf_lane != "Todos":
            dfr = dfr[dfr["Lane"].astype(str) == str(rf_lane)].copy()
        if rf_player != "Todos":
            dfr = dfr[dfr["Player"].astype(str) == str(rf_player)].copy()
        if rf_opp != "Todos":
            dfr = dfr[dfr["Oponente"].astype(str) == str(rf_opp)].copy()
        append_players_recent_stats_panel_trace_fn(
            append_feature_trace_fn=append_feature_trace_fn,
            enabled=bool(ff_players_shadow_trace),
            teamA=team_a,
            teamB=team_b,
            team_filter=rf_team,
            lane_filter=rf_lane,
            player_filter=rf_player,
            opp_filter=rf_opp,
            rows_before=rows_before,
            rows_after=len(dfr),
        )
        dfr = df_contract_view_fn(
            dfr,
            ["Lane", "Time", "Player", "Campeão", "Resultado", "Tempo", "K/D/A", "KDA", "KP%", "Dano", "Oponente", "Data"],
            context="Players > Stats recentes",
            fill_value="-",
        )
        st.dataframe(dfr, width="stretch", hide_index=True)
        st.divider()

    per_player_lines_by_idx = build_per_player_lines_by_idx_fn(
        session_state=session_state,
        lane_rows=lane_rows,
        parse_lines_fn=parse_lines_fn,
    )
    out_rows, fair_rows = build_player_market_rows_fn(
        dfb=dfb,
        lane_rows=lane_rows,
        per_player_lines_by_idx=per_player_lines_by_idx,
        team_a=team_a,
        team_b=team_b,
        wf_m=float(wf_m),
        wf_h=float(wf_h),
        wf_s=float(wf_s),
        odd_from_prob_fn=odd_from_prob_fn,
        format_num_fn=format_num_fn,
        format_pct_fn=format_pct1_fn,
        max_odd=float(session_state.get("resumo_max_odd", 2.0) or 2.0),
        require_model=False,
        min_h2h_games=int(min_h2h_players),
    )
    if not out_rows:
        st.info("Sem dados suficientes para montar mercados de players no recorte atual.")
        return

    if fair_rows:
        st.markdown("#### Fair (Modelo) por jogador")
        st.caption("Odds justas do modelo para cada jogador/linha em Kills, Deaths e Assists.")
        dff = pd.DataFrame(fair_rows)
        ff1, ff2, ff3 = st.columns(3)
        with ff1:
            ff_team_opts = ["Todos", team_a, team_b]
            _ensure_choice("pl_fair_filter_team", ff_team_opts, "Todos")
            ff_team = st.selectbox("Fair - Time", ff_team_opts, key="pl_fair_filter_team")
        with ff2:
            ff_lane_opts = ["Todos", *sorted(dff["Lane"].unique().tolist())]
            _ensure_choice("pl_fair_filter_lane", ff_lane_opts, "Todos")
            ff_lane = st.selectbox("Fair - Lane", ff_lane_opts, key="pl_fair_filter_lane")
        with ff3:
            ff_player_opts = ["Todos", *sorted(dff["Player"].unique().tolist())]
            _ensure_choice("pl_fair_filter_player", ff_player_opts, "Todos")
            ff_player = st.selectbox("Fair - Player", ff_player_opts, key="pl_fair_filter_player")
        if ff_team != "Todos":
            dff = dff[dff["Time"].astype(str) == str(ff_team)].copy()
        if ff_lane != "Todos":
            dff = dff[dff["Lane"].astype(str) == str(ff_lane)].copy()
        if ff_player != "Todos":
            dff = dff[dff["Player"].astype(str) == str(ff_player)].copy()
        append_players_fair_panel_trace_fn(
            append_feature_trace_fn=append_feature_trace_fn,
            enabled=bool(ff_players_shadow_trace),
            teamA=team_a,
            teamB=team_b,
            team_filter=ff_team,
            lane_filter=ff_lane,
            player_filter=ff_player,
            rows_after=len(dff),
            rows_total=len(fair_rows),
        )
        dff = df_contract_view_fn(
            dff,
            ["Lane", "Time", "Player", "Mercado", "Media", "SD", "Linha", "Acima (%)", "Odd Acima", "Abaixo (%)", "Odd Abaixo", "Amostra"],
            context="Players > Fair",
            fill_value="-",
        )
        st.dataframe(dff, width="stretch", hide_index=True)

    st.divider()
    st.markdown("#### Mercados de Players (Modelo/Hist/Mix)")
    dfo = pd.DataFrame(out_rows)
    if not dfo.empty:
        st.caption(
            f'H2H só entra no Odd Mix quando atingir a amostra mínima ({int(min_h2h_players)} jogos). '
            'Se não atingir, confira "Obs Mix". Para "-" em odds (principalmente H2H), veja "Obs Odds".'
        )
    f1, f2, f3, f4 = st.columns(4)
    with f1:
        mkt_team_opts = ["Todos", team_a, team_b]
        _ensure_choice("pl_mkt_filter_team", mkt_team_opts, "Todos")
        team_filter = st.selectbox("Filtro Time", mkt_team_opts, key="pl_mkt_filter_team")
    with f2:
        mkt_lane_opts = ["Todos", *sorted(dfo["Lane"].unique().tolist())]
        _ensure_choice("pl_mkt_filter_lane", mkt_lane_opts, "Todos")
        lane_filter = st.selectbox("Filtro Lane", mkt_lane_opts, key="pl_mkt_filter_lane")
    with f3:
        mkt_market_opts = ["Todos", *sorted(dfo["Mercado"].unique().tolist())]
        _ensure_choice("pl_mkt_filter_market", mkt_market_opts, "Todos")
        market_filter = st.selectbox("Filtro Mercado", mkt_market_opts, key="pl_mkt_filter_market")
    with f4:
        mkt_player_opts = ["Todos", *sorted(dfo["Player"].unique().tolist())]
        _ensure_choice("pl_mkt_filter_player", mkt_player_opts, "Todos")
        player_filter = st.selectbox("Filtro Player", mkt_player_opts, key="pl_mkt_filter_player")
    if team_filter != "Todos":
        dfo = dfo[dfo["Team"].astype(str) == str(team_filter)].copy()
    if lane_filter != "Todos":
        dfo = dfo[dfo["Lane"].astype(str) == str(lane_filter)].copy()
    if market_filter != "Todos":
        dfo = dfo[dfo["Mercado"].astype(str) == str(market_filter)].copy()
    if player_filter != "Todos":
        dfo = dfo[dfo["Player"].astype(str) == str(player_filter)].copy()

    append_players_markets_panel_trace_fn(
        append_feature_trace_fn=append_feature_trace_fn,
        enabled=bool(ff_players_shadow_trace),
        teamA=team_a,
        teamB=team_b,
        team_filter=team_filter,
        lane_filter=lane_filter,
        market_filter=market_filter,
        player_filter=player_filter,
        rows_after=len(dfo),
        rows_total=len(out_rows),
        fair_rows_total=len(fair_rows),
        min_h2h_games=int(min_h2h_players),
    )
    session_state["_ml_trace_players"] = _build_trace_rows(out_rows)
    append_players_panels_bundle_trace_fn(
        append_feature_trace_fn=append_feature_trace_fn,
        enabled=bool(ff_players_shadow_trace),
        teamA=team_a,
        teamB=team_b,
        recent_rows_total=len(recent_rows),
        market_rows_total=len(out_rows),
        fair_rows_total=len(fair_rows),
    )
    persist_combined_trace_file_fn()
    player_cols = ["Lane", "Team", "Player", "Mercado", "Lado", "Linha", "Stats", "H2H", "Odd (Modelo)", "Odd (Hist)", "Odd (H2H)", "Odd (Mix)"]
    if "Obs Odds" in dfo.columns and bool((dfo["Obs Odds"].astype(str).str.strip() != "").any()):
        player_cols.append("Obs Odds")
    player_cols.append("Obs Mix")
    dfo = df_contract_view_fn(
        dfo,
        [c for c in player_cols if c not in {"Obs Odds"}],
        optional_cols=["Obs Odds"],
        context="Players > Mercados",
        fill_value="-",
    )
    st.dataframe(dfo, width="stretch", hide_index=True)
    with st.expander("Trace de calibração (Players)"):
        trace_rows = session_state.get("_ml_trace_players", []) or []
        if trace_rows:
            st.dataframe(pd.DataFrame(trace_rows), width="stretch", hide_index=True)
            st.download_button(
                "Baixar trace (Players) JSON",
                data=json.dumps(trace_rows, ensure_ascii=False, indent=2).encode("utf-8"),
                file_name="ml_trace_players.json",
                mime="application/json",
                key="dl_trace_players_json",
                on_click="ignore",
            )
        else:
            st.caption("Sem trace nesta execução.")
