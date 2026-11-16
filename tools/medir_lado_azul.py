# -*- coding: utf-8 -*-
"""O NUMERO DA TELA MUDA CONFORME A ORDEM DOS TIMES. Quanto isso custa?

O ACHADO (16/09/2026). Ele mandou dois prints do MESMO confronto, Natus
Vincere x Movistar KOI, e o numero estava diferente. Ele atribuiu ao CSV novo
que tinha acabado de subir. Medindo, o CSV nao tinha mexido NADA nesse
confronto (0.567 antes, 0.567 depois -- e nenhum dos dois times jogou nos 54
jogos que entraram). O que mudou foi a ORDEM: no primeiro print a NAVI estava
no Time 1; no segundo, o KOI.

POR QUE A ORDEM MUDA O NUMERO
O calibrador do modelo carrega o INTERCEPTO DO LADO AZUL. Medido no artefato:

    p cru 0.50  ->  calibrado 0.5253

e nos dados a vitoria do lado azul e 53,62% em 8.758 mapas. O calibrador esta
CERTO: ele aprendeu uma vantagem que existe. So que o caminho servido passa o
Time 1 como lado azul -- e na tela o "Time 1" e apenas a caixa onde ele
digitou primeiro, nao o lado que o time vai jogar.

Resultado: `cal(p) + cal(1-p) = 1.05` em vez de 1.00, e o mesmo confronto da
ate 5 pontos percentuais de diferenca conforme a ordem. Bem no meio da
tabela, que e onde as decisoes de aposta acontecem.

O PROJETO JA SABIA, E CONSERTOU SO NUM LUGAR
`app_core/live_between_maps_core.py` faz `p_sym = 0.5*(p_fwd + (1 - p_rev))`,
com o comentario "simetrizado (cancela o intercepto de lado azul do
calibrador)". O caminho principal, que e o que ele usa, nao faz.

POR QUE ESTA MEDICAO E DESENHADA ASSIM
A medicao obvia -- rodar contra o historico, onde se SABE quem jogou de azul
-- responde a pergunta errada, e responde a favor do que ja existe: o lado
azul vence mais, entao premiar o lado azul acerta. Essa medicao diria "nao
mexa", e estaria certa sobre uma situacao que nao e a dele.

A situacao DELE e outra: a ordem em que digita nao tem relacao com o lado.
Entao aqui cada confronto e avaliado NAS DUAS ORDENS e a perda e a media --
que e a perda esperada quando a ordem e arbitraria. Sem Monte Carlo: as duas
ordens sao enumeradas, o resultado e deterministico.

Tres numeros saem:
  1. SE ELE SOUBESSE O LADO   -- o melhor caso da versao atual (limite superior)
  2. ORDEM ARBITRARIA, HOJE   -- o que ele tem de verdade
  3. ORDEM ARBITRARIA, SIMETRIZADO -- a proposta

PRINCIPIO V: nada aqui reimplementa o caminho servido. Usa-se
`mlcore.replay_pre_jogo`, que existe justamente para a medicao parar de
reescrever o pipeline.

Uso: python tools/medir_lado_azul.py [--conjunto teste]
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import replace
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mlcore.replay_pre_jogo import Amostra, carregar, variante  # noqa: E402
from mlcore.utils import clip_prob  # noqa: E402

RANDOM_LOGLOSS = math.log(2.0)


def _inverter(a: Amostra) -> Amostra:
    """A MESMA partida vista do outro lado.

    Tudo que tem lado troca: a probabilidade do time, a dos jogadores, o
    resultado, a diferenca de escalacao e o proprio campo `side` -- que o
    microssegmento le. Esquecer o `side` faria a etapa de microssegmento
    corrigir a amostra invertida como se ela ainda fosse azul, e a medicao
    mediria uma mistura sem nome.
    """
    return replace(
        a,
        y=1 - int(a.y),
        p_team=1.0 - float(a.p_team),
        p_players=1.0 - float(a.p_players),
        delta_eff=-float(a.delta_eff),
        side=("red" if str(a.side).lower() == "blue" else "blue"),
    )


def _perda(p: float, y: int) -> float:
    q = float(clip_prob(float(p)))
    return -(math.log(q) if int(y) == 1 else math.log(1.0 - q))


def _logloss(ps, ys) -> float:
    total = 0.0
    for p, y in zip(ps, ys):
        q = float(clip_prob(float(p)))
        total += -(math.log(q) if int(y) == 1 else math.log(1.0 - q))
    return total / max(len(ys), 1)


def _nota(ll: float) -> float:
    """A MESMA formula do scorecard oficial: aleatorio=5.0, elite=9.5."""
    lo, hi = 0.55, RANDOM_LOGLOSS
    return max(0.0, min(10.0, 5.0 + (hi - ll) / (hi - lo) * 4.5))


def main() -> int:
    ap = argparse.ArgumentParser(description="Custo do intercepto de lado azul.")
    ap.add_argument("--conjunto", default="teste", choices=("teste", "val"))
    args = ap.parse_args()

    d = carregar()
    treino = list(d["treino"])
    alvo = list(d[args.conjunto])
    tabela = d["tabela"]
    if not alvo:
        print("[lado] conjunto vazio.")
        return 1

    alvo_inv = [_inverter(a) for a in alvo]
    ys = [int(a.y) for a in alvo]

    # O caminho servido, com os defaults de PRODUCAO, nas duas ordens. O
    # calibrador e ajustado no treino uma vez so -- e o que producao faz.
    p_fwd = variante(treino, alvo, tabela=tabela)
    p_rev = variante(treino, alvo_inv, tabela=tabela)
    p_sym = [0.5 * (f + (1.0 - r)) for f, r in zip(p_fwd, p_rev)]

    # 1) melhor caso de hoje: ele sempre poria o lado azul no Time 1
    ll_sabendo = _logloss(p_fwd, ys)
    # 2) o que ele tem: a ordem nao tem relacao com o lado, entao a perda e a
    #    media das duas ordens
    ll_hoje = 0.5 * (_logloss(p_fwd, ys)
                     + _logloss([1.0 - r for r in p_rev], ys))
    # 3) simetrizado: a ordem deixa de importar, a perda e a mesma nas duas
    ll_sim = _logloss(p_sym, ys)

    print("[lado] conjunto=%s  n=%d" % (args.conjunto, len(alvo)))
    print()
    print("%-42s %9s %7s" % ("cenario", "logloss", "nota"))
    print("%-42s %9.5f %7.2f" % ("1. SE ele soubesse o lado (limite)", ll_sabendo, _nota(ll_sabendo)))
    print("%-42s %9.5f %7.2f" % ("2. ordem arbitraria — HOJE", ll_hoje, _nota(ll_hoje)))
    print("%-42s %9.5f %7.2f" % ("3. ordem arbitraria — SIMETRIZADO", ll_sim, _nota(ll_sim)))
    print()
    ganho = ll_hoje - ll_sim
    print("ganho da simetrizacao: %+.5f de logloss (%+.3f de nota)" % (
        ganho, _nota(ll_sim) - _nota(ll_hoje)))
    print("custo de nao saber o lado: %+.5f (cenario 2 menos cenario 1)" % (
        ll_hoje - ll_sabendo))
    # QUANTO ISSO E SEGURO DE AFIRMAR. Par a par, agrupado por jogo: dois
    # mapas da mesma serie nao sao duas evidencias independentes.
    import random
    perdas_hoje = [0.5 * (_perda(f, y) + _perda(1.0 - r, y))
                   for f, r, y in zip(p_fwd, p_rev, ys)]
    perdas_sim = [_perda(sm, y) for sm, y in zip(p_sym, ys)]
    dif = [h - s for h, s in zip(perdas_hoje, perdas_sim)]
    por_jogo = {}
    for a_, d_ in zip(alvo, dif):
        por_jogo.setdefault(str(a_.gameid), []).append(d_)
    blocos = [sum(v) / len(v) for v in por_jogo.values()]
    rnd = random.Random(20260916)
    amostras_bs = []
    for _ in range(2000):
        s_ = [blocos[rnd.randrange(len(blocos))] for _ in range(len(blocos))]
        amostras_bs.append(sum(s_) / len(s_))
    amostras_bs.sort()
    lo = amostras_bs[int(0.025 * len(amostras_bs))]
    hi = amostras_bs[int(0.975 * len(amostras_bs))]
    print("intervalo 95%% do ganho (por jogo, n=%d): [%+.5f, %+.5f]" % (
        len(blocos), lo, hi))

    # O QUE A MEDIA ESCONDE: o ganho medio e pequeno porque os erros das duas
    # ordens se cancelam NO AGREGADO. Em UMA aposta eles nao se cancelam --
    # ou o bonus foi para o time certo, ou para o errado.
    espalha = sorted(abs(f - (1.0 - r)) for f, r in zip(p_fwd, p_rev))
    meio = espalha[len(espalha) // 2]
    p90 = espalha[int(0.90 * len(espalha))]
    print("diferenca entre as duas ordens, POR CONFRONTO: mediana %.1f pontos, "
          "9 em 10 abaixo de %.1f" % (100 * meio, 100 * p90))

    print()
    if ganho > 0:
        print("LEITURA: com a ordem arbitraria, simetrizar ACERTA MAIS.")
    else:
        print("LEITURA: simetrizar NAO ajuda nem com a ordem arbitraria.")
    print("         O cenario 1 continua sendo o melhor -- mas so existe para")
    print("         quem sabe qual time joga de azul, e no BO5 os lados trocam")
    print("         a cada mapa.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
