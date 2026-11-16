# -*- coding: utf-8 -*-
"""Quanto vale desligar a trava de concordancia do ultimo estagio.

O ACHADO QUE TROUXE ATE AQUI (21/09/2026). Em `mlcore/fusion_core.py`, o
hybrid_momentum_blend calcula o peso que dara a forma recente assim:

    agree = media(1 - |forma - modelo| / 0.5)
    peso  = teto * fator_amostra * (0.35 + 0.65 * agree)

O peso CRESCE quando a forma concorda com o modelo e ENCOLHE quando discorda.
So que `tools/sobrou_sinal.py` mediu, fora da amostra, onde a forma ainda tem
algo a dizer depois deste estagio:

    mapa 1, forma CONCORDA com o modelo ... +0,004 [-0,004, +0,012]  nada
    mapa 1, forma DISCORDA do modelo ...... +0,037 [+0,018, +0,058]  real

Nove vezes maior exatamente onde a formula manda calar. Faz sentido: quando a
forma concorda, ela nao acrescenta; a informacao nova esta na discordancia.

POR QUE ESTA FERRAMENTA, E NAO OITO RODADAS DA REGUA
Uma dobra da regua leva 12m22s -- oito dobras, 1h40. Varrer cinco valores de
`agree_damp` daria oito horas de maquina. Mas o hybrid e o ULTIMO estagio: o
preco que entra nele nao depende deste botao. Entao a regua grava esse preco
(`antes_hybrid`) e aqui so se reaplica o estagio final.

O QUE ISTO **NAO** E: uma segunda implementacao do estagio. A funcao chamada
e a de PRODUCAO (mlcore.fusion_core.hybrid_momentum_blend), com os pesos JA
amortecidos que a propria regua calculou e gravou. Refazer a conta do
amortecimento interregional aqui criaria duas versoes dela, e elas divergem.
A nota sai de `nota_honesta.nota_de`, a mesma mistura 45/55 da nota oficial.

Uso: python tools/varrer_agree.py [arquivo_da_regua.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PADRAO = "nota_honesta_base_agree_diaria_hybrid_form_platt.json"
VALORES = (1.00, 0.75, 0.50, 0.25, 0.00)


def main() -> int:
    import math

    import pandas as pd

    from mlcore.fusion_core import hybrid_momentum_blend
    from mlcore.stats_teams import build_team_games, load_team_rows
    from tools.nota_honesta import HistoricoPorTime, default_csvs, nota_de

    alvo = ROOT / "scratchpad" / "nota_honesta" / (
        sys.argv[1] if len(sys.argv) > 1 else PADRAO)
    if not alvo.exists():
        print("[varrer] nao achei %s" % alvo)
        print("[varrer] rode antes: python tools/nota_honesta.py --marca base_agree "
              "--dobras 8 --cadencia diaria --com-hybrid --com-form")
        return 1

    d = json.loads(alvo.read_text(encoding="utf-8"))
    linhas = d.get("antes_hybrid") or []
    if not linhas:
        print("[varrer] este arquivo nao tem 'antes_hybrid' -- foi gerado por uma "
              "versao da regua anterior a 21/09/2026. Refaca a rodada.")
        return 1
    print("[varrer] %d jogos, todos fora da amostra" % len(linhas))

    csvs = [str(c) for c in default_csvs()]
    quadros = [build_team_games(load_team_rows(c)) for c in csvs]
    hist = HistoricoPorTime(pd.concat(quadros, ignore_index=True))
    print("[varrer] historico point-in-time montado")

    # Os quadros de cada time sao os mesmos para todos os valores do botao --
    # buscar uma vez so e o que faz esta varredura levar segundos.
    cache = []
    for x in linhas:
        quando = pd.Timestamp(x["date"])
        cache.append((x, hist.antes_de(x["blue"], quando), hist.antes_de(x["red"], quando)))

    print()
    print("%-12s %8s %8s %8s %10s" % ("agree_damp", "nota", "inter", "same", "vs hoje"))
    base = None
    for damp in VALORES:
        inter, same = [], []
        for x, dfa, dfb in cache:
            p = float(x["p"])
            hy = hybrid_momentum_blend(
                p_model=p, df_team_a=dfa, df_team_b=dfb, enabled=True,
                max_weight=float(x["w"]), knee_games=float(x["k"]),
                momentum_games=int(x["mom"]), beta_prior=float(x["beta"]),
                agree_damp=float(damp),
            )
            pb = hy.get("p_blended")
            if hy.get("applied") and pb is not None and math.isfinite(float(pb)):
                p = float(pb)
            (inter if x["inter"] else same).append((p, int(x["y"])))
        n = nota_de(inter, same)
        if base is None:
            base = n
        print("%-12.2f %8.3f %8d %8d %+10.3f  %s" % (
            damp, n, len(inter), len(same), n - base,
            "<- como e hoje" if damp == 1.0 else ""))

    # ---------------------------------------------------------------
    # POR PERIODO. Uma media boa pode esconder um ganho que so existe numa
    # epoca -- e epoca passa. Se o ganho nao aparece na maioria dos blocos,
    # nao e para mexer no preco servido por causa dele.
    # ---------------------------------------------------------------
    cache.sort(key=lambda t: str(t[0]["date"]))
    blocos = 8
    tam = max(1, len(cache) // blocos)
    print()
    print("O MESMO, por periodo (a media pode esconder epoca)")
    cab = "%-12s %6s" % ("ate", "n")
    for damp in VALORES:
        cab += " %8s" % ("%.2f" % damp)
    print(cab)
    vitorias = {d: 0 for d in VALORES if d != 1.0}
    for k in range(blocos):
        parte = cache[k * tam:(k + 1) * tam] if k < blocos - 1 else cache[k * tam:]
        if len(parte) < 50:
            continue
        linha = "%-12s %6d" % (str(parte[-1][0]["date"])[:10], len(parte))
        base_b = None
        for damp in VALORES:
            inter, same = [], []
            for x, dfa, dfb in parte:
                p = float(x["p"])
                hy = hybrid_momentum_blend(
                    p_model=p, df_team_a=dfa, df_team_b=dfb, enabled=True,
                    max_weight=float(x["w"]), knee_games=float(x["k"]),
                    momentum_games=int(x["mom"]), beta_prior=float(x["beta"]),
                    agree_damp=float(damp))
                pb = hy.get("p_blended")
                if hy.get("applied") and pb is not None and math.isfinite(float(pb)):
                    p = float(pb)
                (inter if x["inter"] else same).append((p, int(x["y"])))
            # Um bloco pode nao ter nenhum jogo interregional; ai a mistura
            # 45/55 nao existe e o honesto e pontuar so o que ha.
            n = nota_de(inter, same)
            if not math.isfinite(float(n)):
                from tools.ml_quality_scorecard import _grade_from_logloss, _metrics
                lado = inter if inter and not same else same
                n = _grade_from_logloss(_metrics(lado)["logloss"]) if lado else float("nan")
            if base_b is None:
                base_b = n
            elif math.isfinite(n) and math.isfinite(base_b) and n > base_b:
                vitorias[damp] = vitorias.get(damp, 0) + 1
            linha += " %8.3f" % n
        print(linha)
    print()
    print("blocos em que cada valor bateu o de hoje:")
    for damp, v in vitorias.items():
        print("  agree_damp %.2f -> %d de %d" % (damp, v, blocos))

    print()
    print("agree_damp 1.00 = o comportamento de sempre. 0.00 = a concordancia")
    print("deixa de aumentar o peso dado a forma.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
