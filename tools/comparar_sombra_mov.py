# -*- coding: utf-8 -*-
"""Compara dois artefatos no MESMO holdout, separando ORDENAR de CONFIAR.

╔══ FONTES ═══════════════════════════════════════════════════════════════════╗
║ POR QUE ESTE ARQUIVO EXISTE (08/09/2026): a bancada prequencial              ║
║ (tools/eval_whr_mov.py) diz que a margem GANHA +0.0117 em 2026 cego, e o     ║
║ treino sombra diz que ela PERDE 0.009 no holdout de 180 dias. Duas medicoes  ║
║ honestas discordando e um sinal de que elas medem coisas diferentes — nao    ║
║ de que uma esta mentindo. Este arquivo separa as duas capacidades:           ║
║                                                                             ║
║   ORDENAR (AUC / acerto): o modelo poe o vencedor na frente?                ║
║   CONFIAR (ECE / inclinacao de Platt): o 70% dele acontece 70% das vezes?    ║
║                                                                             ║
║ Logloss mistura as duas. Um modelo pode ordenar melhor E ter logloss pior    ║
║ se for confiante demais, e vice-versa. Sem separar, a discussao vira troca   ║
║ de numeros agregados que nao explicam nada.                                  ║
║                                                                             ║
║ A AUC e a metrica de ordenacao padrao e NAO se altera com recalibracao       ║
║ monotonica (Platt e monotonico), entao ela isola exatamente a parte que o    ║
║ calibrador NAO consegue consertar. Essa propriedade e o motivo de ela estar  ║
║ aqui em vez de so acerto.                                                    ║
║                                                                             ║
║ 3o EIXO, que e a hipotese em teste: FRESCOR. O holdout congela os ratings no ║
║ corte e preve N dias com eles parados. Se o ganho da margem for "acompanhar  ║
║ a forca atual mais depressa", ele evapora num holdout longo. Por isso o      ║
║ recorte por IDADE DA PREVISAO (dias desde o corte).                          ║
╚═════════════════════════════════════════════════════════════════════════════╝

Uso:
  python tools/comparar_sombra_mov.py scratchpad/sombra/base_artifact.json \
                                      scratchpad/sombra/mov_artifact.json
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mlcore.artifact import MLArtifact  # noqa: E402
from mlcore.io_oracle import load_oracle_elixir_games  # noqa: E402
from tools.ml_quality_scorecard import default_csvs  # noqa: E402


def auc(y: np.ndarray, p: np.ndarray) -> float:
    """AUC por postos (Mann-Whitney), com empates tratados por posto medio."""
    pos, neg = p[y == 1], p[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    ordem = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    postos = np.empty(len(ordem), dtype=float)
    postos[ordem] = np.arange(1, len(ordem) + 1, dtype=float)
    todos = np.concatenate([pos, neg])
    # posto medio nos empates
    for v in np.unique(todos):
        m = todos == v
        if m.sum() > 1:
            postos[m] = postos[m].mean()
    return float((postos[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2.0)
                 / (len(pos) * len(neg)))


def ece(y: np.ndarray, p: np.ndarray, n_faixas: int = 10) -> float:
    bordas = np.linspace(0.0, 1.0, n_faixas + 1)
    total = 0.0
    for i in range(n_faixas):
        m = (p >= bordas[i]) & (p < bordas[i + 1] if i < n_faixas - 1 else p <= 1.0)
        if m.sum():
            total += (m.sum() / len(p)) * abs(y[m].mean() - p[m].mean())
    return float(total)


def pontuar(art: MLArtifact, holdout: pd.DataFrame) -> dict:
    p_raw, p_cal, ys = [], [], []
    for r in holdout.itertuples(index=False):
        pr = float(art.model.p_blue(str(r.blue), str(r.red),
                                    blue_league=str(r.blue_league),
                                    red_league=str(r.red_league),
                                    blue_tier=str(r.blue_tier),
                                    red_tier=str(r.red_tier)))
        p_raw.append(min(max(pr, 1e-6), 1 - 1e-6))
        pc = float(art.calibrator.predict_proba(pr))
        p_cal.append(min(max(pc, 1e-6), 1 - 1e-6))
        ys.append(int(r.blue_win))
    y = np.asarray(ys, dtype=float)
    out = {"n": len(y)}
    for nome, arr in (("raw", np.asarray(p_raw)), ("cal", np.asarray(p_cal))):
        out[f"logloss_{nome}"] = float(-(y * np.log(arr) + (1 - y) * np.log(1 - arr)).mean())
        out[f"acc_{nome}"] = float((((arr >= 0.5).astype(float)) == y).mean())
        out[f"auc_{nome}"] = auc(y, arr)
        out[f"ece_{nome}"] = ece(y, arr)
    out["p_cal"] = np.asarray(p_cal)
    out["y"] = y
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("cand")
    ap.add_argument("--holdout-days", type=int, default=180)
    args = ap.parse_args()

    # load_oracle_elixir_games recebe UM caminho; o treino concatena os CSVs.
    g = pd.concat([load_oracle_elixir_games(str(c)) for c in default_csvs()],
                  ignore_index=True)
    g["date"] = pd.to_datetime(g["date"], errors="coerce")
    g = g.dropna(subset=["date"]).sort_values(["date", "gameid"]).reset_index(drop=True)

    # As colunas de liga/tier sao construidas no treino; refaz igual aqui.
    from mlcore.train_offline import (_augment_games_with_home_meta,
                                      _infer_team_domestic_league_by_year,
                                      _infer_team_meta_latest)
    dby = _infer_team_domestic_league_by_year(g)
    meta = _infer_team_meta_latest(dby)
    g = _augment_games_with_home_meta(g, domestic_by_year=dby, team_meta_latest=meta)

    corte = g["date"].max() - pd.Timedelta(days=int(args.holdout_days))
    hold = g[g["date"] >= corte].copy()
    print(f"holdout: {len(hold)} jogos, de {hold['date'].min().date()} "
          f"a {hold['date'].max().date()} (corte {corte.date()})\n")

    rb = pontuar(MLArtifact.load_json(args.base), hold)
    rc = pontuar(MLArtifact.load_json(args.cand), hold)

    print(f"{'metrica':<14}{'BASE':>10}{'CANDIDATO':>12}{'dif':>10}")
    for k in ("logloss_raw", "logloss_cal", "acc_raw", "acc_cal",
              "auc_raw", "auc_cal", "ece_raw", "ece_cal"):
        b, c = rb[k], rc[k]
        # logloss e ECE: menor e melhor. acc e AUC: maior e melhor.
        dif = (b - c) if k.startswith(("logloss", "ece")) else (c - b)
        print(f"{k:<14}{b:>10.4f}{c:>12.4f}{dif:>+10.4f}")

    # IC pareado na diferenca de logloss calibrado — sem isto, um ganho de
    # +0.0067 em n~1200 e um numero sem erro declarado, e a barra da casa
    # exige limite inferior acima de zero.
    llb = -(rb["y"] * np.log(rb["p_cal"]) + (1 - rb["y"]) * np.log(1 - rb["p_cal"]))
    llc = -(rc["y"] * np.log(rc["p_cal"]) + (1 - rc["y"]) * np.log(1 - rc["p_cal"]))
    d = llb - llc
    rng = np.random.default_rng(20260908)
    amostras = d[rng.integers(0, len(d), size=(4000, len(d)))].mean(axis=1)
    lo, hi = np.percentile(amostras, [2.5, 97.5])
    print(f"\nIC95% da dif de logloss calibrado: {d.mean():+.5f} "
          f"[{lo:+.5f}, {hi:+.5f}]  (n={len(d)})")
    print(f"barra da casa (>0.002 E limite inferior >0): "
          f"{'PASSA' if (d.mean() > 0.002 and lo > 0) else 'NAO PASSA'}")

    print("\nLEITURA: 'dif' positivo = candidato melhor, em TODAS as linhas.")
    print("Se AUC melhora e logloss piora, o candidato ORDENA melhor mas CONFIA errado")
    print("— e isso e conserto de calibrador, nao defeito do rating.\n")

    # ---- frescor: o ganho depende de quao velho esta o rating? ----
    idade = (hold["date"] - corte).dt.days.to_numpy()
    ll_b = -(rb["y"] * np.log(rb["p_cal"]) + (1 - rb["y"]) * np.log(1 - rb["p_cal"]))
    ll_c = -(rc["y"] * np.log(rc["p_cal"]) + (1 - rc["y"]) * np.log(1 - rc["p_cal"]))
    print("ganho do candidato por IDADE DA PREVISAO (dias desde o corte):")
    print(f"{'faixa':<12}{'n':>7}{'dif logloss':>14}")
    passo = max(int(args.holdout_days) // 6, 1)
    for ini in range(0, int(args.holdout_days) + 1, passo):
        m = (idade >= ini) & (idade < ini + passo)
        if m.sum() >= 40:
            print(f"{f'{ini}-{ini+passo}d':<12}{int(m.sum()):>7}"
                  f"{float((ll_b[m] - ll_c[m]).mean()):>+14.5f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
