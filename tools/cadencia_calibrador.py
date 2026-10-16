# -*- coding: utf-8 -*-
"""Com que CADENCIA reajustar o calibrador com grupo? (16/10/2026)

POR QUE. `tools/calibrador_envelheceu.py` mediu que o bloco em producao
(ajustado 06/09 com jogos 06-08) ainda ajuda nos jogos de set/out, mas o
servido ficou timido de novo (inclinacao 1,34; BO3 ~1,8). A cadencia de
reajuste nunca foi declarada.

ESTA FERRAMENTA SO MEDE. Nao grava params_fitted.json.

PLANO FIXADO ANTES DE RODAR (nada aqui foi escolhido olhando o resultado):
  P0 nunca       -- ajusta uma vez na calibracao (jan-mar) e nao mexe mais.
  P1 mensal      -- todo mes, com os 2.500 jogos mais recentes (o procedimento
                    do ajustador de producao: VC repetida escolhe agrupamento e L2).
  P2 trimestral  -- reajusta em abr, jul e out.
  P3 por gatilho -- no inicio de cada mes, testa o calibrador ATUAL nos jogos
                    do mes anterior (ja observados); reajusta so se o IC 95% da
                    inclinacao nao contem 1 OU o do intercepto nao contem 0, e
                    so com pelo menos 200 jogos no mes.
  Cada politica e servida ate o reajuste seguinte e pontuada mes a mes, de
  abr a out/2026: o horizonte de avaliacao e o horizonte de servico.
  DECISAO: contra P0, barra da casa (ganho > 0,002 E IC > 0) com p corrigido
  por Bonferroni (p < 0,05/3, tres candidatas). Se mais de uma passar, a de
  maior ganho; diferenca < 0,002 entre elas -> a que reajusta menos vezes.

╔══ FONTES ═════════════════════════════════════════════════════════════════╗
║ 1. Davis et al., "Comparison of Prediction Model Performance Updating     ║
║    Protocols", AMIA 2019 (resumo aberto em 16/10/2026 via Europe PMC,     ║
║    PMC7153129): comparou nunca atualizar, reajuste anual fixo e uma       ║
║    estrategia guiada por teste; "The test-based strategy generally        ║
║    recommended intermittent recalibration and delivered more highly       ║
║    calibrated predictions than either of the baseline strategies."        ║
║    -> por isso o P3 existe ao lado dos calendarios.                       ║
║ 2. Davis et al., "A nonparametric updating method to correct clinical     ║
║    prediction model drift", JAMIA 2019 (resumo aberto em 16/10/2026,      ║
║    PMC6857513): "Our test's recommendations highlighted the benefits of   ║
║    simple updating as opposed to systematic refitting in response to      ║
║    performance drift." -> aqui so o calibrador final e reajustado, nunca  ║
║    o modelo.                                                              ║
║ 3. Van Calster et al. 2019, PMC6912996 (aberta em 16/10/2026): calibracao ║
║    fraca se avalia por intercepto (alvo 0) e inclinacao (alvo 1) -- e o   ║
║    teste do gatilho.                                                      ║
║ 4. O horizonte de avaliacao tem que casar com o de servico: licao         ║
║    registrada na FONTE 6 de tools/varrer_janela_calibrador.py (Zanotti,   ║
║    arXiv:2505.00356, conferida la).                                       ║
║ 5. Bonferroni: tres comparacoes contra a mesma base. A frente 5 (deflacao ║
║    por numero de tentativas) nao comecou; isto e o minimo honesto.        ║
╚═══════════════════════════════════════════════════════════════════════════╝

LIMITES: o mes e a menor unidade de tempo que o replay guarda (Amostra.month),
entao "quinzenal" nao da para medir. O Platt do time e ajustado no treino (o
ajustador de producao o ajusta em tudo). Outubro esta incompleto.

Uso: python tools/cadencia_calibrador.py
"""
from __future__ import annotations

import importlib.util as _iu
import json
import math
import random
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mlcore.calibration import fit_platt_from_raw_probs  # noqa: E402
from mlcore.replay_pre_jogo import cadeia, carregar  # noqa: E402

_spec = _iu.spec_from_file_location("_gate", ROOT / "tools" / "gate_calibrador_final.py")
_gate = _iu.module_from_spec(_spec)
_spec.loader.exec_module(_gate)

JANELA = 2500            # o default do ajustador de producao
MIN_GATILHO = 200
TRIMESTRAL = ("2026-04", "2026-07", "2026-10")
ALFA = 0.05 / 3


def ajustar(amostras, base, folds=5, repeticoes=5):
    """O procedimento do ajustador de producao: VC repetida escolhe agrupamento e L2."""
    idx = list(range(len(amostras)))
    conjuntos = []
    for r in range(repeticoes):
        ordem = idx[:]
        random.Random(r).shuffle(ordem)
        conjuntos.append([ordem[i::folds] for i in range(folds)])
    melhor = (float("inf"), None, None)
    for nome, chave in _gate.AGRUPAMENTOS.items():
        niveis = sorted({chave(a) for a in amostras})[1:]
        for l2 in (_gate.L2_CANDIDATOS if niveis else (1.0,)):
            perdas = []
            for dobras in conjuntos:
                for f in dobras:
                    fora = set(f)
                    dentro = [i for i in idx if i not in fora]
                    cal = _gate._ajusta([amostras[i] for i in dentro], [base[i] for i in dentro],
                                        chave, niveis, l2)
                    perdas += _gate._perdas([cal(amostras[i], base[i]) for i in f],
                                            [amostras[i].y for i in f])
            m = sum(perdas) / len(perdas)
            if m < melhor[0]:
                melhor = (m, nome, l2)
            if not niveis:
                break
    _, nome, l2 = melhor
    chave = _gate.AGRUPAMENTOS[nome]
    niveis = sorted({chave(a) for a in amostras})[1:]
    return _gate._ajusta(amostras, base, chave, niveis, l2), nome, l2


def fraca(ps, ys):
    """Calibracao fraca (FONTE 3): IC 95% de intercepto e inclinacao. True se fora do alvo."""
    z = np.log(np.clip(ps, 1e-9, 1 - 1e-9) / (1 - np.clip(ps, 1e-9, 1 - 1e-9)))
    X = np.column_stack([np.ones(len(z)), z]); y = np.asarray(ys, float)
    b = np.zeros(2)
    for _ in range(100):
        mu = 1 / (1 + np.exp(-(X @ b)))
        H = X.T @ (X * (mu * (1 - mu))[:, None])
        passo = np.linalg.solve(H, X.T @ (y - mu))
        b += passo
        if np.max(np.abs(passo)) < 1e-10:
            break
    se = np.sqrt(np.diag(np.linalg.inv(H)))
    fora_inc = abs(b[1] - 1) > 1.96 * se[1]
    fora_int = abs(b[0]) > 1.96 * se[0]
    return bool(fora_inc or fora_int), float(b[0]), float(b[1])


def pareado(pa, pn):
    d = np.asarray(pa) - np.asarray(pn)
    m, se = float(d.mean()), float(d.std(ddof=1) / math.sqrt(len(d)))
    return m, math.erfc(abs(m / se) / math.sqrt(2)) if se > 0 else 1.0


def main() -> int:
    d = carregar()
    tr, va, te, tab = d["treino"], d["val"], d["teste"], d["tabela"]
    pt = fit_platt_from_raw_probs(
        [a.y for a in tr],
        cadeia(tr, tabela=tab, usar_ms1=False, usar_platt_time=False,
               usar_fusao=False, usar_ms2=False, usar_platt_fusao=False))
    passado = sorted(va + te, key=lambda a: a.month or "")
    base_de = dict(zip((a.gameid for a in passado),
                       cadeia(passado, tabela=tab, platt_time=pt, usar_ms1=True,
                              usar_ms2=False, usar_platt_fusao=False)))
    meses = sorted({a.month for a in te})
    print(f"calibracao {len(va)} jogos | servico {len(te)} jogos, meses {meses}")

    # Um calibrador por mes de reajuste possivel (os 2.500 anteriores ao mes) --
    # o mesmo para todas as politicas, so muda QUANDO cada uma o adota.
    cal_de, info_de = {}, {}
    va_base = [base_de[a.gameid] for a in va]
    cal_de["inicio"], n0, l0 = ajustar(va, va_base)
    info_de["inicio"] = {"agrupamento": n0, "l2": l0, "n": len(va)}
    for m in meses:
        ant = [a for a in passado if (a.month or "") < m][-JANELA:]
        cal_de[m], nm, lm = ajustar(ant, [base_de[a.gameid] for a in ant])
        info_de[m] = {"agrupamento": nm, "l2": lm, "n": len(ant)}
        print(f"  reajuste possivel em {m}: {len(ant)} jogos ({ant[0].month}..{ant[-1].month}) "
              f"-> '{nm}' L2={lm:g}")

    por_mes = {m: [a for a in te if a.month == m] for m in meses}

    def servir(politica):
        atual, reajustes, saida, gat = "inicio", [], {}, []
        for i, m in enumerate(meses):
            if politica == "mensal":
                atual = m; reajustes.append(m)
            elif politica == "trimestral" and m in TRIMESTRAL:
                atual = m; reajustes.append(m)
            elif politica == "gatilho" and i > 0:
                prev = por_mes[meses[i - 1]]
                if len(prev) >= MIN_GATILHO:
                    ps = np.array([cal_de[atual](a, base_de[a.gameid]) for a in prev])
                    disparou, a0, b1 = fraca(ps, [a.y for a in prev])
                    gat.append({"mes": m, "olhou": meses[i - 1], "intercepto": round(a0, 3),
                                "inclinacao": round(b1, 3), "disparou": disparou})
                    if disparou:
                        atual = m; reajustes.append(m)
            for a in por_mes[m]:
                saida[a.gameid] = cal_de[atual](a, base_de[a.gameid])
        return [saida[a.gameid] for a in te], reajustes, gat

    ys = [a.y for a in te]
    res = {}
    for pol in ("nunca", "mensal", "trimestral", "gatilho"):
        ps, rj, gat = servir(pol)
        res[pol] = {"ps": ps, "reajustes": rj, "gatilho": gat}
        _, _, b1 = fraca(np.array(ps), ys)
        print(f"{pol:<11} logloss {_gate._ll(ps, ys):.5f}  inclinacao {b1:.3f}  reajustes {rj}")
        for g in gat:
            print(f"      gatilho {g['mes']} (olhou {g['olhou']}): int {g['intercepto']:+.3f} "
                  f"inc {g['inclinacao']:.3f} -> {'REAJUSTA' if g['disparou'] else 'mantem'}")

    p0 = _gate._perdas(res["nunca"]["ps"], ys)
    print(f"\ncontra P0 (nunca), barra: ganho>0,002 E IC>0 E p<{ALFA:.4f} (Bonferroni)")
    decisao = {}
    for pol in ("mensal", "trimestral", "gatilho"):
        pn = _gate._perdas(res[pol]["ps"], ys)
        g, lo, hi = _gate._ic(p0, pn)
        _, p = pareado(p0, pn)
        passa = bool(g > 0.002 and lo > 0 and p < ALFA)
        decisao[pol] = {"ganho": round(g, 6), "ic_lo": round(lo, 6), "ic_hi": round(hi, 6),
                        "p": round(p, 6), "passa": passa, "reajustes": len(res[pol]["reajustes"])}
        print(f"  {pol:<11} ganho {g:+.5f} [{lo:+.5f}, {hi:+.5f}]  p={p:.5f}  "
              f"reajustes={len(res[pol]['reajustes'])}  {'PASSA' if passa else 'nao passa'}")

    aprovadas = [k for k, v in decisao.items() if v["passa"]]
    escolhida = None
    if aprovadas:
        topo = max(decisao[k]["ganho"] for k in aprovadas)
        perto = [k for k in aprovadas if topo - decisao[k]["ganho"] < 0.002]
        escolhida = min(perto, key=lambda k: decisao[k]["reajustes"])
    print(f"\nDECISAO PELO PLANO: {escolhida or 'nenhuma passou -- fica como esta'}")

    destino = ROOT / "evidence" / "cadencia_calibrador.json"
    destino.write_text(json.dumps({
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "meses": meses, "janela": JANELA, "alfa_bonferroni": ALFA,
        "calibradores": info_de,
        "politicas": {k: {"logloss": round(_gate._ll(v["ps"], ys), 6), "reajustes": v["reajustes"],
                          "gatilho": v["gatilho"]} for k, v in res.items()},
        "contra_nunca": decisao, "escolhida": escolhida,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[salvo] evidence/cadencia_calibrador.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
