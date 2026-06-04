"""Market configuration for championship stats views.

Fonte ÚNICA dos mercados de stats (kills/torres/dragões/barões/inibidores/tempo).
Adicionar/remover um desses mercados = editar SÓ este dicionário; os mapas usados
em outras partes (SC_METRIC_COL, RESUMO_DEFAULT_LINES, _MARKET_KEYS, _METRIC_COL)
são DERIVADOS daqui pelos helpers abaixo, em vez de duplicados.
"""
from __future__ import annotations

from typing import Any

STATS_MARKET_CONFIG: dict[str, dict[str, Any]] = {
    "Kills": {
        "metric_key": "kills",
        "combined_col": "total_kills",
        "threshold_key": "sc_th_kills",
        "default_thresholds": "23.5,25.5,27.5,29.5",
        "default_line": 27.5,
        "pct_prefix": "% Kills > ",
    },
    "Torres": {
        "metric_key": "towers",
        "combined_col": "total_towers",
        "threshold_key": "sc_th_towers",
        "default_thresholds": "10.5,11.5,12.5",
        "default_line": 11.5,
        "pct_prefix": "% Towers > ",
    },
    "Dragões": {
        "metric_key": "dragons",
        "combined_col": "total_dragons",
        "threshold_key": "sc_th_dragons",
        "default_thresholds": "4.5,5.5",
        "default_line": 4.5,
        "pct_prefix": "% Dragons > ",
    },
    "Nashors": {
        "metric_key": "barons",
        "combined_col": "total_nashors",
        "threshold_key": "sc_th_barons",
        "default_thresholds": "1.5",
        "default_line": 1.5,
        "pct_prefix": "% Nashors > ",
    },
    "Inibidores": {
        "metric_key": "inhibitors",
        "combined_col": "total_inhibitors",
        "threshold_key": "sc_th_inhib",
        "default_thresholds": "1.5",
        "default_line": 1.5,
        "pct_prefix": "% Inhib > ",
    },
    "Tempo": {
        "metric_key": "time",
        "combined_col": "game_time_min",
        "threshold_key": "sc_th_time",
        "default_thresholds": "",
        "default_line": 32.5,
        "pct_prefix": "% Game Time > ",
    },
}


# --- Helpers derivados (mapas que antes eram duplicados em outros módulos) ---

def combined_col_map() -> dict[str, str]:
    """{metric_key -> combined_col}. Fonte do SC_METRIC_COL do Resumo."""
    return {str(cfg["metric_key"]): str(cfg["combined_col"]) for cfg in STATS_MARKET_CONFIG.values()}


def default_lines_map() -> dict[str, list[float]]:
    """{metric_key -> [default_line]}. Fonte do RESUMO_DEFAULT_LINES."""
    return {str(cfg["metric_key"]): [float(cfg["default_line"])] for cfg in STATS_MARKET_CONFIG.values()}


def market_key_by_label() -> dict[str, str]:
    """{label -> metric_key}. Fonte do _MARKET_KEYS da Análise de Linha."""
    return {label: str(cfg["metric_key"]) for label, cfg in STATS_MARKET_CONFIG.items()}
