# -*- coding: utf-8 -*-
"""A chance de vitoria melhora o handicap de kills e o total por time?

POR QUE (24/09/2026). O handicap de kills passou na prova cega, mas a conta
enxerga so kills feitos e sofridos, nao a forca do adversario. Na tela do
Dota: Aurora x GamerLegion, a Pinnacle deu Aurora -12,5 e a conta deu os dois
quase iguais -- "vantagem" de +40%, quase certamente erro do modelo. Ele
aprovou medir se juntar a chance de vitoria do modelo de vencedor resolve.

DE ONDE VEM A CHANCE DE VITORIA, PONTO-NO-TEMPO: a regua da nota honesta
(`scratchpad/nota_honesta/nota_honesta_base_agree_diaria_hybrid_form_platt.json`)
guarda, jogo a jogo, a previsao do modelo de vencedor feita NO DIA, so com o
passado. E P(lado azul vence); aqui ela e virada para cada time.

SO EXISTE EM 2026 (24/01 a 21/09), que e o ano cego da conta atual. Entao o
protocolo e todo dentro de 2026:
    escolha   ajusta 24/01-03/04 (1a metade do ajuste), confere 03/04-23/06
    ajuste    24/01-23/06
    CEGO      23/06-21/09
E a comparacao justa, nas MESMAS linhas (ancoradas na media crua):
    A  a conta que esta no ar (artefato de 2024-2025)
    B  a mesma conta, reajustada na janela de 2026    <- o que p acrescenta
    C  B + a chance de vitoria                             e medido por C - B
Criterio da casa: C melhor que B em mais de 0,0005 de Brier, com o limite
inferior do intervalo (agrupado por jogo) acima de zero.

Uso: python tools/abates_com_vitoria.py
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
INICIO_AJUSTE, MEIO_ESCOLHA, FIM_AJUSTE = "2026-01-24", "2026-04-03", "2026-06-23"
BARRA = 0.0005
DESLOC = range(-5, 6)


def _logit(p):
    p = min(max(float(p), 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def registros():
    """Os registros ponto-no-tempo de kills + a chance de vitoria de x."""
    import pandas as pd

    from mlcore.stats_teams import build_team_games, load_team_rows
    from tools.gerar_abates_por_time import registros_ponto_no_tempo
    from tools.nota_honesta import default_csvs

    pj = {str(g): float(p) for g, p, _ in json.loads(REGUA.read_text(encoding="utf-8"))["por_jogo"]}
    tg = pd.concat([build_team_games(load_team_rows(str(c))) for c in default_csvs()],
                   ignore_index=True)
    tg["date"] = pd.to_datetime(tg["date"], errors="coerce")
    azul = {str(g): str(t) for g, t, s in zip(tg["gameid"], tg["team"], tg["side"])
            if str(s).lower() == "blue"}
    quando = {str(g): d for g, d in zip(tg["gameid"], tg["date"])}
    fora = []
    for r in registros_ponto_no_tempo(tg):
        g = r["gameid"]
        if g not in pj or g not in azul:
            continue
        r = dict(r)
        r["data"] = str(quando[g])[:10]
        fora.append(r)
    # x e o primeiro time em ordem alfabetica (a ordem de
    # `registros_ponto_no_tempo`); a regua fala do AZUL -- vira para x.
    times = {}
    for g, t in zip(tg["gameid"].astype(str), tg["team"].astype(str)):
        times.setdefault(g, []).append(t)
    for r in fora:
        x = sorted(times[r["gameid"]])[0]
        lp = _logit(pj[r["gameid"]])
        r["lpx"] = lp if azul[r["gameid"]] == x else -lp
    return fora


def ajustar(regs, com_p):
    """Handicap: D = b1*M (+ b2*lp); por time: K = c0 + c1*E (+ c2*lp).

    Forma e largura como na producao (quantis espelhados; reta no total
    esperado para o handicap, raiz da media para o por time).
    """
    import numpy as np

    from tools.gerar_abates_por_time import _quantis, _reta_da_largura
    D = np.array([r["kx"] - r["ky"] for r in regs])
    M = np.array([r["ex"] - r["ey"] for r in regs])
    L = np.array([r["lpx"] for r in regs])
    X = np.column_stack([M, L]) if com_p else M[:, None]
    bh = np.linalg.lstsq(X, D, rcond=None)[0]
    mh = X @ bh
    a, b = _reta_da_largura([r["ex"] + r["ey"] for r in regs], list(D - mh))
    esc = np.maximum(a + b * np.array([r["ex"] + r["ey"] for r in regs]), 1.0)
    z = (D - mh) / esc
    h = {"coef": [float(v) for v in bh], "a": a, "b": b,
         "quantis": _quantis(list(z) + list(-z))}
    K = np.array([r["kx"] for r in regs] + [r["ky"] for r in regs])
    E = np.array([r["ex"] for r in regs] + [r["ey"] for r in regs])
    LP = np.concatenate([L, -L])
    Xt = np.column_stack([np.ones_like(E), E, LP]) if com_p else np.column_stack([np.ones_like(E), E])
    bt = np.linalg.lstsq(Xt, K, rcond=None)[0]
    mt = Xt @ bt
    t = {"coef": [float(v) for v in bt],
         "quantis": _quantis(list((K - mt) / np.sqrt(np.maximum(mt, 1e-6))))}
    return {"handicap": h, "total_time": t, "com_p": com_p}


def _acima(q, folga):
    import bisect
    return 1.0 - bisect.bisect_right(q, folga) / len(q)


def prob_h(art, ea, eb, lp, pontos):
    h = art["handicap"]
    m = h["coef"][0] * (ea - eb) + (h["coef"][1] * lp if art["com_p"] else 0.0)
    esc = max(h["a"] + h["b"] * (ea + eb), 1.0)
    return _acima(h["quantis"], (-pontos - m) / esc)


def prob_t(art, e, lp, linha):
    c = art["total_time"]["coef"]
    m = c[0] + c[1] * e + (c[2] * lp if art["com_p"] else 0.0)
    if m <= 0:
        return None
    return _acima(art["total_time"]["quantis"], (linha - m) / math.sqrt(m))


def prob_h_no_ar(ea, eb, lp, pontos):
    from mlcore.abates_por_time import prob_cobre_handicap
    return prob_cobre_handicap(ea, eb, pontos)


def prob_t_no_ar(e, lp, linha):
    from mlcore.abates_por_time import prob_total_do_time_acima
    return prob_total_do_time_acima(e, linha)


def apostas(regs, fh, ft):
    """(gameid, mercado, p, deu) nas linhas ancoradas na media CRUA."""
    fora = []
    for r in regs:
        for a, b, lp in (("x", "y", r["lpx"]), ("y", "x", -r["lpx"])):
            ka, kb, ea, eb = r["k" + a], r["k" + b], r["e" + a], r["e" + b]
            base = math.floor(-(ea - eb)) + 0.5
            for j in DESLOC:
                L = base + j
                p = fh(ea, eb, lp, L)
                if p is not None:
                    fora.append((r["gameid"], "handicap", p, 1.0 if ka + L > kb else 0.0))
            base_t = math.floor(ea) + 0.5
            for j in DESLOC:
                L = base_t + j
                p = ft(ea, lp, L)
                if p is not None:
                    fora.append((r["gameid"], "total_time", p, 1.0 if ka > L else 0.0))
    return fora


def comparar(teste, fh1, ft1, fh2, ft2, reamostras=1000):
    """Brier de 1 menos Brier de 2 (positivo = 2 melhor), com IC por jogo."""
    import numpy as np
    a1, a2 = apostas(teste, fh1, ft1), apostas(teste, fh2, ft2)
    fora = {}
    for merc in ("handicap", "total_time"):
        s1 = [(g, (p - y) ** 2) for g, m, p, y in a1 if m == merc]
        s2 = [(g, (p - y) ** 2) for g, m, p, y in a2 if m == merc]
        assert len(s1) == len(s2)
        gids = sorted({g for g, _ in s1})
        ix = {g: i for i, g in enumerate(gids)}
        d1, d2, n = np.zeros(len(gids)), np.zeros(len(gids)), np.zeros(len(gids))
        for (g, b1), (_, b2) in zip(s1, s2):
            d1[ix[g]] += b1
            d2[ix[g]] += b2
            n[ix[g]] += 1
        rng = np.random.default_rng(20260924)
        gan = []
        for _ in range(reamostras):
            s = rng.integers(0, len(gids), len(gids))
            gan.append((d1[s].sum() - d2[s].sum()) / n[s].sum())
        fora[merc] = {"b1": d1.sum() / n.sum(), "b2": d2.sum() / n.sum(),
                      "ganho": (d1.sum() - d2.sum()) / n.sum(),
                      "ic": (float(np.quantile(gan, .025)), float(np.quantile(gan, .975))),
                      "jogos": len(gids)}
    return fora


def calibracao(teste, fh, ft):
    fora = {}
    for merc in ("handicap", "total_time"):
        ps = [(p, y) for g, m, p, y in apostas(teste, fh, ft) if m == merc]
        tab = []
        for lo, hi in ((0, .25), (.25, .35), (.35, .45), (.45, .55), (.55, .65), (.65, .75), (.75, 1.01)):
            sub = [(p, y) for p, y in ps if lo <= p < hi]
            if len(sub) >= 200:
                tab.append((lo, hi, len(sub), sum(p for p, _ in sub) / len(sub),
                            sum(y for _, y in sub) / len(sub)))
        fora[merc] = tab
    return fora


def main() -> int:
    regs = registros()
    esc_aj = [r for r in regs if INICIO_AJUSTE <= r["data"] < MEIO_ESCOLHA]
    esc_cf = [r for r in regs if MEIO_ESCOLHA <= r["data"] < FIM_AJUSTE]
    ajuste = esc_aj + esc_cf
    cego = [r for r in regs if r["data"] >= FIM_AJUSTE]
    print("[vitoria] jogos: escolha %d + %d | ajuste %d | CEGO %d"
          % (len(esc_aj), len(esc_cf), len(ajuste), len(cego)))

    # conferencia antes do cego: p ajuda na janela de escolha?
    B0, C0 = ajustar(esc_aj, False), ajustar(esc_aj, True)
    r0 = comparar(esc_cf,
                  lambda ea, eb, lp, L: prob_h(B0, ea, eb, lp, L), lambda e, lp, L: prob_t(B0, e, lp, L),
                  lambda ea, eb, lp, L: prob_h(C0, ea, eb, lp, L), lambda e, lp, L: prob_t(C0, e, lp, L),
                  reamostras=200)
    for m, v in r0.items():
        print("[vitoria] conferencia %s: B %.5f  C %.5f  ganho %+.5f" % (m, v["b1"], v["b2"], v["ganho"]))

    B, C = ajustar(ajuste, False), ajustar(ajuste, True)
    print("[vitoria] handicap: B coef %s | C coef %s" % (
        [round(x, 3) for x in B["handicap"]["coef"]], [round(x, 3) for x in C["handicap"]["coef"]]))
    print("[vitoria] por time: B coef %s | C coef %s" % (
        [round(x, 3) for x in B["total_time"]["coef"]], [round(x, 3) for x in C["total_time"]["coef"]]))
    fB = (lambda ea, eb, lp, L: prob_h(B, ea, eb, lp, L), lambda e, lp, L: prob_t(B, e, lp, L))
    fC = (lambda ea, eb, lp, L: prob_h(C, ea, eb, lp, L), lambda e, lp, L: prob_t(C, e, lp, L))
    fA = (prob_h_no_ar, prob_t_no_ar)

    print()
    print("PROVA CEGA (%s em diante)" % FIM_AJUSTE)
    for nome, (f1, f2) in (("C contra B (o que a chance de vitoria acrescenta)", (fB, fC)),
                           ("C contra A (contra o que esta no ar)", (fA, fC))):
        res = comparar(cego, f1[0], f1[1], f2[0], f2[1])
        print("  " + nome)
        for m, v in res.items():
            ok = v["ganho"] > BARRA and v["ic"][0] > 0
            print("    %-10s  antes %.5f  depois %.5f  ganho %+.5f  IC95 [%+.5f, %+.5f]  %s"
                  % (m, v["b1"], v["b2"], v["ganho"], v["ic"][0], v["ic"][1],
                     "PASSA" if ok else "nao passa"))
    passou_tudo = True
    for f1 in (fB, fA):
        for m, v in comparar(cego, f1[0], f1[1], fC[0], fC[1], reamostras=1000).items():
            passou_tudo = passou_tudo and v["ganho"] > BARRA and v["ic"][0] > 0
    print()
    print("CALIBRACAO CONDICIONAL no cego, versao C")
    for m, tab in calibracao(cego, *fC).items():
        print("  " + m)
        for lo, hi, n, pm, ob in tab:
            print("    %3.0f%%-%3.0f%%  %6d  modelo %5.1f%%  aconteceu %5.1f%%  %+5.1fpp"
                  % (100 * lo, 100 * hi, n, 100 * pm, 100 * ob, 100 * (pm - ob)))
    if not passou_tudo:
        print()
        print("[vitoria] NAO passou nos dois mercados contra B e contra A: nada gravado.")
        return 1
    if "--sem-gravar" in sys.argv:
        return 0
    # Grava AO LADO dos blocos de sempre: o confronto aberto (que tem a
    # chance de vitoria do cartao) usa estes; os outros jogos, os de sempre.
    alvo = ROOT / "abates_por_time_forma.json"
    d = json.loads(alvo.read_text(encoding="utf-8"))
    d["handicap_com_vitoria"] = {"modo": "vitoria", **C["handicap"]}
    d["total_time_com_vitoria"] = {"modo": "vitoria", **C["total_time"]}
    d["_com_vitoria"] = {"regua": REGUA.name, "ajuste": [INICIO_AJUSTE, FIM_AJUSTE],
                         "cego": [FIM_AJUSTE, max(r["data"] for r in cego)],
                         "gerado_por": "tools/abates_com_vitoria.py"}
    alvo.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    print("[vitoria] passou e gravou os blocos com vitoria em %s" % alvo.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
