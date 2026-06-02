"""Market configuration for championship stats views."""
from __future__ import annotations

STATS_MARKET_CONFIG: dict[str, dict[str, str]] = {
    "Kills": {
        "metric_key": "kills",
        "combined_col": "total_kills",
        "threshold_key": "sc_th_kills",
        "default_thresholds": "23.5,25.5,27.5,29.5",
        "pct_prefix": "% Kills > ",
    },
    "Torres": {
        "metric_key": "towers",
        "combined_col": "total_towers",
        "threshold_key": "sc_th_towers",
        "default_thresholds": "10.5,11.5,12.5",
        "pct_prefix": "% Towers > ",
    },
    "Dragões": {
        "metric_key": "dragons",
        "combined_col": "total_dragons",
        "threshold_key": "sc_th_dragons",
        "default_thresholds": "4.5,5.5",
        "pct_prefix": "% Dragons > ",
    },
    "Nashors": {
        "metric_key": "barons",
        "combined_col": "total_nashors",
        "threshold_key": "sc_th_barons",
        "default_thresholds": "1.5",
        "pct_prefix": "% Nashors > ",
    },
    "Inibidores": {
        "metric_key": "inhibitors",
        "combined_col": "total_inhibitors",
        "threshold_key": "sc_th_inhib",
        "default_thresholds": "1.5",
        "pct_prefix": "% Inhib > ",
    },
    "Tempo": {
        "metric_key": "time",
        "combined_col": "game_time_min",
        "threshold_key": "sc_th_time",
        "default_thresholds": "",
        "pct_prefix": "% Game Time > ",
    },
}
