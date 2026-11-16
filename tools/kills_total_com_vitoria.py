# -*- coding: utf-8 -*-
"""A chance de vitoria melhora o TOTAL de kills do mapa?

POR QUE (25/09/2026). No handicap de kills e no total por time, juntar a
chance de vitoria do modelo de vencedor melhorou a conta na prova cega
(tools/abates_com_vitoria.py: +0,0036 e +0,0037 de Brier). O total de kills
do mapa -- o mercado que ele mais aposta -- ainda nao usa essa informacao.
Ele deu a iniciativa ("pode tomar a iniciativa e fazer da forma que voce
preferir").

O TOTAL NAO TEM LADO. A informacao que pode importar e o TAMANHO do
favoritismo: jogo de 80/20 tende a ser atropelo, e atropelo tem outro padrao
de kills que jogo parelho. Entao a variavel e |logit(p)| -- simetrica, igual
para os dois times.

A MEDIA QUE SE COMPARA E A DA TELA. A previsao servida (`_expected_totals_dc`:
V0 + Dixon-Coles, curva normal com o sd do motor) e coletada ponto-no-tempo
por `tools/eval_totais_forma_empirica._coletar_servido`, a mesma rotina do
gate de 23/09, agora guardando o jogo.

PROTOCOLO (a chance de vitoria ponto-no-tempo so existe em 2026, na regua da
nota honesta):
    escolha   ajusta 24/01-03/04, confere 03/04-23/06
    ajuste    24/01-23/06
    CEGO      23/06-21/09
    A  a conta que esta no ar (normal com media e sd servidos)
    B  a mesma media, reajustada (reta) com a forma real do erro -- o que o
       reajuste sozinho faz
    C  B + |logit(p)|                          <- o que a vitoria acrescenta
    linhas: em volta da media servida, 5 de cada lado, IGUAIS para A, B e C
Criterio da casa: > 0,0005 de Brier e limite inferior do IC (por jogo) > 0.

Uso: python tools/kills_total_com_vitoria.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REGUA = ROOT / "scratchpad" / "nota_honesta" / "nota_honesta_base_agree_diaria_hybrid_form_platt.json"
CACHE = ROOT / "scratchpad" / "kills_servido_2026.json"
INICIO, MEIO, FIM = "2026-01-24", "2026-04-03", "2026-06-23"
BARRA = 0.0005
DESLOC = range(-5, 6)


def _logit(p):
    p = min(max(float(p), 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def coletar():
    """[{gameid, data, mean, sd, actual}] do caminho servido, 2026."""
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    import pandas as pd

    from mlcore.stats_teams import build_team_games, load_team_rows
    from tools.eval_totais_forma_empirica import _coletar_servido
    from tools.nota_honesta import default_csvs
    tg = pd.concat([build_team_games(load_team_rows(str(c))) for c in default_csvs()],
                   ignore_index=True)
    tg["date"] = pd.to_datetime(tg["date"], errors="coerce")
    tg = tg.dropna(subset=["date"])
    quando = {str(g): str(d)[:10] for g, d in zip(tg["gameid"], tg["date"])}
    regs = [r for r in _coletar_servido(tg, 2026) if r["metric"] == "kills"]
    fora = [{"gameid": r["gameid"], "data": quando.get(r["gameid"], ""),
             "mean": r["mean"], "sd": r["sd"], "actual": r["actual"]} for r in regs]
    CACHE.write_text(json.dumps(fora), encoding="utf-8")
    return fora


def juntar(regs):
    pj = {str(g): float(p) for g, p, _ in json.loads(REGUA.read_text(encoding="utf-8"))["por_jogo"]}
    fora = []
    for r in regs:
        if r["gameid"] in pj:
            fora.append(dict(r, m=abs(_logit(pj[r["gameid"]]))))
    return fora


def ajustar(regs, com_p):
    import numpy as np

    from tools.gerar_abates_por_time import _quantis
    K = np.array([r["actual"] for r in regs])
    E = np.array([r["mean"] for r in regs])
    M = np.array([r["m"] for r in regs])
    X = np.column_stack([np.ones_like(E), E, M]) if com_p else np.column_stack([np.ones_like(E), E])
    b = np.linalg.lstsq(X, K, rcond=None)[0]
    res = K - X @ b
    return {"coef": [float(v) for v in b], "com_p": com_p, "quantis": _quantis(list(res))}


def _acima(q, folga):
    import bisect
    return 1.0 - bisect.bisect_right(q, folga) / len(q)


def prob(art, r, L):
    c = art["coef"]
    m = c[0] + c[1] * r["mean"] + (c[2] * r["m"] if art["com_p"] else 0.0)
    return _acima(art["quantis"], L - m)


def prob_no_ar(r, L):
    """A conta de ANTES do reajuste semanal: normal com media e sd servidos.

    Sem `metric`, de proposito: desde 25/09/2026 o motor aplica o reajuste
    semanal aos kills (kills_recalibrado.json), e esta regua compara
    justamente contra a conta sem ele."""
    from mlcore.lines_engine import MatchupTotals, prob_over_from_total
    t = MatchupTotals(mean=r["mean"], sd=r["sd"], dist="normal")
    return prob_over_from_total(t, L)


def apostas(regs, f):
    fora = []
    for r in regs:
        base = math.floor(r["mean"]) + 0.5
        for j in DESLOC:
            L = base + j
            fora.append((r["gameid"], f(r, L), 1.0 if r["actual"] > L else 0.0))
    return fora


def comparar(regs, f1, f2, reamostras=1000):
    import numpy as np
    a1, a2 = apostas(regs, f1), apostas(regs, f2)
    gids = sorted({g for g, _, _ in a1})
    ix = {g: i for i, g in enumerate(gids)}
    d1, d2, n = np.zeros(len(gids)), np.zeros(len(gids)), np.zeros(len(gids))
    for (g, p1, y), (_, p2, _) in zip(a1, a2):
        d1[ix[g]] += (p1 - y) ** 2
        d2[ix[g]] += (p2 - y) ** 2
        n[ix[g]] += 1
    rng = np.random.default_rng(20260925)
    gan = []
    for _ in range(reamostras):
        s = rng.integers(0, len(gids), len(gids))
        gan.append((d1[s].sum() - d2[s].sum()) / n[s].sum())
    return {"b1": d1.sum() / n.sum(), "b2": d2.sum() / n.sum(),
            "ganho": (d1.sum() - d2.sum()) / n.sum(),
            "ic": (float(np.quantile(gan, .025)), float(np.quantile(gan, .975))),
            "jogos": len(gids)}


def calibracao(regs, f):
    ps = [(p, y) for _, p, y in apostas(regs, f)]
    fora = []
    for lo, hi in ((0, .25), (.25, .35), (.35, .45), (.45, .55), (.55, .65), (.65, .75), (.75, 1.01)):
        sub = [(p, y) for p, y in ps if lo <= p < hi]
        if len(sub) >= 200:
            fora.append((lo, hi, len(sub), sum(p for p, _ in sub) / len(sub),
                         sum(y for _, y in sub) / len(sub)))
    return fora


def main() -> int:
    regs = juntar(coletar())
    esc_aj = [r for r in regs if INICIO <= r["data"] < MEIO]
    esc_cf = [r for r in regs if MEIO <= r["data"] < FIM]
    ajuste = esc_aj + esc_cf
    cego = [r for r in regs if r["data"] >= FIM]
    print("[kills] jogos: escolha %d + %d | ajuste %d | CEGO %d"
          % (len(esc_aj), len(esc_cf), len(ajuste), len(cego)))

    B0, C0 = ajustar(esc_aj, False), ajustar(esc_aj, True)
    r0 = comparar(esc_cf, lambda r, L: prob(B0, r, L), lambda r, L: prob(C0, r, L), 200)
    print("[kills] conferencia: B %.5f  C %.5f  ganho %+.5f" % (r0["b1"], r0["b2"], r0["ganho"]))

    B, C = ajustar(ajuste, False), ajustar(ajuste, True)
    print("[kills] B coef %s | C coef %s" % ([round(x, 3) for x in B["coef"]],
                                           [round(x, 3) for x in C["coef"]]))
    fA = prob_no_ar
    fB = lambda r, L: prob(B, r, L)
    fC = lambda r, L: prob(C, r, L)
    print()
    print("PROVA CEGA (%s em diante)" % FIM)
    for nome, f1, f2 in (("B contra A (so o reajuste)", fA, fB),
                         ("C contra B (o que a chance de vitoria acrescenta)", fB, fC),
                         ("C contra A (contra o que esta no ar)", fA, fC)):
        v = comparar(cego, f1, f2)
        ok = v["ganho"] > BARRA and v["ic"][0] > 0
        print("  %-48s antes %.5f depois %.5f ganho %+.5f IC95 [%+.5f, %+.5f] %s"
              % (nome, v["b1"], v["b2"], v["ganho"], v["ic"][0], v["ic"][1],
                 "PASSA" if ok else "nao passa"))
    for nome, f in (("A (no ar)", fA), ("C", fC)):
        print("\nCALIBRACAO CONDICIONAL no cego, " + nome)
        for lo, hi, n, pm, ob in calibracao(cego, f):
            print("    %3.0f%%-%3.0f%%  %6d  modelo %5.1f%%  aconteceu %5.1f%%  %+5.1fpp"
                  % (100 * lo, 100 * hi, n, 100 * pm, 100 * ob, 100 * (pm - ob)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
