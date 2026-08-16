# -*- coding: utf-8 -*-
"""MEDIÇÃO: qual w_lineup seria ÓTIMO na season inteira? (pedido dele 24/07)

Contexto: a camada de players está DESLIGADA na prática — o fit do holdout
(1283 jogos) escolhe w negativo (-0.115) e o train_offline clipa em 0. Resultado:
Elo-core == Fusão (9.15 == 9.15), e 5127 jogadores catalogados com 100% de
cobertura não mudam nenhuma previsão.

Pergunta: isso é sinal REAL (o core já absorveu os players) ou artefato do
holdout curto? Aqui varremos w em grade e medimos logloss na SEASON INTEIRA
(mesma prova do scorecard oficial), separando inter-liga e mesma-liga.

Leitura do resultado:
  ótimo em 0        -> players são mesmo redundantes; a camada pode ser aposentada.
  ótimo POSITIVO    -> o fit do holdout está subestimando; ligar rende nota.
  ótimo NEGATIVO    -> sinal invertido em algum ponto da cadeia = BUG.

Uso: python tools/medir_w_lineup_grid.py
"""
from __future__ import annotations

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

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mlcore.artifact import MLArtifact  # noqa: E402
from mlcore.players_layer import (  # noqa: E402
    PlayersArtifact,
    compute_delta_and_confidence,
    load_match_player_rows,
    lineup_for_game,
)
from mlcore.io_oracle import load_oracle_elixir_games  # noqa: E402
from mlcore.tiers import tier_for_league  # noqa: E402
from tools.ml_quality_scorecard import default_csvs  # noqa: E402

GRID = [-0.40, -0.20, -0.10, -0.05, 0.0, 0.05, 0.10, 0.20, 0.40, 0.80]


def _logit(p: float) -> float:
    p = min(max(float(p), 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def _sig(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-35.0, min(35.0, z))))


def _ll(ps: list[float], ys: list[int]) -> float:
    tot = 0.0
    for p, y in zip(ps, ys):
        p = min(max(p, 1e-9), 1 - 1e-9)
        tot += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return tot / max(1, len(ps))


def main() -> int:
    csvs = [str(c) for c in default_csvs()]
    art = MLArtifact.load_json(str(ROOT / "ml_artifact.json"))
    p_art = PlayersArtifact.load_json(str(ROOT / "players_artifact.json"))
    model = art.model

    frames = []
    for c in csvs:
        try:
            df = load_oracle_elixir_games(c, keep_playoffs=None)
            if not df.empty:
                frames.append(df)
        except Exception as e:
            print(f"skip {c}: {e}")
    games = pd.concat(frames, ignore_index=True, join="inner")
    games["date"] = pd.to_datetime(games["date"], errors="coerce")
    games = games.dropna(subset=["date"]).drop_duplicates(subset=["gameid"], keep="last")
    season = int(pd.to_numeric(games["year"], errors="coerce").max())
    g = games[pd.to_numeric(games["year"], errors="coerce") == season].copy()
    print(f"season {season}: {len(g)} jogos-linha")

    player_rows = load_match_player_rows(csvs, keep_playoffs=None)

    base_logit: list[float] = []
    deltas: list[float] = []
    ys: list[int] = []
    inter: list[bool] = []
    n_delta_nz = 0

    for r in g.itertuples(index=False):
        try:
            y = int(r.blue_win)
        except (TypeError, ValueError):
            continue
        blue, red = str(r.blue), str(r.red)
        lg = str(getattr(r, "league", "") or "OTHER")
        bt = rt = str(tier_for_league(lg))
        p0 = float(model.p_blue(blue, red, blue_league=lg, red_league=lg,
                                blue_tier=bt, red_tier=rt))
        bl_lineup, rd_lineup = lineup_for_game(player_rows, str(r.gameid))
        res = compute_delta_and_confidence(
            p_art, blue_lineup=bl_lineup, red_lineup=rd_lineup,
            as_of=pd.to_datetime(r.date).date(), match_league=lg,
        )
        d = float(res.get("delta", 0.0) or 0.0)
        cov_tot = float(res.get("coverage_total", 5) or 5.0)
        cov = float(res.get("coverage", 0) or 0.0) / (cov_tot if cov_tot else 5.0)
        d_eff = d * cov
        if abs(d_eff) > 1e-9:
            n_delta_nz += 1
        base_logit.append(_logit(p0))
        deltas.append(d_eff)
        ys.append(y)
        inter.append(False)  # marcado abaixo se precisar separar

    print(f"amostra: {len(ys)} jogos | com delta de players != 0: {n_delta_nz} "
          f"({100.0*n_delta_nz/max(1,len(ys)):.1f}%)")
    if n_delta_nz == 0:
        print("\nATENÇÃO: nenhum jogo tem delta de players — a camada não vê lineup nenhum.")
        return 1

    print(f"\n{'w_lineup':>9} {'logloss':>9} {'vs w=0':>10}")
    base_ll = None
    rows = []
    for w in GRID:
        ps = [_sig(lb + w * d) for lb, d in zip(base_logit, deltas)]
        ll = _ll(ps, ys)
        if w == 0.0:
            base_ll = ll
        rows.append((w, ll))
    for w, ll in rows:
        dif = (base_ll - ll) if base_ll is not None else float("nan")
        mark = "  <== ÓTIMO" if ll == min(r[1] for r in rows) else ""
        print(f"{w:>9.2f} {ll:>9.5f} {dif:>+10.5f}{mark}")

    best_w, best_ll = min(rows, key=lambda t: t[1])
    print(f"\nw ótimo na season inteira: {best_w:+.2f} (logloss {best_ll:.5f})")
    print(f"ganho sobre desligado (w=0): {base_ll - best_ll:+.5f}")
    if abs(best_w) < 1e-9:
        print("VEREDITO: players redundantes — o core já absorveu o sinal.")
    elif best_w > 0:
        print("VEREDITO: LIGAR renderia — o fit do holdout está subestimando o peso.")
    else:
        print("VEREDITO: peso ótimo NEGATIVO na season inteira — investigar sinal invertido.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
