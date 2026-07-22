# -*- coding: utf-8 -*-
"""MEDIÇÃO: por quanto tempo a qualidade de um time "vale"? — OOS, sem vazamento.

Pergunta dele (22/07): "em relação a segurar a qualidade do time, o que a
internet diz sobre o tempo? ou isso é possível ser testado?"

A internet diz: janela longa como base (a própria Riot usa 2-3 anos no Global
Power Rankings) MAS com decaimento — jogo antigo pesa menos; e ~10 jogos já
carregam a maior parte do sinal (estudo do Inglês: 10 rodadas explicam 76,9% da
classificação final). Só que o valor do decaimento é empírico, e no seu modelo
ele está FIXO em 180 dias (half_life_days), nunca medido.

Este script mede. Método (o mesmo dos outros gates):
  1. Split temporal: treino antigo -> teste futuro (teste nunca vaza p/ o treino).
  2. Para cada meia-vida candidata, monta o perfil for/against de cada time
     PONDERADO POR RECÊNCIA (peso = 0.5 ** (dias_atrás / meia_vida)).
  3. Prevê os totais do teste e mede o RMSE.
  4. A meia-vida com menor erro é a memória ótima — por mercado e no geral.

Meia-vida curta = "só o que aconteceu agora importa" (esquece rápido).
Meia-vida longa = "a história toda conta" (esquece devagar).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mlcore.stats_teams import build_team_games, load_team_rows  # noqa: E402

CSVS = [
    "CSV_HISTORICO/2024_LoL_esports_match_data_from_OraclesElixir.csv",
    "CSV_HISTORICO/2025_LoL_esports_match_data_from_OraclesElixir.csv",
    "CSV_DIARIO/2026_LoL_esports_match_data_from_OraclesElixir.csv",
]
# mercado -> (col_for, col_against, col_total_real)
MERCADOS = {
    "kills": ("kills_for", "kills_against", "total_kills"),
    "torres": ("towers_for", "towers_against", "total_towers"),
    "dragoes": ("dragons_for", "dragons_against", "total_dragons"),
    "baroes": ("barons_for", "barons_against", "total_nashors"),
    "inibidores": ("inhibitors_for", "inhibitors_against", "total_inhibitors"),
}
# meia-vidas candidatas, em dias. inf = sem esquecimento (média simples).
MEIAS_VIDAS = [21.0, 45.0, 90.0, 135.0, 180.0, 270.0, 365.0, 730.0, float("inf")]
ATUAL = 180.0  # o default de hoje em lines_engine.build_profile


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _carregar() -> pd.DataFrame:
    frames = []
    for p in CSVS:
        fp = ROOT / p
        if fp.exists():
            frames.append(build_team_games(load_team_rows(str(fp))))
    tg = pd.concat(frames, ignore_index=True)
    tg["date"] = pd.to_datetime(tg["date"], errors="coerce")
    return tg.dropna(subset=["date", "team", "opponent"]).sort_values("date").reset_index(drop=True)


def _perfis(train: pd.DataFrame, cols: list[str], corte: pd.Timestamp, meia_vida: float) -> dict:
    """Média ponderada por recência de cada coluna, por time."""
    d = train.copy()
    if np.isfinite(meia_vida):
        dias = (corte - d["date"]).dt.total_seconds() / 86400.0
        d["_w"] = np.power(0.5, np.clip(dias, 0.0, None) / float(meia_vida))
    else:
        d["_w"] = 1.0
    out: dict[str, dict[str, float]] = {}
    for team, g in d.groupby("team"):
        w = _num(g["_w"]).fillna(0.0).values
        sw = float(w.sum())
        if sw <= 0:
            continue
        out[str(team)] = {
            c: float(np.nansum(_num(g[c]).values * w) / sw) for c in cols if c in g.columns
        }
    return out


def main() -> int:
    tg = _carregar()
    corte = tg["date"].quantile(0.80)
    train = tg[tg["date"] <= corte].copy()
    test = tg[tg["date"] > corte].copy()
    te = test[test["side"].astype(str).str.lower().eq("blue")]
    print(f"jogos-linha {len(tg)} | treino <= {corte.date()} ({len(train)}) | teste {len(te)} jogos\n")

    cols = sorted({c for cf, ca, _ in MERCADOS.values() for c in (cf, ca)})
    gdef = {c: float(_num(train[c]).mean()) for c in cols if c in train.columns}

    print("RMSE fora-da-amostra por MEIA-VIDA (menor = melhor):")
    print(f"{'meia-vida':>12} " + " ".join(f"{m:>10}" for m in MERCADOS) + f" {'media_norm':>11}")
    linhas = []
    for hl in MEIAS_VIDAS:
        prof = _perfis(train, cols, corte, hl)

        def val(df, tcol, col):
            return df[tcol].map(lambda t: prof.get(str(t), {}).get(col, gdef.get(col, 0.0))).astype(float)

        rmses = {}
        for mkt, (cf, ca, tot) in MERCADOS.items():
            a = 0.5 * (val(te, "team", cf) + val(te, "opponent", ca))
            b = 0.5 * (val(te, "opponent", cf) + val(te, "team", ca))
            pred = (a + b).astype(float)
            act = _num(te[tot]).astype(float)
            m = pred.notna() & act.notna()
            rmses[mkt] = float(np.sqrt(np.mean((act[m].values - pred[m].values) ** 2)))
        linhas.append((hl, rmses))
        rot = "sem esquecer" if not np.isfinite(hl) else f"{hl:.0f}d"
        print(f"{rot:>12} " + " ".join(f"{rmses[m]:10.4f}" for m in MERCADOS), end="")
        print()

    # normaliza cada mercado pelo melhor, p/ comparar em escalas diferentes
    print("\nErro RELATIVO ao melhor de cada mercado (1.000 = melhor):")
    melhores = {m: min(r[m] for _, r in linhas) for m in MERCADOS}
    ranking = []
    for hl, r in linhas:
        rel = {m: r[m] / melhores[m] for m in MERCADOS}
        media = float(np.mean(list(rel.values())))
        ranking.append((media, hl, rel))
        rot = "sem esquecer" if not np.isfinite(hl) else f"{hl:.0f}d"
        print(f"{rot:>12} " + " ".join(f"{rel[m]:10.4f}" for m in MERCADOS) + f" {media:11.4f}")

    ranking.sort()
    melhor_media, melhor_hl, _ = ranking[0]
    atual_media = next(m for m, hl, _ in ranking if hl == ATUAL)
    rot = "sem esquecer" if not np.isfinite(melhor_hl) else f"{melhor_hl:.0f} dias"
    print(f"\nMELHOR memória: {rot}  (erro relativo médio {melhor_media:.4f})")
    print(f"ATUAL do modelo: {ATUAL:.0f} dias (erro relativo médio {atual_media:.4f})")
    ganho = 100.0 * (atual_media - melhor_media) / atual_media
    print(f"Ganho potencial trocando: {ganho:+.2f}%")
    print("\nGATE: só vale trocar se o ganho for consistente (>0.5%) E o melhor")
    print("não for um extremo da grade (sinal de que a grade é curta demais).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
