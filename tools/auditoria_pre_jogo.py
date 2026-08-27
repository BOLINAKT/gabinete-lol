# -*- coding: utf-8 -*-
"""AUDITORIA DO PRÉ-JOGO — o número da tela é honesto, e onde ele mente.

Pergunta dele (26/08/2026): "quero ter certeza que a nota que estou vendo é
confiável — posso não concordar, mas ela tem que fazer sentido como preço."
Traduzido em critério mensurável: quando o modelo diz 70%, tem que acontecer
70% das vezes. E tem que valer NA LIGA em que ele está apostando, não só na
média — o que a literatura chama de multicalibração.

TRÊS PERGUNTAS, TRÊS FERRAMENTAS, TODAS ESCOLHIDAS POR PESQUISA:

  1) A régua oficial mede o que a tela serve?
     Divergência entre `p_regua` (o que ml_fusion_scorecard mede) e `p_servido`
     (o caminho de produção). Se for 0.001, a nota serve; se for 0.05, ela
     descreve outro produto.

  2) Cada etapa do caminho ajuda?
     Ablação com a DECOMPOSIÇÃO CALIBRAÇÃO/REFINAMENTO (Berta, Holzmüller,
     Jordan & Bach, 2025). Refinamento = a logloss DEPOIS de recalibrar, ou
     seja, o que sobra de informação de verdade. Etapa que melhora refinamento
     adiciona informação; etapa que só melhora calibração poderia ser
     substituída por uma recalibração final; etapa que PIORA refinamento
     destrói informação.
     SUSPEITO PRINCIPAL: o microssegmento. Ele é uma multicalibração caseira,
     e a literatura diz que impor calibração por grupo custa muito mais dado
     (erro^-3 contra erro^-2) e que o mecanismo estima médias em células com
     poucos pontos. É o mesmo regime em que o calibrador do ao vivo perdeu em
     15 de 15 hoje.

  3) Em que grupo o número mente?
     Z DE SPIEGELHALTER por grupo — teste não-paramétrico, SEM binning e sem
     parâmetro para escolher errado. Sob a hipótese de que o grupo está
     calibrado, Z ~ Normal(0,1); |Z| grande = o número daquele grupo mente de
     forma sistemática. Escolhido no lugar do ECE justamente porque ECE é
     estimador enviesado e sensível ao número de caixas.

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
from mlcore.replay_pre_jogo import carregar  # noqa: E402

EPS = 1e-12

# As etapas na ordem em que o app as aplica. O nome e o campo do Etapas.
ETAPAS = [
    ("nucleo WHR (cru)", "p_elo"),
    ("o que a REGUA mede", "p_regua"),
    ("+ microssegmento", "p_time_ms"),
    ("+ Platt do time", "p_time_cal"),
    ("+ fusao por precisao", "p_fundido"),
    ("+ microssegmento (2a vez)", "p_fundido_ms"),
    ("+ Platt da fusao = SERVIDO", "p_servido"),
]


def _ll(ps, ys) -> float:
    return sum(-(math.log(min(max(p, EPS), 1 - EPS)) if y == 1
                 else math.log(1 - min(max(p, EPS), 1 - EPS)))
               for p, y in zip(ps, ys)) / max(1, len(ys))


def refinamento(ps, ys) -> float:
    """Logloss DEPOIS de recalibrar de forma otima — o que sobra de informacao.

    Usa a familia beta, que contem a identidade: se ja estiver calibrado, a
    recalibracao pode nao fazer nada, e o refinamento coincide com a logloss."""
    cal = fit_beta_from_raw_probs(ys, ps)
    return _ll([cal.predict_proba(p) for p in ps], ys)


def spiegelhalter_z(ps, ys) -> tuple[float, float]:
    """Z de Spiegelhalter e valor-p bicaudal.

    Z = SUM (y-p)(1-2p) / sqrt(SUM (1-2p)^2 p (1-p))
    Sob H0 (o conjunto esta calibrado), Z ~ N(0,1). Sem caixas, sem parametro."""
    num = 0.0
    den = 0.0
    for p, y in zip(ps, ys):
        p = min(max(float(p), 1e-9), 1 - 1e-9)
        num += (y - p) * (1 - 2 * p)
        den += ((1 - 2 * p) ** 2) * p * (1 - p)
    if den <= 0:
        return float("nan"), float("nan")
    z = num / math.sqrt(den)
    pv = math.erfc(abs(z) / math.sqrt(2.0))
    return z, pv


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de Wilson: grupo pequeno mostra intervalo largo em vez de
    fingir precisao. E o que faz a tabela de leitura ser honesta."""
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - r) / d, (c + r) / d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-grupo", type=int, default=60,
                    help="tamanho minimo para um grupo entrar no teste")
    ap.add_argument("--out", default="evidence/auditoria_pre_jogo.json")
    args = ap.parse_args()

    dados = carregar()
    teste = dados["teste"]
    if not teste:
        print("sem amostras de teste — rode com o cache limpo")
        return 1
    ys = [e.y for e in teste]
    n = len(ys)
    print(f"temporada cega: {n} jogos | taxa-base {sum(ys) / n:.3f}\n")

    # ---------------------------------------------------------------- 1
    difs = [abs(e.p_regua - e.p_servido) for e in teste]
    difs_ord = sorted(difs)
    print("=== 1) A REGUA OFICIAL MEDE O QUE A TELA SERVE? ===")
    print(f"diferenca |regua - servido|:  media {sum(difs) / n:.4f}   "
          f"mediana {difs_ord[n // 2]:.4f}   p95 {difs_ord[int(0.95 * n)]:.4f}   "
          f"max {difs_ord[-1]:.4f}")
    grandes = sum(1 for d in difs if d >= 0.02)
    print(f"jogos com diferenca >= 2 pontos percentuais: {grandes} ({grandes / n:.1%})")
    print("leitura: se isso for grande, a nota que o vigia semanal guarda")
    print("         descreve um produto diferente do que aparece na tela.\n")

    # ---------------------------------------------------------------- 2
    print("=== 2) CADA ETAPA AJUDA? (ablacao com calibracao/refinamento) ===")
    print(f"{'etapa':<30}{'logloss':>10}{'refinam.':>10}{'d logloss':>11}{'d refinam.':>12}")
    linhas = []
    ant_ll = ant_ref = None
    for nome, campo in ETAPAS:
        ps = [getattr(e, campo) for e in teste]
        ll, ref = _ll(ps, ys), refinamento(ps, ys)
        d_ll = "" if ant_ll is None else f"{ant_ll - ll:>+11.5f}"
        d_ref = "" if ant_ref is None else f"{ant_ref - ref:>+12.5f}"
        print(f"{nome:<30}{ll:>10.5f}{ref:>10.5f}{d_ll}{d_ref}")
        linhas.append({"etapa": nome, "logloss": round(ll, 5), "refinamento": round(ref, 5)})
        ant_ll, ant_ref = ll, ref
    print("leitura: 'd refinam.' positivo = a etapa ADICIONA informacao.")
    print("         'd logloss' positivo com 'd refinam.' ~0 = a etapa so ajeita")
    print("         a regua, e podia ser trocada por uma recalibracao final.")
    print("         'd refinam.' NEGATIVO = a etapa DESTROI informacao.\n")

    # ---------------------------------------------------------------- 3
    print("=== 3) EM QUE GRUPO O NUMERO MENTE? (Z de Spiegelhalter) ===")
    grupos: dict[str, list] = defaultdict(list)
    for e in teste:
        grupos[f"liga: {e.liga or 'sem liga'}"].append(e)
        p = e.p_servido
        faixa = ("favorito pesado (>=80%)" if p >= 0.8 else
                 "favorito (60-80%)" if p >= 0.6 else
                 "parelho (40-60%)" if p >= 0.4 else
                 "azarao (20-40%)" if p >= 0.2 else "azarao pesado (<20%)")
        grupos[f"faixa: {faixa}"].append(e)

    achados = []
    for nome, itens in grupos.items():
        if len(itens) < int(args.min_grupo):
            continue
        ps = [e.p_servido for e in itens]
        yy = [e.y for e in itens]
        z, pv = spiegelhalter_z(ps, yy)
        lo, hi = wilson(sum(yy), len(yy))
        achados.append({"grupo": nome, "n": len(itens), "z": round(z, 2),
                        "p_valor": round(pv, 4), "previsto": round(sum(ps) / len(ps), 3),
                        "aconteceu": round(sum(yy) / len(yy), 3),
                        "ic_lo": round(lo, 3), "ic_hi": round(hi, 3)})
    achados.sort(key=lambda a: a["p_valor"])
    print(f"{'grupo':<34}{'n':>6}{'previsto':>10}{'aconteceu':>11}"
          f"{'IC 95%':>18}{'Z':>7}{'p':>8}")
    for a in achados[:18]:
        marca = "  <-- MENTE" if a["p_valor"] < 0.05 else ""
        print(f"{a['grupo'][:33]:<34}{a['n']:>6}{a['previsto']:>10.1%}{a['aconteceu']:>11.1%}"
              f"   [{a['ic_lo']:.1%}, {a['ic_hi']:.1%}]{a['z']:>7.2f}{a['p_valor']:>8.4f}{marca}")
    ruins = [a for a in achados if a["p_valor"] < 0.05]
    print(f"\ngrupos testados: {len(achados)} | com desvio significativo: {len(ruins)}")
    print("ATENCAO: testar muitos grupos infla o numero de 'significativos' por")
    print(f"         acaso — com {len(achados)} grupos a 5%, espere ~{0.05 * len(achados):.1f} falsos.")

    destino = ROOT / str(args.out)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({
        "n_teste": n, "divergencia_media": round(sum(difs) / n, 5),
        "etapas": linhas, "grupos": achados}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"[salvo] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
