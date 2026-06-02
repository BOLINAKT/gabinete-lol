"""Rankings tab renderer."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from app_core.tab_filters_core import collect_year_split_league_options, scope_has_playoffs
from app_core.tab_state_core import ensure_blank_keys, normalize_select_key, reset_keys, select_placeholder
from app_core.tab_ui_core import render_tab_hero, render_tab_section


def render_rankings_tab(
    *,
    st: Any,
    team_games: pd.DataFrame,
    Filters: Any,
    artifact_path: str,
    as_of_date: Any,
    half_life_days: float,
    mlcore_rank_table_v2_fn: Callable[..., pd.DataFrame],
    elo_rank_table_fn: Callable[..., pd.DataFrame],
    format_num_fn: Callable[[float, int], str],
) -> None:
    render_tab_hero(
        st,
        title="Rankings",
        subtitle="Tabela principal do ML core v2 com fallback de Elo para auditoria e cobertura.",
        eyebrow="Power ratings",
        chips=[f"As of {as_of_date}", f"Half-life {format_num_fn(float(half_life_days), 0)}d"],
    )
    render_tab_section(
        st,
        title="Recorte do ranking",
        subtitle="Filtre liga, ano, split e playoffs antes de abrir a tabela principal.",
    )

    _, _, leagues = collect_year_split_league_options(team_games)
    ensure_blank_keys(st.session_state, ["rank_league_visual", "rank_year_visual", "rank_split_visual", "rank_po_visual"])

    def _on_rank_league_change() -> None:
        reset_keys(st.session_state, ["rank_year_visual", "rank_split_visual"])

    c1, c2, c3, c4 = st.columns([1.2, 1.0, 1.0, 1.0])
    with c1:
        rank_league = st.selectbox(
            "Liga",
            options=["", *leagues],
            key="rank_league_visual",
            format_func=select_placeholder,
            on_change=_on_rank_league_change,
        )

    df_opt = team_games
    if rank_league and df_opt is not None and not df_opt.empty and "league" in df_opt.columns:
        df_opt = df_opt[df_opt["league"].astype(str) == str(rank_league)].copy()

    years = []
    try:
        if df_opt is not None and not df_opt.empty and "year" in df_opt.columns:
            years = sorted([int(x) for x in pd.to_numeric(df_opt["year"], errors="coerce").dropna().unique().tolist()])
    except Exception:
        years = []

    with c2:
        normalize_select_key(st.session_state, "rank_year_visual", [""] + [str(y) for y in years])
        rank_year = st.selectbox(
            "Ano",
            options=[""] + [str(y) for y in years],
            key="rank_year_visual",
            format_func=select_placeholder,
        )

    df_opt2 = df_opt
    if rank_year and df_opt2 is not None and not df_opt2.empty and "year" in df_opt2.columns:
        try:
            df_opt2 = df_opt2[pd.to_numeric(df_opt2["year"], errors="coerce") == int(rank_year)].copy()
        except Exception:
            pass

    splits = []
    try:
        if df_opt2 is not None and not df_opt2.empty and "split" in df_opt2.columns:
            splits = sorted([str(x) for x in df_opt2["split"].fillna("").astype(str).unique().tolist() if str(x)])
    except Exception:
        splits = []

    with c3:
        normalize_select_key(st.session_state, "rank_split_visual", ["", *splits])
        rank_split = st.selectbox(
            "Split",
            options=["", *splits],
            key="rank_split_visual",
            format_func=select_placeholder,
        )

    # Playoffs box appears ONLY when the chosen (liga, ano, split) has playoff
    # games — same pattern as the other tabs (scope_has_playoffs).
    if scope_has_playoffs(team_games, league=rank_league, year=rank_year, split=rank_split):
        with c4:
            normalize_select_key(st.session_state, "rank_po_visual", ["", "Regular", "Playoffs"])
            rank_playoffs = st.selectbox(
                "Playoffs",
                options=["", "Regular", "Playoffs"],
                key="rank_po_visual",
                format_func=select_placeholder,
            )
        rank_playoffs = st.session_state.get("rank_po_visual", "") or ""
    else:
        rank_playoffs = ""

    rank_filters = Filters(
        year=None if not rank_year else int(rank_year),
        league=None if not rank_league else rank_league,
        split=None if not rank_split else rank_split,
        playoffs=None if not rank_playoffs else (True if rank_playoffs == "Playoffs" else False),
    )

    render_tab_section(
        st,
        title="Ranking principal",
        subtitle="O painel prioriza o ML core v2 e cai para Elo quando o recorte pede cobertura extra.",
    )
    if "rank_top_n" not in st.session_state:
        st.session_state["rank_top_n"] = 200
    top_n = st.slider("Top N (ranking global)", min_value=50, max_value=400, step=50, key="rank_top_n")
    rank_fetch_n = int(max(int(top_n), 600))
    df_rank_v2 = mlcore_rank_table_v2_fn(artifact_path, as_of=as_of_date, top_n=rank_fetch_n)
    df_rank_v2_view = df_rank_v2.copy()
    if rank_league and (not df_rank_v2_view.empty) and ("league" in df_rank_v2_view.columns):
        df_rank_v2_view = df_rank_v2_view[df_rank_v2_view["league"].astype(str) == str(rank_league)].copy()

    df_fallback = pd.DataFrame()
    try:
        df_fallback = elo_rank_table_fn(
            team_games,
            filters=rank_filters,
            half_life_days=float(half_life_days),
            k_factor=24.0,
            base_rating=1500.0,
        )
        if not df_fallback.empty:
            df_fallback = df_fallback.head(int(top_n)).copy()
    except Exception:
        df_fallback = pd.DataFrame()

    df_rank_main = df_rank_v2_view.copy()
    rank_main_source = "ML core v2"
    no_filters = (not rank_league) and (not rank_year) and (not rank_split) and (not rank_playoffs)
    if df_rank_main.empty:
        if not df_fallback.empty:
            df_rank_main = df_fallback.copy()
            rank_main_source = "Elo fallback (CSV)"
    elif no_filters:
        try:
            v2_leagues = set(df_rank_main["league"].astype(str).str.strip()) if "league" in df_rank_main.columns else set()
            v2_teams = (
                set(df_rank_main["team"].astype(str).str.strip().str.casefold()) if "team" in df_rank_main.columns else set()
            )
            need_fallback = False
            if "LCK" not in v2_leagues:
                need_fallback = True
            for featured in ["gen.g", "t1"]:
                if featured not in v2_teams:
                    need_fallback = True
                    break
            if need_fallback and (not df_fallback.empty):
                df_rank_main = df_fallback.copy()
                rank_main_source = "Elo fallback (CSV)"
        except Exception:
            pass

    if df_rank_main.empty:
        st.warning("Não consegui gerar ranking para esse recorte (v2 + fallback sem dados).")
    else:
        st.caption(f"Fonte do ranking principal: {rank_main_source}")
        if rank_league and ("league" in df_rank_main.columns):
            df_rank_main = df_rank_main[df_rank_main["league"].astype(str) == str(rank_league)].copy()
        if rank_year and ("year" in df_rank_main.columns):
            try:
                df_rank_main = df_rank_main[pd.to_numeric(df_rank_main["year"], errors="coerce") == int(rank_year)].copy()
            except Exception:
                pass
        if rank_split and ("split" in df_rank_main.columns):
            df_rank_main = df_rank_main[df_rank_main["split"].astype(str) == str(rank_split)].copy()
        if rank_playoffs and ("playoffs" in df_rank_main.columns):
            try:
                want_playoffs = True if str(rank_playoffs) == "Playoffs" else False
                po_ser = df_rank_main["playoffs"]
                if po_ser.dtype == bool:
                    df_rank_main = df_rank_main[po_ser == want_playoffs].copy()
                else:
                    df_rank_main = df_rank_main[
                        pd.to_numeric(po_ser, errors="coerce").fillna(0).astype(int).astype(bool) == want_playoffs
                    ].copy()
            except Exception:
                pass

        if no_filters:
            try:
                df_cov = pd.DataFrame()
                if not df_rank_main.empty:
                    df_cov = df_rank_main.copy()
                if not df_fallback.empty:
                    df_cov = pd.concat([df_cov, df_fallback.copy()], ignore_index=True) if not df_cov.empty else df_fallback.copy()
                if not df_cov.empty and ("league" in df_cov.columns):
                    score_col = None
                    for col in ["total_strength", "elo", "rating", "score"]:
                        if col in df_cov.columns:
                            score_col = col
                            break
                    if score_col is not None:
                        df_cov["_score_num"] = pd.to_numeric(df_cov[score_col], errors="coerce")
                        df_cov = df_cov.sort_values("_score_num", ascending=False, na_position="last")
                        top_limit = int(top_n)
                        top = df_cov.head(top_limit).copy()
                        majors = ["LCK", "LPL", "LEC", "LCS"]
                        present = set(top["league"].astype(str).tolist())
                        extras = []
                        for league in majors:
                            if league in present:
                                continue
                            cand = df_cov[df_cov["league"].astype(str) == league].head(1)
                            if not cand.empty:
                                extras.append(cand)
                        if extras:
                            top = pd.concat([top, *extras], ignore_index=True)
                            dedup_cols = [c for c in ["team", "league"] if c in top.columns]
                            if dedup_cols:
                                top = top.drop_duplicates(subset=dedup_cols, keep="first")
                            if top.shape[0] > top_limit:
                                major_df = top[top["league"].astype(str).isin(majors)].copy()
                                other_df = top[~top["league"].astype(str).isin(majors)].copy()
                                top = pd.concat([major_df, other_df], ignore_index=True).head(top_limit).copy()
                            feat_rows = []
                            for team_name in ["gen.g", "t1"]:
                                cand = df_cov[df_cov["team"].astype(str).str.strip().str.casefold() == team_name].head(1)
                                if not cand.empty:
                                    feat_rows.append(cand)
                            if feat_rows:
                                top = pd.concat([top, *feat_rows], ignore_index=True)
                                if dedup_cols:
                                    top = top.drop_duplicates(subset=dedup_cols, keep="first")
                                top = top.head(top_limit).copy()
                            df_rank_main = top.drop(columns=["_score_num"], errors="ignore")
            except Exception:
                pass

        if not df_rank_main.empty:
            df_rank_main = df_rank_main.head(int(top_n)).copy()
        st.dataframe(df_rank_main, width="stretch", height=520)

    st.divider()
    with st.expander("Ranking antigo (Elo / debug)", expanded=False):
        st.caption("Elo é atualizado jogo a jogo; jogos mais recentes valem mais (half-life).")
        c_a, c_b, c_c = st.columns([1, 1, 2])
        with c_a:
            k_factor = st.number_input("K (agressividade)", min_value=4.0, max_value=64.0, value=24.0, step=1.0)
        with c_b:
            base_rating = st.number_input("Base Elo", min_value=1000.0, max_value=2000.0, value=1500.0, step=10.0)
        with c_c:
            st.markdown("**Dica:** K menor = ranking mais estável | K maior = reage mais rápido.")

        elo_df = elo_rank_table_fn(
            team_games,
            filters=rank_filters,
            half_life_days=float(half_life_days),
            k_factor=float(k_factor),
            base_rating=float(base_rating),
        )
        if elo_df.empty:
            st.info("Sem jogos suficientes nesse recorte para calcular ranking.")
            return

        st.dataframe(elo_df.head(50), width="stretch", height=520)
        if "league" not in elo_df.columns or elo_df["league"].astype(str).str.len().sum() <= 0:
            return

        st.markdown("#### Força média por liga (no recorte)")
        try:
            elo_num = pd.to_numeric(elo_df["elo"], errors="coerce")
        except Exception:
            elo_num = pd.Series([None] * len(elo_df))
        tmp = elo_df.copy()
        tmp["elo_num"] = elo_num
        by_league = tmp.dropna(subset=["elo_num"]).groupby("league", dropna=False)["elo_num"].agg(["mean", "count"]).reset_index()
        by_league = by_league.sort_values("mean", ascending=False)
        by_league["mean"] = by_league["mean"].apply(lambda x: format_num_fn(x, 0))
        st.dataframe(by_league, width="stretch", height=260)
