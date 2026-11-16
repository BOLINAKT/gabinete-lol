# -*- coding: utf-8 -*-
"""GATE: acrescentar o TIER DA LIGA ao calibrador com grupo melhora a previsao?

POR QUE (16/10/2026). `tools/diagnostico_timidez.py` mediu, nos 8.336 jogos da
nota honesta, inclinacao de calibracao 1,145 no geral e 1,43 nas ligas grandes
(alvo 1; acima de 1 = moderado demais). O calibrador em producao agrupa so por
formato e fase (`mlcore/agrupamentos.py`); o tier nunca foi candidato. O
calibrador POR LIGA foi reprovado em 16/08 (liga a liga, amostra pequena), e o
gate de 04/09 mediu que 79 grupos (BO x liga) fazem o ganho sumir. Aqui o tier
entra com POUCOS niveis.

ESTA FERRAMENTA SO MEDE. Nao grava em params_fitted.json e nao toca no app.

╔══ FONTES ═════════════════════════════════════════════════════════════════╗
║ O desenho e o do `tools/gate_calibrador_final.py` e herda as FONTES dele  ║
║ (grupo como feature, poucos grupos, escolha DENTRO da calibracao com VC   ║
║ repetida, teste tocado uma vez, logloss decide, barra em conjuncao). As   ║
║ funcoes de ajuste e de intervalo sao as dele, importadas -- nao copiadas. ║
║                                                                           ║
║ A BASE E A PRODUCAO DE HOJE, nao a cadeia crua (CLAUDE.md: "Base fraca da ║
║ ACCEPT falso"). O replay (`variante`) nao aplica o calibrador com grupo,  ║
║ entao o "atual" aqui e o mesmo PROCEDIMENTO do ajustador de producao      ║
║ (`tools/ajustar_calibrador_grupo.py`): cadeia com microssegmento (o app   ║
║ roda), VC escolhendo entre os 4 agrupamentos de hoje.                     ║
║                                                                           ║
║ Inclinacao de calibracao (abertas em 16/10/2026): Van Calster et al.      ║
║ 2019, PMC6912996 -- "The calibration slope evaluates the spread of the    ║
║ estimated risks and has a target value of 1." / "A slope > 1 suggests the ║
║ opposite, i.e., that risk estimates are too moderate."                    ║
║                                                                           ║
║ BARRA DA CASA (CLAUDE.md, regra 6): ganho > 0,002 E p < 0,05 E limite     ║
║ inferior do IC > 0. O p aqui e do teste pareado nas perdas por jogo.      ║
║                                                                           ║
║ LIMITE HONESTO: o teste cego (depois de 31/03/2026) ja foi usado pelo     ║
║ gate de 04-06/09. Os jogos de setembro em diante sao novos para qualquer  ║
║ decisao. Sai impresso o resultado SO nesses, para quem quiser a leitura   ║
║ mais limpa.                                                               ║
╚═══════════════════════════════════════════════════════════════════════════╝

Uso: python tools/gate_calibrador_tier.py
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
from mlcore.tiers import tier_for_league  # noqa: E402

_spec = _iu.spec_from_file_location("_gate", ROOT / "tools" / "gate_calibrador_final.py")
_gate = _iu.module_from_spec(_spec)
_spec.loader.exec_module(_gate)

NOVO_A_PARTIR_DE = "2026-09"   # jogos que nenhum gate anterior viu


def _t1(a) -> str:
    return "T1" if tier_for_league(a.league) == "T1" else "resto"


def _t12(a) -> str:
    t = tier_for_league(a.league)
    return t if t in ("T1", "T2") else "resto"


ATUAIS = dict(_gate.AGRUPAMENTOS)
NOVOS = {
    "tier (T1 x resto)": _t1,
    "tier (T1/T2/resto)": _t12,
    "formato + fase + T1": lambda a: f"{a.bo}|{a.phase}|{_t1(a)}",
}


def escolher(candidatos, va, b_va, conjuntos):
    """VC repetida DENTRO da calibracao (fonte 3 do gate). Devolve (nome, l2, tabela)."""
    idx = list(range(len(va)))
    melhor, tabela = (float("inf"), None, None), []
    for nome, chave in candidatos.items():
        niveis = sorted({chave(a) for a in va})[1:]
        for l2 in (_gate.L2_CANDIDATOS if niveis else (1.0,)):
            perdas = []
            for dobras in conjuntos:
                for f in dobras:
                    fora = set(f)
                    dentro = [i for i in idx if i not in fora]
                    cal = _gate._ajusta([va[i] for i in dentro], [b_va[i] for i in dentro],
                                        chave, niveis, l2)
                    perdas += _gate._perdas([cal(va[i], b_va[i]) for i in f],
                                            [va[i].y for i in f])
            m = sum(perdas) / len(perdas)
            tabela.append({"agrupamento": nome, "l2": l2, "logloss_vc": round(m, 6)})
            if m < melhor[0]:
                melhor = (m, nome, l2)
            if not niveis:
                break
    return melhor[1], melhor[2], tabela


def aplicar(candidatos, nome, l2, va, b_va, alvo, b_alvo):
    chave = candidatos[nome]
    niveis = sorted({chave(a) for a in va})[1:]
    cal = _gate._ajusta(va, b_va, chave, niveis, l2)
    return [cal(a, p) for a, p in zip(alvo, b_alvo)]


def pareado(perda_atual, perda_novo):
    """Ganho medio (atual - novo), erro padrao e p bilateral do teste pareado."""
    d = np.asarray(perda_atual) - np.asarray(perda_novo)
    m, se = float(d.mean()), float(d.std(ddof=1) / math.sqrt(len(d)))
    z = m / se if se > 0 else 0.0
    return m, se, math.erfc(abs(z) / math.sqrt(2))


def inclinacao(ps, ys):
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
    se = math.sqrt(np.linalg.inv(H)[1, 1])
    return b[1], b[1] - 1.96 * se, b[1] + 1.96 * se


def main(folds: int = 5, repeticoes: int = 5) -> int:
    d = carregar()
    tr, va, te, tab = d["treino"], d["val"], d["teste"], d["tabela"]
    pt = fit_platt_from_raw_probs(
        [a.y for a in tr],
        cadeia(tr, tabela=tab, usar_ms1=False, usar_platt_time=False,
               usar_fusao=False, usar_ms2=False, usar_platt_fusao=False))
    # a cadeia que o app roda antes do calibrador com grupo (ver o ajustador)
    b_va = cadeia(va, tabela=tab, platt_time=pt, usar_ms1=True, usar_ms2=False, usar_platt_fusao=False)
    b_te = cadeia(te, tabela=tab, platt_time=pt, usar_ms1=True, usar_ms2=False, usar_platt_fusao=False)
    ys = [a.y for a in te]
    print(f"calibracao: {len(va)} jogos | teste cego: {len(te)} jogos "
          f"({min(a.month for a in te)} -> {max(a.month for a in te)})")

    idx = list(range(len(va)))
    conjuntos = []
    for r in range(int(repeticoes)):
        ordem = idx[:]
        random.Random(r).shuffle(ordem)
        conjuntos.append([ordem[i::folds] for i in range(folds)])

    n_at, l2_at, tab_at = escolher(ATUAIS, va, b_va, conjuntos)
    todos = {**ATUAIS, **NOVOS}
    n_nv, l2_nv, tab_nv = escolher(todos, va, b_va, conjuntos)
    print(f"ATUAL (procedimento de producao): '{n_at}' L2={l2_at:g}")
    print(f"NOVO  (com o tier entre os candidatos): '{n_nv}' L2={l2_nv:g}")
    for linha in sorted(tab_nv, key=lambda x: x["logloss_vc"])[:8]:
        print(f"   VC  {linha['agrupamento']:<24} L2={linha['l2']:<6g} {linha['logloss_vc']:.6f}")

    atual = aplicar(todos, n_at, l2_at, va, b_va, te, b_te)
    novo = aplicar(todos, n_nv, l2_nv, va, b_va, te, b_te)
    pa, pn = _gate._perdas(atual, ys), _gate._perdas(novo, ys)
    g, lo, hi = _gate._ic(pa, pn)
    _, _, p = pareado(pa, pn)
    passa = bool(g > 0.002 and p < 0.05 and lo > 0)
    print(f"\nTESTE CEGO: logloss atual {_gate._ll(atual, ys):.5f}  novo {_gate._ll(novo, ys):.5f}")
    print(f"ganho {g:+.5f}  IC95% [{lo:+.5f}, {hi:+.5f}]  p={p:.4f}")
    print(f"barra da casa (ganho>0,002 E p<0,05 E IC>0): {'PASSA' if passa else 'NAO passa'}")

    sel = [i for i, a in enumerate(te) if a.month >= NOVO_A_PARTIR_DE]
    if len(sel) >= 200:
        ga, lo2, hi2 = _gate._ic([pa[i] for i in sel], [pn[i] for i in sel])
        _, _, p2 = pareado([pa[i] for i in sel], [pn[i] for i in sel])
        print(f"so os jogos de {NOVO_A_PARTIR_DE} em diante (n={len(sel)}): "
              f"ganho {ga:+.5f} [{lo2:+.5f}, {hi2:+.5f}] p={p2:.4f}")

    print("\ninclinacao de calibracao no teste cego (alvo 1):")
    por_tier = {}
    for nome_g, f in (("T1", lambda a: _t1(a) == "T1"), ("resto", lambda a: _t1(a) != "T1")):
        ii = [i for i, a in enumerate(te) if f(a)]
        sa = inclinacao(np.array([atual[i] for i in ii]), [ys[i] for i in ii])
        sn = inclinacao(np.array([novo[i] for i in ii]), [ys[i] for i in ii])
        por_tier[nome_g] = {"n": len(ii), "atual": [round(x, 3) for x in sa], "novo": [round(x, 3) for x in sn]}
        print(f"  {nome_g:<6} n={len(ii):5d}  atual {sa[0]:.3f} [{sa[1]:.3f},{sa[2]:.3f}]   "
              f"novo {sn[0]:.3f} [{sn[1]:.3f},{sn[2]:.3f}]")

    destino = ROOT / "evidence" / "gate_calibrador_tier.json"
    destino.write_text(json.dumps({
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "atual": {"agrupamento": n_at, "l2": l2_at},
        "novo": {"agrupamento": n_nv, "l2": l2_nv},
        "teste": {"n": len(te), "ganho": round(g, 6), "ic_lo": round(lo, 6), "ic_hi": round(hi, 6),
                  "p": round(p, 6), "passa": passa},
        "inclinacao_por_tier": por_tier,
        "validacao_cruzada": tab_nv,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[salvo] evidence/gate_calibrador_tier.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
