from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import streamlit as st

# Opções do seletor de BO. Constante de módulo para permitir override por
# outros hosts (o Gabinete Dota inclui BO2; o LoL segue 1/3/5).
BO_OPTIONS: List[int] = [1, 3, 5]

from app_core.flow_runtime_core import (
    apply_flow_line_values,
    consume_pending_auto_analyze,
    ensure_matchup_selection_state,
    request_analysis_refresh,
    request_pending_reset_matchup,
    set_flow_stage,
    set_lines_loaded_key,
    set_matchup_key,
    set_pending_auto_analyze,
    set_pending_load,
)
from app_core.schedule_state_core import (
    get_schedule_games,
    get_schedule_line_fields,
    get_schedule_line_inputs,
    init_schedule_line_inputs,
    resolve_schedule_line_hc_team,
    save_schedule_games,
)
from app_core.stats_config import line_input_hints, line_key_by_label

# Exemplos dos inputs de linha da Agenda (variante "agenda"; diverge da tela
# principal de propósito). Fonte única: STATS_MARKET_CONFIG.input_hint_agenda —
# mercado novo herda o placeholder sozinho.
_LINE_INPUT_LABELS: Dict[str, str] = line_input_hints("agenda")


def _safe_rerun() -> None:
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


_CHAVE_NAO_RESOLVIDOS = "_agenda_times_nao_resolvidos"


def set_pending_unresolved(session_state: Any, faltou: list) -> None:
    """Guarda o que nao deu para casar, para a tela dizer em vez de calar."""
    try:
        session_state[_CHAVE_NAO_RESOLVIDOS] = list(faltou or [])
    except (TypeError, KeyError, AttributeError):
        pass


def _resolver_time_salvo(session_state: Any, cru: str, times: Sequence[str]) -> str:
    """Nome guardado na agenda -> nome do CSV, ou "" quando nao da.

    Usa o MESMO resolvedor da aba Jogos, com os apelidos que ele ja ensinou.
    Antes daqui a comparacao era `nome in times` — exata, letra por letra —, e
    qualquer diferenca de sufixo deixava o campo vazio sem avisar.
    """
    alvo = str(cru or "").strip()
    if not alvo:
        return ""
    if alvo in times:
        return alvo
    try:
        from pathlib import Path

        from app_core.schedule_import_core import (
            load_schedule_aliases,
            resolve_schedule_team,
        )
        # Mesma raiz e mesmo arquivo de apelidos que a aba Jogos usa.
        raiz = Path(__file__).resolve().parents[1]
        apelidos = load_schedule_aliases(session_state, raiz / "user_team_aliases.json")
        achado, ok = resolve_schedule_team(alvo, list(times), apelidos)
        return str(achado) if ok else ""
    except Exception:
        return ""


def render_matchup_selection(
    session_state: dict[str, Any],
    *,
    flow_stage: str,
    teams: Sequence[str],
    season_label: str,
    matchup_key_fn: Callable[[Any, Any, Any], str],
    save_lines_for_matchup_fn: Callable[[str], Any],
    load_lines_for_matchup_fn: Callable[[str], Any],
    reset_flow_fn: Callable[..., Any],
) -> tuple[str, str, int]:
    st.subheader("Time 1 - Time 2")
    st.subheader("Confronto")

    if flow_stage == "select":
        games = get_schedule_games(session_state)
        if isinstance(games, list) and games:
            with st.expander("Selecionar jogo salvo (Agenda)", expanded=False):
                labels: list[str] = []
                for game in games:
                    try:
                        d = str(game.get("date", "") or "").strip()
                        t = str(game.get("time", "") or "").strip()
                        dt = (d + (" " + t if t else "")).strip()
                        league = str(game.get("league", "") or "").strip()
                        ta = str(game.get("teamA", "") or "").strip()
                        tb = str(game.get("teamB", "") or "").strip()
                        bo_g = game.get("bo", 3)
                    except Exception:
                        dt, league, ta, tb, bo_g = "", "", "", "", 3
                    parts: list[str] = []
                    if dt:
                        parts.append(dt)
                    if league:
                        parts.append(league)
                    parts.append(f"{ta} x {tb}")
                    parts.append(f"BO{bo_g}")
                    labels.append(" | ".join(parts))

                pick = st.selectbox(
                    "Jogo salvo",
                    options=[-1, *list(range(len(labels)))],
                    key="main_saved_game_idx",
                    format_func=lambda x: "Selecione ..." if int(x) == -1 else labels[int(x)],
                )
                bcols = st.columns([1, 2])
                with bcols[0]:
                    do_pick = st.button(
                        "Usar este jogo",
                        type="primary",
                        width="stretch",
                        disabled=(int(pick) == -1),
                        key="main_saved_game_use",
                    )
                with bcols[1]:
                    st.caption("Dica: se o nome do time não bater com o CSV, use a aba **Jogos** para resolver/editar o texto.")

                if int(pick) >= 0:
                    try:
                        selected_game = games[int(pick)]
                    except Exception:
                        selected_game = None

                    if isinstance(selected_game, dict):
                        team_a_sel = str(selected_game.get("teamA", "") or "").strip()
                        team_b_sel = str(selected_game.get("teamB", "") or "").strip()
                        bo_sel = int(selected_game.get("bo", 3) or 3) if str(selected_game.get("bo", "")).strip() else 3

                        lines_saved = selected_game.get("lines_saved")
                        if not isinstance(lines_saved, dict):
                            lines_saved = {}

                        with st.expander("Linhas deste jogo (opcional) — salvar e/ou analisar", expanded=False):
                            prefix = f"ag_lines_{int(pick)}_"
                            fields = list(get_schedule_line_fields())
                            init_schedule_line_inputs(session_state, prefix, lines_saved, fields=tuple(fields))

                            st.markdown("**Mercados principais**")
                            line_cols = st.columns(3)
                            for idx, (market_label, line_key) in enumerate(line_key_by_label().items()):
                                with line_cols[(idx // 2) % 3]:
                                    st.text_input(
                                        _LINE_INPUT_LABELS.get(line_key, market_label),
                                        key=prefix + line_key,
                                    )

                            with st.expander("Extras (opcional)", expanded=False):
                                st.text_input(f"Total Kills {team_a_sel or 'Time 1'} (ex: 16.5)", key=prefix + "teamA_kills_line_text")
                                st.text_input(f"Total Kills {team_b_sel or 'Time 2'} (ex: 15.5)", key=prefix + "teamB_kills_line_text")

                                st.caption("Handicap: interpreta como (métrica_for + handicap) > métrica_against (sem push; use .5).")
                                if team_a_sel and team_b_sel:
                                    _cur, hc_opts = resolve_schedule_line_hc_team(
                                        session_state,
                                        prefix,
                                        team_a=team_a_sel,
                                        team_b=team_b_sel,
                                    )
                                    st.selectbox(
                                        "Handicap Kills — Time",
                                        options=hc_opts,
                                        key=prefix + "hc_kills_team",
                                    )
                                    hc_team, _ = resolve_schedule_line_hc_team(
                                        session_state,
                                        prefix,
                                        team_a=team_a_sel,
                                        team_b=team_b_sel,
                                        write_back=False,
                                    )
                                else:
                                    hc_team = team_a_sel or team_b_sel

                                st.text_input(f"HC Kills ({hc_team or 'Time'}) (ex: -2.5)", key=prefix + "hc_kills_text")
                                st.text_input(f"HC Torres ({team_a_sel or 'Time 1'}) (ex: -3.5)", key=prefix + "hc_towers_text")
                                st.text_input(f"HC Dragões ({team_a_sel or 'Time 1'}) (ex: -1.5)", key=prefix + "hc_dragons_text")
                                st.text_input("Linha Kills (para ML + Totais)", key=prefix + "combo_kills_text")
                                st.text_input("Linha Tempo (para ML + Totais)", key=prefix + "combo_time_text")

                            s1, s2 = st.columns(2)
                            with s1:
                                save_lines = st.button("Salvar linhas", width="stretch", key=f"ag_save_lines_{int(pick)}")
                            with s2:
                                analyze = st.button(
                                    "Analisar confronto",
                                    type="primary",
                                    width="stretch",
                                    key=f"ag_analyze_{int(pick)}",
                                )

                            if save_lines or analyze:
                                line_values = get_schedule_line_inputs(session_state, prefix, fields=tuple(fields))
                                try:
                                    games[int(pick)]["lines_saved"] = line_values
                                    save_schedule_games(session_state, games)
                                except Exception:
                                    pass

                                if save_lines:
                                    st.success("Linhas salvas para este jogo.")
                                    _safe_rerun()

                                if analyze:
                                    set_pending_load(
                                        session_state,
                                        {
                                            "_reset_flow": True,
                                            "teamA": team_a_sel if team_a_sel in teams else "",
                                            "teamB": team_b_sel if team_b_sel in teams else "",
                                            "bo": bo_sel,
                                        },
                                    )
                                    set_pending_auto_analyze(session_state, {"lines": line_values})
                                    _safe_rerun()

                if do_pick and int(pick) >= 0:
                    try:
                        game = games[int(pick)]
                        prefix = f"ag_lines_{int(pick)}_"
                        current_line_values = get_schedule_line_inputs(session_state, prefix, fields=tuple(get_schedule_line_fields()))
                        if isinstance(game, dict):
                            game["lines_saved"] = dict(current_line_values)
                            save_schedule_games(session_state, games)
                        payload = {"_reset_flow": True}
                        # NOME EXATO NAO BASTA (defeito relatado por ele em
                        # 15/09/2026). A agenda dele tinha "Barczaca Esports" e
                        # o CSV tem "Barczaca Esports by Yumisu" — o campo
                        # Time 1 ficava vazio, EM SILENCIO, e ele so via que
                        # nada aconteceu.
                        #
                        # O resolvedor com apelidos aprendidos ja existia no
                        # projeto (e a mesma coisa que a aba Jogos usa ao
                        # importar); aqui ele nunca tinha sido chamado.
                        _res_a = _resolver_time_salvo(session_state, str(game.get("teamA", "")), teams)
                        _res_b = _resolver_time_salvo(session_state, str(game.get("teamB", "")), teams)
                        if _res_a:
                            payload["teamA"] = _res_a
                        if _res_b:
                            payload["teamB"] = _res_b
                        # O que NAO resolveu fica dito, com o palpite. Campo
                        # vazio sem explicacao e o pior desfecho: parece que o
                        # botao nao funcionou.
                        _faltou = [(rot, str(game.get(ch, "") or ""))
                                   for rot, ch, r in (("Time 1", "teamA", _res_a),
                                                      ("Time 2", "teamB", _res_b))
                                   if not r and str(game.get(ch, "") or "").strip()]
                        if _faltou:
                            set_pending_unresolved(session_state, _faltou)
                        if str(game.get("bo")) in {str(x) for x in BO_OPTIONS}:
                            payload["bo"] = int(game.get("bo"))
                        if isinstance(game, dict) and isinstance(game.get("lines_saved"), dict):
                            payload["_flow_line_values"] = dict(game.get("lines_saved") or {})
                        set_pending_load(session_state, payload)
                        _safe_rerun()
                    except Exception:
                        pass

    locked = flow_stage in ("lines", "results")
    ensure_matchup_selection_state(session_state)
    team_opts = ["", *list(teams)]
    if str(session_state.get("teamA", "") or "") not in team_opts:
        session_state["teamA"] = ""
    if str(session_state.get("teamB", "") or "") not in team_opts:
        session_state["teamB"] = ""
    if str(session_state.get("bo", "1") or "1") not in {str(x) for x in BO_OPTIONS}:
        session_state["bo"] = int(BO_OPTIONS[0])

    # TIME DA AGENDA QUE NAO CASOU COM O CSV (15/09/2026, relatado por ele).
    # Antes o campo simplesmente ficava vazio e ninguem dizia nada — parecia
    # que o botao "Usar este jogo" nao tinha funcionado. Agora diz QUAL time
    # falhou, ja traz o palpite, e deixa ensinar ali mesmo: o apelido fica
    # salvo e o problema nao volta.
    _nao_casou = session_state.get(_CHAVE_NAO_RESOLVIDOS) or []
    if _nao_casou:
        from pathlib import Path as _Path

        from app_core.schedule_import_core import (
            load_schedule_aliases as _carregar_apelidos,
            normalize_schedule_team_key as _chave_apelido,
            save_schedule_aliases as _salvar_apelidos,
            suggest_schedule_teams as _sugerir,
        )
        _arq_apelidos = _Path(__file__).resolve().parents[1] / "user_team_aliases.json"
        for _rot, _cru in _nao_casou:
            st.warning("**{}** ficou vazio: a agenda tem *{}*, que nao existe "
                       "com esse nome no CSV.".format(_rot, _cru))
            _sug = _sugerir(_cru, list(teams))
            _pick = st.selectbox(
                "Esse time e qual? (fica salvo)", options=["", *_sug],
                key="agenda_fix_{}".format(_chave_apelido(_cru)),
            )
            if _pick and st.button("Salvar e usar",
                                   key="agenda_fix_btn_{}".format(_chave_apelido(_cru))):
                _ap = _carregar_apelidos(session_state, _arq_apelidos)
                _ap[_chave_apelido(_cru)] = str(_pick)
                _salvar_apelidos(session_state, _arq_apelidos, _ap)
                session_state["teamA" if _rot == "Time 1" else "teamB"] = str(_pick)
                session_state[_CHAVE_NAO_RESOLVIDOS] = [
                    x for x in _nao_casou if x[0] != _rot]
                _safe_rerun()

    def _fmt_team_placeholder(x: str) -> str:
        return "" if str(x) == "" else str(x)

    cA, cB, cC, cD = st.columns([3, 3, 1, 3])
    with cA:
        team_a = st.selectbox("Time 1", options=team_opts, key="teamA", disabled=locked, format_func=_fmt_team_placeholder)
    with cB:
        team_b = st.selectbox("Time 2", options=team_opts, key="teamB", disabled=locked, format_func=_fmt_team_placeholder)
    with cC:
        bo = st.selectbox("BO", list(BO_OPTIONS), key="bo", disabled=locked)
    with cD:
        if flow_stage == "select":
            st.write("Ação")
            can_analyze = bool(team_a) and bool(team_b) and (str(team_a) != str(team_b))
            pending_auto = consume_pending_auto_analyze(session_state) if can_analyze else {}
            if can_analyze and pending_auto:
                lines_payload = pending_auto.get("lines") if isinstance(pending_auto, dict) else None
                if isinstance(lines_payload, dict):
                    key = matchup_key_fn(season_label, team_a, team_b)
                    set_matchup_key(session_state, key)
                    apply_flow_line_values(session_state, lines_payload, fields=tuple(get_schedule_line_fields()))
                    save_lines_for_matchup_fn(key)
                    set_flow_stage(session_state, "results")
                    request_analysis_refresh(session_state)
                    _safe_rerun()

            if st.button("Analisar Confronto", type="primary", width="stretch", disabled=not can_analyze, key="btn_go_lines_quick"):
                key = matchup_key_fn(season_label, team_a, team_b)
                set_matchup_key(session_state, key)
                load_lines_for_matchup_fn(key)
                set_lines_loaded_key(session_state, key)
                # Skip the legacy "lines" stage — users now input lines inside
                # the per-market sub-tabs (Análise de Linha v3). Go straight
                # to results so the tabs render immediately.
                set_flow_stage(session_state, "results")
                request_analysis_refresh(session_state)
                _safe_rerun()
        elif flow_stage == "lines":
            if st.button("Trocar confronto", width="stretch"):
                request_pending_reset_matchup(session_state)
                _safe_rerun()
        else:
            if st.button("Trocar confronto", width="stretch", key="btn_swap_matchup_results"):
                request_pending_reset_matchup(session_state)
                _safe_rerun()

    return str(team_a or ""), str(team_b or ""), int(bo)


def team_with_league_label(name: str, league: str) -> str:
    """Format team name with optional league suffix: 'TeamName (LCK)'."""
    team = str(name or "").strip()
    lg = str(league or "").strip()
    return f"{team} ({lg})" if lg else team


def canon_team_key(name: str) -> str:
    """Casefolded, whitespace-normalized team key for deduplication and comparison."""
    s = ("" if name is None else str(name)).strip()
    s = re.sub(r"\s+", " ", s)
    return s.casefold()


def norm_team_token(s: Any) -> str:
    """Normalize a team name token to lowercase alphanumeric words for fuzzy matching."""
    t = str(s or "").strip().lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def team_match_score(name: str, patterns: List[str]) -> int:
    """Score a team name against search patterns: 100=exact, 70=substring, 0=no match."""
    nm = norm_team_token(name)
    score = 0
    for p in patterns:
        pp = norm_team_token(p)
        if not pp:
            continue
        if nm == pp:
            score = max(score, 100)
        elif pp in nm:
            score = max(score, 70)
    return score


def pick_team_name(candidates: List[str], patterns: List[str]) -> Optional[str]:
    """Return the best-matching team name from candidates using pattern scoring, or None."""
    best_name = None
    best_score = -1
    for c in candidates:
        sc = team_match_score(c, patterns)
        if sc > best_score:
            best_score = sc
            best_name = c
    return best_name if best_score >= 60 else None


def team_canon_maps(csv_sig: Tuple[str, int, int]) -> Dict[str, Any]:
    """Build team name canonicalization maps from CSV (deduplication by frequency).

    Returns:
      - variant_to_best_key: canon_key -> best_display_name
      - best_to_variants: best_display_name -> [variants...]
      - best_list: [best_display_name...]
    """
    from mlcore.stats_teams import load_team_rows

    csv_path, _size, _mtime = csv_sig
    rows = load_team_rows(csv_path)
    s = rows.get("teamname")
    if s is None:
        return {"variant_to_best_key": {}, "best_to_variants": {}, "best_list": []}

    names = s.dropna().astype(str).map(lambda x: re.sub(r"\s+", " ", x.strip()))
    if names.empty:
        return {"variant_to_best_key": {}, "best_to_variants": {}, "best_list": []}

    vc = names.value_counts()
    key_to_variants: Dict[str, List[str]] = {}
    for v in vc.index.tolist():
        k = canon_team_key(v)
        key_to_variants.setdefault(k, []).append(v)

    key_to_best: Dict[str, str] = {}
    best_to_variants: Dict[str, List[str]] = {}
    for k, variants in key_to_variants.items():
        best = max(variants, key=lambda v: int(vc.get(v, 0)))
        key_to_best[k] = best
        best_to_variants[best] = sorted(list(set(variants)))

    best_list = sorted(list(best_to_variants.keys()))
    return {"variant_to_best_key": key_to_best, "best_to_variants": best_to_variants, "best_list": best_list}
