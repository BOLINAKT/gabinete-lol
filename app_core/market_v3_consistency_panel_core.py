"""V3 consistency panel — copy of `render_market_context_panel` adapted for the
new Kills (and future markets) sub-tab inside Análise de Linha.

What differs from the Consistência version (the screenshot reference):
  - Pre-computes per-opponent baselines (mean of metric across the league)
    so each recent / H2H game line gets a contextual tag:
        🔥 over vs adv. historicamente under
        ❄️ under vs adv. historicamente over
        📈 over forte (Δ > 3.0 vs linha)
        📉 under forte (Δ < -3.0 vs linha)
        neutral → no tag (avoids visual noise)
  - Hover tooltips via native HTML title= attribute
  - Cleaner card aesthetics (subtle borders, cyan accent banner header)
  - Removes nested expanders / dividers between sections

The Consistência tab continues to use the original `render_market_context_panel`
unchanged — this module is a parallel copy so v3 evolution doesn't risk that.
"""
from __future__ import annotations

import math
from html import escape
from typing import Any, Callable, Dict, List, Mapping, Optional

import pandas as pd

from app_core.consistency_core import (
    build_overall_tables,
    fmt_metric_value,
    h2h_numeric_series,
    team_metric_stats,
)


_TAG_STYLES: Dict[str, Dict[str, str]] = {
    "over_vs_under": {
        "emoji": "🔥",
        "color": "#22c55e",
        "bg": "rgba(34,197,94,0.18)",
        "label": "over vs adv. under",
    },
    "under_vs_over": {
        "emoji": "❄️",
        "color": "#3b82f6",
        "bg": "rgba(59,130,246,0.16)",
        "label": "under vs adv. over",
    },
    "over_strong": {
        "emoji": "📈",
        "color": "#22c55e",
        "bg": "rgba(34,197,94,0.13)",
        "label": "over forte",
    },
    "under_strong": {
        "emoji": "📉",
        "color": "#ef4444",
        "bg": "rgba(239,68,68,0.13)",
        "label": "under forte",
    },
}


def _classify_game_signal(
    *,
    value: float,
    line: Optional[float],
    opponent: str,
    opp_baseline: float,
    league_avg: float,
) -> Optional[Dict[str, str]]:
    """Return {'kind', 'emoji', 'color', 'bg', 'label', 'tooltip'} or None if neutral."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    L = None
    if line is not None:
        try:
            L = float(line)
        except (TypeError, ValueError):
            L = None
    if L is not None and not math.isfinite(L):
        L = None

    # Opponent strength relative to league
    opp_strength: str = "neutral"
    if math.isfinite(opp_baseline) and math.isfinite(league_avg) and league_avg > 0:
        diff_pct = (opp_baseline - league_avg) / league_avg
        if diff_pct <= -0.15:
            opp_strength = "very_under"
        elif diff_pct <= -0.05:
            opp_strength = "under"
        elif diff_pct < 0.05:
            opp_strength = "avg"
        elif diff_pct < 0.15:
            opp_strength = "over"
        else:
            opp_strength = "very_over"

    if L is None:
        # No line given — only tag based on opponent context vs game value
        # If big game (way above league) and opp is under → still meaningful
        if opp_strength in ("very_under", "under") and math.isfinite(league_avg) and v > league_avg * 1.15:
            kind = "over_vs_under"
            style = _TAG_STYLES[kind]
            return {
                **style, "kind": kind,
                "tooltip": (f"Bateu acima da média da liga (méd {league_avg:.1f}) "
                            f"contra {opponent} historicamente {opp_strength.replace('_', ' ')} "
                            f"(baseline {opp_baseline:.1f}). Sinal forte."),
            }
        if opp_strength in ("very_over", "over") and math.isfinite(league_avg) and v < league_avg * 0.85:
            kind = "under_vs_over"
            style = _TAG_STYLES[kind]
            return {
                **style, "kind": kind,
                "tooltip": (f"Ficou abaixo da média da liga (méd {league_avg:.1f}) "
                            f"contra {opponent} historicamente {opp_strength.replace('_', ' ')} "
                            f"(baseline {opp_baseline:.1f}). Sinal forte."),
            }
        return None

    delta = v - L
    is_over = v > L

    # Strongest signals: hit against opposite-leaning opponent
    if is_over and opp_strength in ("very_under", "under"):
        kind = "over_vs_under"
        style = _TAG_STYLES[kind]
        return {
            **style, "kind": kind,
            "tooltip": (f"Foi Over (+{delta:.1f} vs linha {L:g}) contra {opponent} "
                        f"historicamente {opp_strength.replace('_', ' ')} "
                        f"(baseline {opp_baseline:.1f}). Sinal forte."),
        }
    if (not is_over) and opp_strength in ("very_over", "over"):
        kind = "under_vs_over"
        style = _TAG_STYLES[kind]
        return {
            **style, "kind": kind,
            "tooltip": (f"Foi Under ({delta:+.1f} vs linha {L:g}) contra {opponent} "
                        f"historicamente {opp_strength.replace('_', ' ')} "
                        f"(baseline {opp_baseline:.1f}). Sinal forte."),
        }

    # Strong magnitude even vs neutral opponent
    if is_over and delta > 3.0:
        kind = "over_strong"
        style = _TAG_STYLES[kind]
        return {
            **style, "kind": kind,
            "tooltip": f"Over {delta:+.1f} além da linha {L:g}.",
        }
    if (not is_over) and delta < -3.0:
        kind = "under_strong"
        style = _TAG_STYLES[kind]
        return {
            **style, "kind": kind,
            "tooltip": f"Under {delta:+.1f} aquém da linha {L:g}.",
        }
    return None


def _tag_html(tag: Mapping[str, str]) -> str:
    """Render a tag as inline HTML (with hover tooltip via title=)."""
    color = str(tag.get("color", "#9ca3af"))
    bg = str(tag.get("bg", "rgba(156,163,175,0.10)"))
    label = str(tag.get("label", ""))
    emoji = str(tag.get("emoji", ""))
    tip = str(tag.get("tooltip", ""))
    return (
        f"<span title='{escape(tip)}' "
        f"style='display:inline-block;padding:2px 8px;margin-left:8px;"
        f"border-radius:10px;background:{bg};color:{color};"
        f"font-size:0.78em;font-weight:600;letter-spacing:0.02em;cursor:help;'>"
        f"{escape(emoji)} {escape(label)}</span>"
    )


def _build_opp_baselines(
    league_scope_df: pd.DataFrame, col_name: str
) -> tuple[Dict[str, float], float]:
    """Return ({opponent_name: mean_value}, league_avg)."""
    if league_scope_df is None or league_scope_df.empty or "team" not in league_scope_df.columns:
        return {}, float("nan")
    opp_means: Dict[str, float] = {}
    for team_name, grp in league_scope_df.groupby("team"):
        s = pd.to_numeric(grp.get(col_name), errors="coerce").dropna() if col_name in grp.columns else pd.Series(dtype=float)
        if len(s) > 0:
            opp_means[str(team_name)] = float(s.mean())
    league_vals = pd.to_numeric(league_scope_df.get(col_name), errors="coerce").dropna() if col_name in league_scope_df.columns else pd.Series(dtype=float)
    league_avg = float(league_vals.mean()) if len(league_vals) > 0 else float("nan")
    return opp_means, league_avg


def _render_game_lines_with_tags(
    *,
    st: Any,
    df_recent: pd.DataFrame,
    col_name: str,
    metric_formatter: Callable[[str, Any, int], str],
    opp_baselines: Mapping[str, float],
    league_avg: float,
    line: Optional[float],
    n: int = 10,
) -> None:
    """Render a recent-games list with optional contextual tag per row."""
    if df_recent is None or df_recent.empty or str(col_name) not in df_recent.columns:
        st.markdown("<div style='opacity:0.55;'>— sem jogos —</div>", unsafe_allow_html=True)
        return
    # Take the most recent N and display newest first
    d = df_recent.sort_values("date").tail(int(n)).iloc[::-1]
    rows_html: List[str] = []
    for _, row in d.iterrows():
        opp = str(row.get("opponent", "") or "-")
        v = pd.to_numeric(pd.Series([row.get(col_name)]), errors="coerce").iloc[0]
        v_str = metric_formatter(str(col_name), v, 0)
        # Build tag
        tag = _classify_game_signal(
            value=v, line=line, opponent=opp,
            opp_baseline=opp_baselines.get(opp, float("nan")),
            league_avg=league_avg,
        )
        tag_html = _tag_html(tag) if tag else ""
        rows_html.append(
            f"<div style='padding:3px 0;'>"
            f"<span style='opacity:0.85;'>{escape(opp)}</span>"
            f"<span style='margin:0 6px;opacity:0.4;'>·</span>"
            f"<span style='font-weight:600;'>{escape(str(v_str))}</span>"
            f"{tag_html}"
            f"</div>"
        )
    st.markdown("\n".join(rows_html), unsafe_allow_html=True)


def _render_h2h_lines_with_tags(
    *,
    st: Any,
    df_h2h: pd.DataFrame,
    col_name: str,
    team_a: str,
    metric_formatter: Callable[[str, Any, int], str],
    opp_baselines: Mapping[str, float],
    league_avg: float,
    line: Optional[float],
    n: int = 10,
) -> None:
    """Render H2H games (vs the same opponent across years if available)."""
    if df_h2h is None or df_h2h.empty or str(col_name) not in df_h2h.columns:
        st.markdown("<div style='opacity:0.55;'>— sem H2H —</div>", unsafe_allow_html=True)
        return
    # Newest H2H first
    d = df_h2h.sort_values("date").tail(int(n)).iloc[::-1]
    rows_html: List[str] = []
    for _, row in d.iterrows():
        opp = str(row.get("opponent", "") or "-")
        v = pd.to_numeric(pd.Series([row.get(col_name)]), errors="coerce").iloc[0]
        date_str = str(row.get("date", "") or "")[:10]
        v_str = metric_formatter(str(col_name), v, 0)
        tag = _classify_game_signal(
            value=v, line=line, opponent=opp,
            opp_baseline=opp_baselines.get(opp, float("nan")),
            league_avg=league_avg,
        )
        tag_html = _tag_html(tag) if tag else ""
        rows_html.append(
            f"<div style='padding:3px 0;'>"
            f"<span style='font-weight:600;'>{escape(str(v_str))}</span>"
            f"<span style='margin:0 6px;opacity:0.4;'>·</span>"
            f"<span style='opacity:0.6;font-size:0.88em;'>{escape(date_str)}</span>"
            f"{tag_html}"
            f"</div>"
        )
    st.markdown("\n".join(rows_html), unsafe_allow_html=True)


def _card_header_html(title: str) -> str:
    """Cyan banner header for each card (matches reference screenshot)."""
    return (
        "<div style='background:linear-gradient(180deg, #2daac4 0%, #1f8ba1 100%);"
        "padding:8px 12px;border-radius:8px 8px 0 0;text-align:center;"
        "font-weight:700;letter-spacing:0.05em;font-size:0.92em;color:white;"
        "box-shadow:inset 0 1px 0 rgba(255,255,255,0.18);'>"
        f"{escape(title)}</div>"
    )


def render_v3_market_context_panel(
    st: Any,
    *,
    panel_title: str,
    col_name: str,
    team_a: str,
    team_b: str,
    df_a_context_all: pd.DataFrame,
    df_b_context_all: pd.DataFrame,
    df_a_context_season: pd.DataFrame,
    df_b_context_season: pd.DataFrame,
    df_h2h_year: pd.DataFrame,
    df_h2h_context_year_full_a: Optional[pd.DataFrame],
    league_scope_df: pd.DataFrame,
    line: Optional[float],
    min_to_mmss_fn: Callable[[float], str],
    num_formatter: Callable[[Any, int], str],
) -> None:
    """Render the OVERALL / RECENT FORM / PAST FACEOFFS 3-card panel (v3)."""

    def metric(col: str, value: Any, decimals: int = 1) -> str:
        return fmt_metric_value(col, value, decimals, time_formatter=min_to_mmss_fn)

    # Pre-compute opp baselines once (used by both recent and h2h lines)
    opp_baselines, league_avg = _build_opp_baselines(league_scope_df, col_name)

    s_a_cur = team_metric_stats(df_a_context_all, col_name)
    s_b_cur = team_metric_stats(df_b_context_all, col_name)
    s_a_all = team_metric_stats(df_a_context_season, col_name)
    s_b_all = team_metric_stats(df_b_context_season, col_name)
    df_cur, df_all = build_overall_tables(
        team_a, team_b, col_name,
        s_a_cur, s_b_cur, s_a_all, s_b_all,
        num_formatter=num_formatter, metric_formatter=metric,
    )

    c_over, c_recent, c_h2h = st.columns(3)

    # ============================ OVERALL ============================
    with c_over:
        st.markdown(_card_header_html("OVERALL"), unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;"
                f"font-weight:600;font-size:1.0em;margin-bottom:6px;'>"
                f"<span style='color:#2daac4;'>{escape(team_a)}</span>"
                f"<span style='color:#2daac4;'>{escape(team_b)}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "<div style='opacity:0.6;font-size:0.82em;font-style:italic;"
                "margin:6px 0 2px 0;'>Split atual</div>",
                unsafe_allow_html=True,
            )
            st.dataframe(df_cur, width="stretch", hide_index=True)
            st.markdown(
                "<div style='opacity:0.6;font-size:0.82em;font-style:italic;"
                "margin:8px 0 2px 0;'>Season inteira</div>",
                unsafe_allow_html=True,
            )
            st.dataframe(df_all, width="stretch", hide_index=True)

    # =========================== RECENT FORM ===========================
    with c_recent:
        st.markdown(_card_header_html("RECENT FORM"), unsafe_allow_html=True)
        with st.container(border=True):
            a5 = team_metric_stats(df_a_context_all.tail(5), col_name)
            b5 = team_metric_stats(df_b_context_all.tail(5), col_name)
            a10 = team_metric_stats(df_a_context_all.tail(10), col_name)
            b10 = team_metric_stats(df_b_context_all.tail(10), col_name)
            # Header per team
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;"
                f"font-weight:600;color:#2daac4;font-size:1.0em;margin-bottom:8px;'>"
                f"<span>{escape(team_a)}</span><span>{escape(team_b)}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
            # Last-5 and Last-10 summary line
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;font-size:0.85em;"
                f"opacity:0.85;padding-bottom:6px;border-bottom:1px solid rgba(255,255,255,0.08);'>"
                f"<div>Last 5: <b>{metric(col_name, a5['avg'])}</b>"
                f" · Last 10: <b>{metric(col_name, a10['avg'])}</b></div>"
                f"<div>Last 5: <b>{metric(col_name, b5['avg'])}</b>"
                f" · Last 10: <b>{metric(col_name, b10['avg'])}</b></div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            # Two-column rows of recent games
            rc_a, rc_b = st.columns(2)
            with rc_a:
                _render_game_lines_with_tags(
                    st=st, df_recent=df_a_context_all,
                    col_name=col_name, metric_formatter=metric,
                    opp_baselines=opp_baselines, league_avg=league_avg,
                    line=line, n=10,
                )
            with rc_b:
                _render_game_lines_with_tags(
                    st=st, df_recent=df_b_context_all,
                    col_name=col_name, metric_formatter=metric,
                    opp_baselines=opp_baselines, league_avg=league_avg,
                    line=line, n=10,
                )

    # =========================== PAST FACEOFFS =========================
    with c_h2h:
        st.markdown(_card_header_html("PAST FACEOFFS"), unsafe_allow_html=True)
        with st.container(border=True):
            h2h_series = h2h_numeric_series(df_h2h_year, col_name)
            st.markdown(
                f"<div style='font-weight:600;color:#2daac4;font-size:1.0em;margin-bottom:8px;'>"
                f"{escape(team_a)} vs {escape(team_b)}</div>",
                unsafe_allow_html=True,
            )
            n_h2h = int(h2h_series.shape[0]) if h2h_series is not None else 0
            avg_h2h = (h2h_series.mean() if (h2h_series is not None and n_h2h > 0)
                       else float("nan"))
            st.markdown(
                f"<div style='display:flex;gap:14px;padding-bottom:8px;"
                f"border-bottom:1px solid rgba(255,255,255,0.08);'>"
                f"<div><div style='opacity:0.6;font-size:0.78em;text-transform:uppercase;'>H2H Games</div>"
                f"<div style='font-size:1.4em;font-weight:700;color:#2daac4;'>{n_h2h}</div></div>"
                f"<div><div style='opacity:0.6;font-size:0.78em;text-transform:uppercase;'>"
                f"{'Avg (combined)' if str(col_name).startswith('total_') else f'Avg ({escape(team_a)})'}"
                f"</div>"
                f"<div style='font-size:1.4em;font-weight:700;'>{escape(str(metric(col_name, avg_h2h)))}</div></div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if (df_h2h_context_year_full_a is not None
                    and not df_h2h_context_year_full_a.empty
                    and col_name in df_h2h_context_year_full_a.columns):
                _render_h2h_lines_with_tags(
                    st=st, df_h2h=df_h2h_context_year_full_a,
                    col_name=col_name, team_a=team_a, metric_formatter=metric,
                    opp_baselines=opp_baselines, league_avg=league_avg,
                    line=line, n=10,
                )
            else:
                st.markdown("<div style='opacity:0.55;'>— sem H2H —</div>", unsafe_allow_html=True)


__all__ = ["render_v3_market_context_panel"]
