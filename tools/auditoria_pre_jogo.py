# -*- coding: utf-8 -*-
"""AUDITORIA DO PRÉ-JOGO — o número da tela é honesto, e onde ele mente.

Pergunta dele (26/08/2026): "quero ter certeza que o número que estou vendo é
confiável — posso não concordar, mas ele tem que fazer sentido como preço."
Critério mensurável: quando o modelo diz 70%, tem que acontecer 70%. E tem que
valer NA LIGA em que ele aposta, não só na média.

TRÊS PERGUNTAS, TRÊS FERRAMENTAS, TODAS ESCOLHIDAS POR PESQUISA:

  1) A régua oficial mede o que a tela serve?
     Divergência entre o que `ml_fusion_scorecard` calcula e o caminho de
     produção. Se for 0,001 a nota serve; se for 0,05 ela descreve outro
     produto — e é essa nota que o vigia semanal guarda.

  2) Cada etapa ajuda?
     Ablação POR REMOÇÃO (não cumulativa), com a decomposição
     CALIBRAÇÃO/REFINAMENTO (Berta, Holzmüller, Jordan & Bach 2025).
     Refinamento = a logloss depois de recalibrar de forma ótima, ou seja, o
     que sobra de informação de verdade.
       remover piora o refinamento  -> a etapa ADICIONA informação
       remover não mexe no refinamento, só na logloss -> a etapa só ajeita a
         régua, e poderia ser trocada por uma recalibração final
       remover MELHORA tudo -> a etapa estava atrapalhando
     Cada variante REAJUSTA os próprios calibradores; sem isso a comparação
     seria fraudada a favor do status quo.

     SUSPEITO PRINCIPAL: o microssegmento. É uma multicalibração caseira, e a
     literatura diz que impor calibração por grupo custa muito mais dado
     (erro^-3 contra erro^-2) porque estima médias em células pequenas — o
     mesmo regime em que o calibrador do ao vivo perdeu em 15 de 15.

  3) Em que grupo o número mente?
     Z DE SPIEGELHALTER por grupo: não-paramétrico, SEM binning, sem parâmetro
     para escolher errado. Sob a hipótese de que o grupo está calibrado,
     Z ~ Normal(0,1). Escolhido no lugar do ECE porque ECE é estimador
     enviesado e sensível ao número de caixas.
     Com correção de BENJAMINI-HOCHBERG: testar 40 grupos a 5% produz ~2
     "mentirosos" por acaso. BH controla a proporção de falsas descobertas e é
     a escolha certa para triagem de subgrupos (Bonferroni esconderia efeito
     real).

Uso: python tools/auditoria_pre_jogo.py
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mlcore.calibration import fit_beta_from_raw_probs  # noqa: E402
from mlcore.replay_pre_jogo import carregar, p_regua, variante  # noqa: E402

EPS = 1e-12

# Ablacao POR REMOCAO: cada linha desliga UMA etapa e mantem o resto.
VARIANTES = [
    ("caminho completo (SERVIDO)", {}),
    ("sem microssegmento no time", {"usar_ms1": False}),
    ("sem microssegmento na fusao", {"usar_ms2": False}),
    ("sem NENHUM microssegmento", {"usar_ms1": False, "usar_ms2": False}),
    ("sem Platt do time", {"usar_platt_time": False}),
    ("sem Platt da fusao", {"usar_platt_fusao": False}),
    ("sem a camada de jogadores", {"usar_fusao": False}),
]


def _ll(ps, ys) -> float:
    return sum(-(math.log(min(max(p, EPS), 1 - EPS)) if y == 1
                 else math.log(1 - min(max(p, EPS), 1 - EPS)))
               for p, y in zip(ps, ys)) / max(1, len(ys))


def refinamento(ps, ys) -> float:
    """Logloss depois de recalibrar de forma otima. Usa a familia beta, que
    CONTEM a identidade: se ja estiver calibrado, a recalibracao pode nao fazer
    nada e o refinamento coincide com a logloss."""
    cal = fit_beta_from_raw_probs(ys, ps)
    return _ll([cal.predict_proba(p) for p in ps], ys)


def spiegelhalter_z(ps, ys) -> tuple[float, float]:
    """Z = SUM (y-p)(1-2p) / sqrt(SUM (1-2p)^2 p (1-p)); sob H0, Z ~ N(0,1)."""
    num = den = 0.0
    for p, y in zip(ps, ys):
        p = min(max(float(p), 1e-9), 1 - 1e-9)
        num += (y - p) * (1 - 2 * p)
        den += ((1 - 2 * p) ** 2) * p * (1 - p)
    if den <= 0:
        return float("nan"), float("nan")
    z = num / math.sqrt(den)
    return z, math.erfc(abs(z) / math.sqrt(2.0))


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Grupo pequeno mostra intervalo largo em vez de fingir precisao."""
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - r) / d, (c + r) / d


def benjamini_hochberg(pvs: list[float], alpha: float = 0.05) -> list[bool]:
    """Controla a PROPORCAO de falsas descobertas entre as rejeitadas.

    Escolhido em vez de Bonferroni porque isto e triagem exploratoria de
    subgrupos: Bonferroni controla a chance de UM falso positivo e, com dezenas
    de grupos, esconderia quase todo efeito real."""
    m = len(pvs)
    if m == 0:
        return []
    ordem = sorted(range(m), key=lambda i: pvs[i])
    corte = -1
    for posicao, i in enumerate(ordem, start=1):
        if pvs[i] <= posicao / m * alpha:
            corte = posicao
    marcados = [False] * m
    for posicao, i in enumerate(ordem, start=1):
        if posicao <= corte:
            marcados[i] = True
    return marcados


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-grupo", type=int, default=60)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--out", default="evidence/auditoria_pre_jogo.json")
    args = ap.parse_args()

    d = carregar()
    treino, teste, tabela = d["treino"], d["teste"], d["tabela"]
    if not teste:
        print("sem amostras de teste")
        return 1
    ys = [a.y for a in teste]
    n = len(ys)
    print(f"temporada cega: {n} jogos | treino: {len(treino)} | "
          f"taxa-base {sum(ys) / n:.3f} | segmentos no microssegmento: {len(tabela)}\n")

    servido = variante(treino, teste, tabela=tabela)
    regua = p_regua(teste, d["w_lineup"])

    # ---------------------------------------------------------------- 1
    difs = sorted(abs(a - b) for a, b in zip(regua, servido))
    print("=== 1) A REGUA OFICIAL MEDE O QUE A TELA SERVE? ===")
    print(f"|regua - servido|:  media {sum(difs) / n:.4f}   mediana {difs[n // 2]:.4f}   "
          f"p95 {difs[int(0.95 * n)]:.4f}   max {difs[-1]:.4f}")
    gr = sum(1 for x in difs if x >= 0.02)
    print(f"jogos com diferenca >= 2 pontos percentuais: {gr} ({gr / n:.1%})")
    print(f"logloss da REGUA: {_ll(regua, ys):.5f}   |   do SERVIDO: {_ll(servido, ys):.5f}\n")

    # ---------------------------------------------------------------- 2
    print("=== 2) CADA ETAPA AJUDA? (ablacao POR REMOCAO, calibradores reajustados) ===")
    print(f"{'variante':<32}{'logloss':>10}{'refinam.':>10}{'d logloss':>11}{'d refinam.':>12}")
    base_ll = base_ref = None
    ablacao = []
    for nome, chaves in VARIANTES:
        ps = servido if not chaves else variante(treino, teste, tabela=tabela, **chaves)
        ll, ref = _ll(ps, ys), refinamento(ps, ys)
        if base_ll is None:
            base_ll, base_ref = ll, ref
            print(f"{nome:<32}{ll:>10.5f}{ref:>10.5f}{'':>11}{'':>12}")
        else:
            print(f"{nome:<32}{ll:>10.5f}{ref:>10.5f}{ll - base_ll:>+11.5f}{ref - base_ref:>+12.5f}")
        ablacao.append({"variante": nome, "logloss": round(ll, 5),
                        "refinamento": round(ref, 5)})
    print("leitura: 'd' POSITIVO = remover PIOROU, logo a etapa ajuda.")
    print("         'd' NEGATIVO = remover MELHOROU, logo a etapa atrapalha.")
    print("         d logloss positivo com d refinamento ~0 = a etapa so ajeita a")
    print("         regua; podia ser trocada por uma recalibracao final.\n")

    # ---------------------------------------------------------------- 3
    print("=== 3) EM QUE GRUPO O NUMERO MENTE? (Z de Spiegelhalter + Benjamini-Hochberg) ===")
    grupos: dict[str, list[int]] = defaultdict(list)
    for i, a in enumerate(teste):
        p = servido[i]
        grupos[f"liga: {a.league or '?'}"].append(i)
        grupos[f"formato: BO{a.bo or '?'}"].append(i)
        if a.phase:
            grupos[f"fase: {a.phase}"].append(i)
        if a.month:
            grupos[f"mes: {a.month}"].append(i)
        grupos["faixa: " + ("favorito pesado >=80%" if p >= .8 else
                            "favorito 60-80%" if p >= .6 else
                            "parelho 40-60%" if p >= .4 else
                            "azarao 20-40%" if p >= .2 else
                            "azarao pesado <20%")].append(i)

    achados = []
    for nome, idxs in grupos.items():
        if len(idxs) < int(args.min_grupo):
            continue
        ps = [servido[i] for i in idxs]
        yy = [ys[i] for i in idxs]
        z, pv = spiegelhalter_z(ps, yy)
        lo, hi = wilson(sum(yy), len(yy))
        achados.append({"grupo": nome, "n": len(idxs), "z": round(z, 2), "p_valor": pv,
                        "previsto": sum(ps) / len(ps), "aconteceu": sum(yy) / len(yy),
                        "ic_lo": lo, "ic_hi": hi})
    marcados = benjamini_hochberg([a["p_valor"] for a in achados], alpha=float(args.alpha))
    for a, m in zip(achados, marcados):
        a["mente"] = bool(m)
    achados.sort(key=lambda a: a["p_valor"])

    print(f"{'grupo':<34}{'n':>6}{'previsto':>10}{'aconteceu':>11}{'IC 95%':>19}{'Z':>7}{'p':>8}")
    for a in achados[:20]:
        marca = "  <-- MENTE" if a["mente"] else ""
        print(f"{a['grupo'][:33]:<34}{a['n']:>6}{a['previsto']:>10.1%}{a['aconteceu']:>11.1%}"
              f"   [{a['ic_lo']:>5.1%},{a['ic_hi']:>6.1%}]{a['z']:>7.2f}{a['p_valor']:>8.4f}{marca}")
    ruins = [a for a in achados if a["mente"]]
    print(f"\ngrupos testados: {len(achados)} | com desvio real (apos Benjamini-Hochberg): "
          f"{len(ruins)}")
    if not ruins:
        print("nenhum grupo mente de forma detectavel — o numero servido e honesto")
        print("onde da pra testar. Grupo pequeno tem IC largo: ausencia de deteccao")
        print("nao e prova de honestidade, e falta de poder.")

    destino = ROOT / str(args.out)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({
        "n_teste": n, "divergencia_media": round(sum(difs) / n, 5),
        "logloss_regua": round(_ll(regua, ys), 5),
        "logloss_servido": round(_ll(servido, ys), 5),
        "ablacao": ablacao,
        "grupos": [{k: (round(v, 4) if isinstance(v, float) else v)
                    for k, v in a.items()} for a in achados],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[salvo] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
