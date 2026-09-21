# -*- coding: utf-8 -*-
"""A REGUA do handicap de abates -- antes de existir preco na tela.

POR QUE ESTE MERCADO (21/09/2026). Medindo a margem e o LIMITE de cada mercado
nas 14.937 leituras ja coletadas da Pinnacle:

    mercado                 linhas   margem   limite
    Placar exato               441   27,31%      100
    Dragoes/baroes/inibid.    ~240    7,2%       100
    Total de abates           3515    8,92%      250
    HANDICAP DE ABATES        3700    8,41%      950   <-
    Handicap de serie          613    7,87%     2000
    Vencedor                  1010    5,30%      500

O limite e a confissao mais honesta da casa: ela sobe onde confia no proprio
preco, e ali ele pode apostar de verdade. Os mercados exoticos (dragao, barao,
inibidor, Elder) tem limite 100 -- acertar neles rende pouco dinheiro. O
handicap de abates tem o segundo maior limite e o maior numero de linhas
coletadas depois do total.

E A CONTA JA ESTA MEIO PRONTA. `mlcore.lines_engine.matchup_expected_totals`
JA calcula os abates esperados de cada time -- e devolve so a soma:

    a = _combine_mean(pA.kills_for, pB.kills_against)
    b = _combine_mean(pB.kills_for, pA.kills_against)
    mean = a + b                       <- so isto sai

DUAS COISAS QUE EU SUPUS E MEDI, E AS DUAS ESTAVAM ERRADAS:

1. "Os dois times matam muito nos jogos sangrentos, entao os abates sao
   positivamente correlacionados." NAO: a correlacao e -0,229 em 29.166
   jogos. Atropelo pesa mais que jogo sangrento. Supor independencia ENCOLHE
   o espalhamento da diferenca em 10% (11,31 contra 12,54 de verdade) -- e
   espalhamento curto demais faz o modelo achar valor onde nao ha.

2. "A diferenca deve ser mais ou menos normal." NAO: a curtose e -1,14, bem
   achatada. Uma normal poria peso demais nas pontas e de menos no meio, que
   e exatamente onde a linha da casa costuma estar.

Por isso a diferenca aqui NAO sai de uma formula bonita: sai da FORMA
EMPIRICA, medida no historico, com media e largura vindas do confronto.

O QUE ESTE ARQUIVO FAZ: mede. Nenhum preco chega a tela antes de a calibracao
sair daqui, fora da amostra e ponto-no-tempo.

Uso: python tools/handicap_de_abates.py
"""
from __future__ import annotations

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

# As linhas que a Pinnacle realmente oferece neste mercado, lidas do
# historico. Medir em linha inventada nao diz nada sobre o dinheiro dele.
LINHAS_TIPICAS = (-7.5, -5.5, -3.5, -1.5, 1.5, 3.5, 5.5, 7.5)

# Esticar a previsao para o tamanho que a regressao pede. Medido: PIORA a
# calibracao (3,2 -> 4,3pp). Fica desligado; a chave existe para refazer o
# teste, nao para ser ligada no escuro.
GANHO_LIGADO = False


def forma_empirica(difs, larguras):
    """A FORMA da diferenca, padronizada, sem supor curva nenhuma.

    Recebe as diferencas observadas e a largura esperada de cada uma; devolve
    os valores padronizados ordenados, que servem de "regua de formato".
    Consultar essa lista e mais honesto que uma normal quando a curtose e
    -1,14.
    """
    z = []
    for d, s in zip(difs, larguras):
        if s and s > 0 and d == d:
            z.append(float(d) / float(s))
    z.sort()
    return z


def prob_acima(linha, media, largura, forma):
    """P(diferenca > linha), pela forma empirica.

    Sem a forma (lista vazia) devolve None em vez de cair na normal: uma
    aproximacao silenciosa aqui viraria preco na tela.
    """
    if not forma or not largura or largura <= 0:
        return None
    z = (float(linha) - float(media)) / float(largura)
    import bisect
    i = bisect.bisect_right(forma, z)
    return 1.0 - (i / len(forma))


def main() -> int:
    import numpy as np
    import pandas as pd

    from mlcore.stats_teams import build_team_games, load_team_rows
    from tools.nota_honesta import default_csvs

    tg = pd.concat([build_team_games(load_team_rows(str(c))) for c in default_csvs()],
                   ignore_index=True)
    tg["date"] = pd.to_datetime(tg["date"], errors="coerce")
    tg = tg.dropna(subset=["date"])
    # UMA LINHA POR JOGO, com desempate estavel -- percorrer linha a linha ja
    # me custou um vazamento do futuro em 21/09/2026.
    jogos = tg[tg["side"].astype(str).str.lower() == "blue"].copy()
    jogos = jogos.sort_values(["date", "gameid"], kind="mergesort")
    jogos["a"] = pd.to_numeric(jogos["kills_for"], errors="coerce")
    jogos["c"] = pd.to_numeric(jogos["kills_against"], errors="coerce")
    jogos = jogos.dropna(subset=["a", "c"])
    print("[handicap] %d jogos com abates dos dois lados" % len(jogos))

    # --- expectativa PONTO-NO-TEMPO de cada time, sem olhar o proprio jogo ---
    # Media movel simples dos ultimos N jogos: e o mesmo espirito do
    # TeamProfile de producao, mas aqui precisa rodar 29 mil vezes, e o
    # build_profile refaz o filtro inteiro a cada chamada.
    JANELA = 20
    feitos = {}      # time -> [(abates feitos, abates sofridos)]
    linhas = []
    for r in jogos.itertuples(index=False):
        azul, verm = str(r.team), str(r.opponent)
        ha, hb = feitos.get(azul) or [], feitos.get(verm) or []
        if len(ha) >= 8 and len(hb) >= 8:
            ua, ub = ha[-JANELA:], hb[-JANELA:]
            # a mesma mistura do lines_engine: o que A faz e o que B sofre
            ea = (sum(x for x, _ in ua) / len(ua) + sum(y for _, y in ub) / len(ub)) / 2
            eb = (sum(x for x, _ in ub) / len(ub) + sum(y for _, y in ua) / len(ua)) / 2
            linhas.append({"date": r.date, "media": ea - eb, "total": ea + eb,
                           "dif": float(r.a) - float(r.c)})
        feitos.setdefault(azul, []).append((float(r.a), float(r.c)))
        feitos.setdefault(verm, []).append((float(r.c), float(r.a)))

    print("[handicap] %d jogos com historico suficiente dos dois times" % len(linhas))
    if len(linhas) < 2000:
        print("[handicap] pouco dado para medir.")
        return 1

    corte = len(linhas) // 2
    treino, teste = linhas[:corte], linhas[corte:]
    print("[handicap] ajuste ate %s | medicao em %d jogos depois disso"
          % (str(treino[-1]["date"])[:10], len(teste)))

    # --- DUAS CORRECOES QUE A PRIMEIRA MEDICAO EXIGIU ---
    #
    # 1) VIES DO LADO AZUL. O erro medio no teste era +0,755 abates: o azul
    #    mata mais do que a media dos dois times previa. Nao e acaso -- e a
    #    mesma vantagem de lado que o modelo de vencedor ja trata (azul vence
    #    53,6% dos mapas). Ignorar isso jogava TODA a curva para um lado.
    #
    # 2) A LARGURA MUDA COM O TEMPO. Medido por ano: desvio 10,90 em 2024,
    #    12,43 em 2025, 12,05 em 2026. Ajustar uma reta na metade antiga e
    #    usar na metade nova subestimava a largura em 8,5%, e largura curta
    #    faz o modelo achar valor onde nao ha.
    #
    # Os dois saem de uma JANELA RECENTE que anda junto com o jogo, sempre de
    # partidas ANTERIORES a ele. Numero fixo aqui envelhece calado.
    JANELA_AJUSTE = 3000

    def _ajustar(amostra):
        """(ganho, vies do azul, largura(total)) a partir de jogos anteriores.

        O GANHO corrigiu a terceira suposicao errada. Eu esperava que a media
        movel de 20 jogos EXAGERASSE a diferenca entre os times (regressao a
        media). Medido: o contrario. A diferenca real e 1,29 vez a prevista --
        a previsao e TIMIDA, nao exagerada. Ela encolhe porque cada time e
        medido contra adversarios diferentes, e a media de 20 jogos mistura
        oponente facil com dificil.

        Previsao timida faz o modelo concordar com a casa em tudo e nunca
        achar nada. Previsao exagerada faz o contrario. As duas erram; so
        medir diz qual e.
        """
        prev = np.array([t["media"] for t in amostra], dtype=float)
        real = np.array([t["dif"] for t in amostra], dtype=float)
        if float(np.std(prev)) > 1e-9:
            ganho = float(np.polyfit(prev, real, 1)[0])
        else:
            ganho = 1.0
        # MEDIDO E REPROVADO (21/09/2026). A regressao dizia que a previsao
        # era timida por 1,29, entao amplifica-la deveria ajudar. Aplicado, o
        # erro de calibracao PIOROU de 3,2 para 4,3 pontos percentuais.
        #
        # As duas medicoes nao se contradizem: a inclinacao fala do jogo
        # individual, a calibracao fala da media sobre todos. Esticar a media
        # melhora uma e estraga a outra. Como o que ele aposta e a linha, e a
        # linha vive da calibracao, o ganho fica DESLIGADO.
        #
        # `GANHO_LIGADO = True` refaz o experimento sem reescrever nada.
        ganho = max(0.5, min(2.5, ganho)) if GANHO_LIGADO else 1.0
        vies = float(np.mean([t["dif"] - ganho * t["media"] for t in amostra]))
        resto = np.array([t["dif"] - ganho * t["media"] - vies for t in amostra],
                         dtype=float)
        tot = np.array([t["total"] for t in amostra], dtype=float)
        # A LARGURA SAI DO DESVIO DIRETO, por faixa de total esperado.
        #
        # A primeira versao ajustava uma reta no |erro| e multiplicava por um
        # fator para virar desvio. Esse fator so vale para uma FORMA de
        # distribuicao -- e a forma aqui tem curtose -1,14, nem perto de
        # normal. O resultado era largura curta demais e o modelo achando
        # valor onde nao havia. Desvio medido direto nao depende de forma
        # nenhuma.
        faixas = np.quantile(tot, [0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
        pontos = []
        for i in range(len(faixas) - 1):
            m = (tot >= faixas[i]) & (tot <= faixas[i + 1] if i == len(faixas) - 2
                                      else tot < faixas[i + 1])
            if int(m.sum()) >= 100:
                pontos.append((float(np.mean(tot[m])), float(np.std(resto[m]))))
        if len(pontos) >= 2:
            inc, base = np.polyfit([x for x, _ in pontos], [y for _, y in pontos], 1)
        else:
            inc, base = 0.0, float(np.std(resto))
        return ganho, vies, (lambda x: max(1.0, inc * float(x) + base))

    ganho_tr, vies_tr, largura_tr = _ajustar(treino[-JANELA_AJUSTE:])
    print("[handicap] ganho da previsao: %.2f | vies do lado azul: %+.2f abates"
          % (ganho_tr, vies_tr))

    # Para cada jogo do teste, vies/largura/forma vem dos JOGOS ANTERIORES a
    # ele -- refeitos a cada bloco, que e o que a producao poderia fazer.
    PASSO = 1000
    previsto = {}
    for ini in range(0, len(teste), PASSO):
        passado = (treino + teste[:ini])[-JANELA_AJUSTE:]
        g, v, larg = _ajustar(passado)
        fm = forma_empirica([t["dif"] - g * t["media"] - v for t in passado],
                            [larg(t["total"]) for t in passado])
        for k, t in enumerate(teste[ini:ini + PASSO]):
            previsto[ini + k] = (g * t["media"] + v, larg(t["total"]), fm)

    print()
    print("ESTA CALIBRADO? (o que o modelo diz x o que aconteceu, fora da amostra)")
    print("%-8s %8s %12s %12s %9s" % ("linha", "jogos", "modelo diz", "aconteceu", "erro"))
    pior = 0.0
    for L in LINHAS_TIPICAS:
        ps, ys = [], []
        for i, t in enumerate(teste):
            m, larg, fm = previsto[i]
            p = prob_acima(L, m, larg, fm)
            if p is None:
                continue
            ps.append(p)
            ys.append(1.0 if t["dif"] > L else 0.0)
        if len(ps) < 200:
            continue
        pm, real = float(np.mean(ps)), float(np.mean(ys))
        pior = max(pior, abs(pm - real))
        print("%-8.1f %8d %11.1f%% %11.1f%% %+8.1fpp"
              % (L, len(ps), 100 * pm, 100 * real, 100 * (pm - real)))

    print()
    print("maior erro de calibracao: %.1f pontos percentuais" % (100 * pior))
    print("(acima de ~2pp a margem da casa, de 8,41%%, come qualquer vantagem)")

    # A comparacao que fecha a conta: a forma empirica ganha da normal?
    from statistics import NormalDist
    nd = NormalDist()
    print()
    print("A FORMA EMPIRICA VALE A PENA? (mesma medicao, supondo normal)")
    print("%-8s %12s %12s" % ("linha", "erro empirica", "erro normal"))
    for L in LINHAS_TIPICAS:
        pe, pn, ys = [], [], []
        for i, t in enumerate(teste):
            m, larg, fm = previsto[i]
            p1 = prob_acima(L, m, larg, fm)
            if p1 is None:
                continue
            pe.append(p1)
            pn.append(1.0 - nd.cdf((float(L) - m) / larg))
            ys.append(1.0 if t["dif"] > L else 0.0)
        if len(ys) < 200:
            continue
        real = float(np.mean(ys))
        print("%-8.1f %+11.1fpp %+11.1fpp"
              % (L, 100 * (float(np.mean(pe)) - real),
                 100 * (float(np.mean(pn)) - real)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
