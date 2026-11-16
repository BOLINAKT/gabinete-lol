# -*- coding: utf-8 -*-
"""O modelo e TIMIDO por calibracao ou por falta de informacao? (frente de 16/10/2026)

A regua do vencedor mostrou o modelo mais timido que a Pinnacle (inclinacao 0,60)
e pior que ela. Antes de mexer, separar as duas causas, que pedem remedios
opostos: calibracao (conserta com calibrador) ou informacao que o mercado tem e
o modelo nao (nenhum calibrador resolve).

So mede, nao muda nada. Usa a mesma juncao da regua do vencedor.
Uso: python tools/diagnostico_timidez.py   (depois da nota honesta)
FONTES (abertas em 16/10/2026):
- Van Calster et al. 2019, "Calibration: the Achilles heel of predictive analytics",
  PMC6912996: "The calibration slope evaluates the spread of the estimated risks and
  has a target value of 1." / "A slope > 1 suggests the opposite, i.e., that risk
  estimates are too moderate."
- Reade, Singleton, Vaughan Williams 2020 (econpapers em-dp2020-03): comparacao modelo x
  casa "based on forecast encompassing regressions".
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.modelo_contra_a_casa import carregar_regua, juntar  # noqa: E402


def logit(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def logistica(X, y):
    """Regressao logistica por Newton. X ja com a coluna de 1. Devolve (beta, erro padrao)."""
    X = np.asarray(X, float); y = np.asarray(y, float)
    b = np.zeros(X.shape[1])
    for _ in range(100):
        eta = X @ b
        mu = 1 / (1 + np.exp(-eta))
        W = mu * (1 - mu)
        H = X.T @ (X * W[:, None])
        g = X.T @ (y - mu)
        passo = np.linalg.solve(H, g)
        b = b + passo
        if np.max(np.abs(passo)) < 1e-10:
            break
    cov = np.linalg.inv(H)
    return b, np.sqrt(np.diag(cov))


def ll(p, y):
    p = np.clip(np.asarray(p, float), 1e-9, 1 - 1e-9); y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def calib(nome, p, y):
    p = np.asarray(p, float); y = np.asarray(y, float)
    X = np.column_stack([np.ones(len(p)), logit(p)])
    b, se = logistica(X, y)
    lo, hi = b[1] - 1.96 * se[1], b[1] + 1.96 * se[1]
    print(f"  {nome:34s} n={len(p):5d}  inclinacao={b[1]:.3f} [{lo:.3f}, {hi:.3f}]  "
          f"intercepto={b[0]:+.3f}  logloss={ll(p, y):.4f}")
    return b


def main():
    import pandas as pd
    from tools.nota_honesta import default_csvs
    modelo, resumo = carregar_regua()
    print("regua honesta:", resumo["arquivos"], "jogos:", resumo["jogos"])

    # liga e data de cada jogo, do CSV
    ligas = {}
    for c in default_csvs():
        d = pd.read_csv(c, usecols=["gameid", "league", "date"], low_memory=False).drop_duplicates("gameid")
        for g, lg, dt in d.itertuples(index=False):
            ligas[str(g)] = (str(lg), str(dt)[:10])
    MAIORES = {"LCK", "LPL", "LEC", "LCS", "LTA N", "LTA S", "LCP", "CBLOL", "PCS", "VCS", "LJL",
               "MSI", "WLDs", "FST", "EWC"}

    print("\nA. CALIBRACAO NA REGUA HONESTA (todos os jogos fora da amostra)")
    todos = [(g, p, y) for g, (p, y) in modelo.items()]
    calib("todos", [p for _, p, _ in todos], [y for *_, y in todos])
    maior = [(p, y) for g, p, y in todos if ligas.get(g, ("?",))[0] in MAIORES]
    menor = [(p, y) for g, p, y in todos if g in ligas and ligas[g][0] not in MAIORES]
    calib("ligas grandes", *zip(*maior))
    calib("ligas menores", *zip(*menor))
    recente = [(p, y) for g, p, y in todos if ligas.get(g, ("", ""))[1] >= "2026-08-15"]
    calib("desde 15/08", *zip(*recente))

    print("\nB. AS PARTIDAS COM ODDS DA PINNACLE")
    casos = juntar()["casos"]
    pm = np.array([c["p_modelo"] for c in casos]); pc = np.array([c["p_mercado"] for c in casos])
    y = np.array([c["y"] for c in casos], float)
    calib("modelo", pm, y)
    calib("casa (sem margem)", pc, y)

    print("\nC. ENCOMPASSING: y ~ logit(casa) + logit(modelo)")
    X = np.column_stack([np.ones(len(y)), logit(pc), logit(pm)])
    b, se = logistica(X, y)
    for nome, i in (("casa", 1), ("modelo", 2)):
        z = b[i] / se[i]
        pval = math.erfc(abs(z) / math.sqrt(2))
        print(f"  coeficiente {nome:7s} = {b[i]:+.3f} (erro {se[i]:.3f})  z={z:+.2f}  p={pval:.3f}")
    # o modelo puxado so por um fator: ajuda contra a casa?
    for k in (1.0, 1.25, 1.5, 1.67, 2.0):
        pk = 1 / (1 + np.exp(-k * logit(pm)))
        print(f"  modelo esticado x{k:.2f}: logloss={ll(pk, y):.4f}   (casa {ll(pc, y):.4f})")

    print("\nD. ONDE ESTAO AS 132: ligas")
    from collections import Counter
    cont = Counter((c["liga"] or "?") for c in casos)
    print("  ", cont.most_common(15))
    gr = [c for c in casos if ligas.get(c["gameid"], ("?",))[0] in MAIORES]
    mn = [c for c in casos if c not in gr]
    for nome, sub in (("ligas grandes", gr), ("ligas menores", mn)):
        if len(sub) >= 10:
            a = np.array([c["p_modelo"] for c in sub]); b2 = np.array([c["p_mercado"] for c in sub])
            yy = np.array([c["y"] for c in sub], float)
            print(f"  {nome:14s} n={len(sub):3d}  logloss modelo={ll(a, yy):.4f}  casa={ll(b2, yy):.4f}  "
                  f"dif={ll(a, yy) - ll(b2, yy):+.4f}")


if __name__ == "__main__":
    main()
