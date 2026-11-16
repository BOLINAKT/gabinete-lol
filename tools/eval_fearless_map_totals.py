# -*- coding: utf-8 -*-
"""Estudo (gate do sinal fearless do Radar): em séries FEARLESS, o número do
mapa desloca os totais (kills/torres/dragões/tempo)?

Hipótese do usuário (2026-07-04): conforme os campeões vão saindo do pool,
os drafts dos mapas 2/3+ tomam um rumo (underkill/undertorre ou o contrário).

Método:
- Série = (data, par de times ordenado). Fearless detectada NOS DADOS: nenhum
  campeão repete entre mapas da mesma série (série com 2+ mapas).
- Compara média e taxa de Over (linhas padrão) por número do mapa, dentro das
  séries fearless; z de duas proporções mapa 1 vs mapas 3+.
- Regra da casa: se não confirmar, o sinal verbalizado NÃO nasce no Radar.

Uso: python tools/eval_fearless_map_totals.py [--year 2026]
"""
from __future__ import annotations

import argparse
import math
import sys

# Console cp1252 no Windows derruba qualquer print com acento/emoji — e o estouro
# vem no fim, depois do trabalho todo feito. Ver tools/find_silent_failures.py.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app_core.players_data_core import load_player_rows  # noqa: E402
from mlcore.stats_teams import build_team_games, load_team_rows  # noqa: E402

LINES = {"mv2_total_kills": 27.5, "mv2_total_towers": 11.5,
         "mv2_total_dragons": 4.5, "game_time_min": 32.5}
LABELS = {"mv2_total_kills": "Kills", "mv2_total_towers": "Torres",
          "mv2_total_dragons": "Dragoes", "game_time_min": "Tempo"}


def find_csvs(year: int) -> list[Path]:
    out = []
    for folder in (ROOT / "CSV_DIARIO", ROOT / "CSV_HISTORICO"):
        out.extend(folder.glob(f"{year}_*OraclesElixir*.csv"))
    return sorted(out)


def two_prop_z(h1: int, n1: int, h2: int, n2: int) -> float:
    if min(n1, n2) == 0:
        return float("nan")
    p1, p2 = h1 / n1, h2 / n2
    p = (h1 + h2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    return (p1 - p2) / se if se > 1e-12 else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--all-series", action="store_true",
                    help="controle: usa TODAS as series 2+ mapas (ignora deteccao fearless)")
    args = ap.parse_args()

    csvs = find_csvs(args.year)
    if not csvs:
        print(f"sem CSV para {args.year}")
        return
    csv = csvs[0]
    print(f"CSV: {csv.name}")

    pdf = load_player_rows(csv_path=str(csv))
    tg = build_team_games(load_team_rows(str(csv)))
    tg["game_time_min"] = pd.to_numeric(tg["gamelength"], errors="coerce") / 60.0
    for col, f, a in (("mv2_total_kills", "kills_for", "kills_against"),
                      ("mv2_total_towers", "towers_for", "towers_against"),
                      ("mv2_total_dragons", "dragons_for", "dragons_against")):
        tg[col] = pd.to_numeric(tg[f], errors="coerce") + pd.to_numeric(tg[a], errors="coerce")

    # ---- detectar séries fearless nos picks ----
    picks = pdf[["gameid", "date", "game", "teamname", "champion"]].dropna(subset=["gameid", "champion"]).copy()
    picks["day"] = pd.to_datetime(picks["date"], errors="coerce").dt.date.astype(str)
    game_team = picks.groupby("gameid").agg(
        day=("day", "first"), map_no=("game", "first"),
        teams=("teamname", lambda s: tuple(sorted(set(map(str, s))))),
        champs=("champion", lambda s: frozenset(map(str, s))),
    ).reset_index()
    game_team["series_key"] = game_team["day"] + "|" + game_team["teams"].astype(str)

    fearless_games: set[str] = set()
    n_series = n_fearless = 0
    for _, grp in game_team.groupby("series_key"):
        if len(grp) < 2:
            continue
        n_series += 1
        all_champs: list[frozenset] = list(grp["champs"])
        union = set().union(*all_champs)
        is_fearless = len(union) == sum(len(c) for c in all_champs)
        if is_fearless:
            n_fearless += 1
        if is_fearless or args.all_series:
            fearless_games.update(grp["gameid"].astype(str))
    print(f"series 2+ mapas: {n_series} | fearless (sem repeticao): {n_fearless} "
          f"({100.0 * n_fearless / max(1, n_series):.0f}%) | mapas fearless: {len(fearless_games)}")

    # dedup team_games (2 linhas por jogo) -> 1 por gameid
    g = tg.drop_duplicates(subset=["gameid"]).copy()
    g = g[g["gameid"].astype(str).isin(fearless_games)]
    g["map_no"] = pd.to_numeric(g["map_number"], errors="coerce")

    print(f"\n{'mercado':10s} {'mapa':>5s} {'n':>5s} {'media':>7s} {'over%':>7s}   (linha)")
    results = {}
    for col, line in LINES.items():
        s_all = {}
        for m in (1, 2, 3):
            sub = g[g["map_no"] == m] if m < 3 else g[g["map_no"] >= 3]
            v = pd.to_numeric(sub[col], errors="coerce").dropna()
            n = len(v)
            over = int((v > line).sum())
            s_all[m] = (over, n, v.mean() if n else float("nan"))
            tag = f"{m}" if m < 3 else "3+"
            print(f"{LABELS[col]:10s} {tag:>5s} {n:>5d} {s_all[m][2]:>7.2f} "
                  f"{100.0 * over / n if n else float('nan'):>6.1f}%   ({line})")
        z12 = two_prop_z(s_all[1][0], s_all[1][1], s_all[2][0], s_all[2][1])
        z13 = two_prop_z(s_all[1][0], s_all[1][1], s_all[3][0], s_all[3][1])
        results[col] = (z12, z13)
        print(f"{'':10s} mapa1 vs 2: z(over) {z12:+.2f}"
              f" {'<-- SIGNIFICATIVO' if abs(z12) >= 2.0 else ''}"
              f" | mapa1 vs 3+: z(over) {z13:+.2f}"
              f" {'<-- SIGNIFICATIVO' if abs(z13) >= 2.0 else ''}")
        print()

    sig = [LABELS[c] for c, zz in results.items() if max(abs(z) for z in zz if math.isfinite(z)) >= 2.0]
    print("VEREDITO:", ("ACCEPT p/ sinal verbalizado em: " + ", ".join(sig)) if sig
          else "REJECT — numero do mapa nao desloca totais de forma significativa (sinal nao nasce)")


if __name__ == "__main__":
    main()
