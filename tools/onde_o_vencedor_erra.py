# -*- coding: utf-8 -*-
"""O modelo de VENCEDOR erra para que lado? A conta que responde.

O PEDIDO (16/09/2026). Ele mandou dois prints em dois dias e disse: "ainda
sim esta muito divergente da realidade".

    NAVI x Movistar KOI: modelo 56% para a NAVI, mercado 33%
    FlyQuest x Team Liquid: modelo 41,7% para o FlyQuest, mercado 21,7%

MINHA HIPOTESE ERA QUE O MODELO FOSSE SUBCONFIANTE -- que empurrasse tudo na
direcao de 50% e nunca se comprometesse. Nos dois casos ele deu probabilidade
alta demais para o azarao, e isso parecia a assinatura.

O DADO DERRUBOU A HIPOTESE, e de um jeito util. Medido fora da amostra em
7.359 jogos, o modelo e o CONTRARIO: extremo DEMAIS.

    faixa       o modelo   aconteceu
    0-30%          18,3%       29,4%     <- duro demais com azarao
    45-50%         47,5%       54,2%
    70-100%        82,2%       76,2%     <- generoso demais com favorito

E a melhor recalibracao possivel tem T=1,60: ela ENCOLHE na direcao de 50%.
Ou seja, o ajuste que ajuda na media deixaria o caso dele (Liquid) AINDA MAIS
longe do mercado, nao mais perto.

Na media o modelo e extremo demais; naquele confronto ele nao foi extremo o
bastante. Isso nao e erro de escala -- e RUIDO: ele se compromete nos lugares
errados.

QUANTO VALE CADA COISA (medido, com o ajuste otimizado nos proprios dados, o
que e generoso de proposito -- se nem o teto compensar, a conversa acabou):

    logloss hoje ......................... 0,64642
    com a melhor recalibracao possivel ... 0,63043
    moeda ao ar .......................... 0,69315
    elite ................................ 0,55

    erro de ESCALA (recalibravel) ........ 0,016
    erro de ORDEM (o que sobra) .......... 0,080   <- cinco vezes maior

Recalibrar ajuda um pouco. O grosso e o modelo nao enxergar quem e melhor --
e isso pede SINAL NOVO, nao ajuste de escala. Nenhuma recalibracao muda a
ordem: ela e monotona por construcao.

E ha evidencia independente de que o problema e real, nao impressao de dois
jogos:
  - nota honesta (producao): 5,69 -- moeda ao ar e 5,0;
  - picks tracker, mercado ML: -2,89% de ROI em 884 apostas, enquanto kills
    da +8,96% e torres +9,89%. So o vencedor da prejuizo.

COMO A CONTA E FEITA, E POR QUE ASSIM
As previsoes vem de `tools/nota_honesta.py` -- origem rolante, um modelo
treinado por dobra, TODOS os jogos pontuados fora da amostra. Usar a regua
comum aqui seria pior que inutil: ela pontua jogos que estavam no treino
(84,9% deles), e um modelo que decorou o gabarito parece bem calibrado.

Depois as previsoes sao agrupadas por FAIXA e comparado o que o modelo disse
com o que aconteceu. Se em toda faixa acima de 50% a realidade for MAIOR que
a previsao (e abaixo de 50%, menor), o modelo e subconfiante -- e isso tem
conserto conhecido e medivel.

PRINCIPIO V: nada aqui reimplementa o caminho. Le-se o que a regua honesta
gravou.

Uso: python tools/onde_o_vencedor_erra.py [--arquivo <json da nota honesta>]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
PADRAO = ROOT / "scratchpad" / "nota_honesta" / "nota_honesta_prod_diaria.json"

# Faixas de probabilidade. Mais finas perto de 50%, que e onde as apostas
# dele vivem e onde 5 pontos de erro mudam a decisao.
FAIXAS = [(0.0, 0.30), (0.30, 0.40), (0.40, 0.45), (0.45, 0.50),
          (0.50, 0.55), (0.55, 0.60), (0.60, 0.70), (0.70, 1.01)]


def _carregar(caminho: Path) -> list:
    d = json.loads(Path(caminho).read_text(encoding="utf-8"))
    pares = []
    for item in (d.get("por_jogo") or []):
        try:
            p = float(item[1])
            y = int(item[2])
        except (TypeError, ValueError, IndexError):
            continue
        if 0.0 < p < 1.0 and y in (0, 1):
            pares.append((p, y))
    return pares


def _wilson(k: int, n: int) -> tuple:
    """Intervalo de 95% para uma proporcao. Sem ele, uma faixa com 30 jogos
    'provaria' qualquer coisa."""
    if n <= 0:
        return (float("nan"), float("nan"))
    z = 1.959963985
    p = k / n
    den = 1.0 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    meio = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centro - meio), min(1.0, centro + meio))


def _logit(p: float) -> float:
    p = min(max(float(p), 1e-6), 1 - 1e-6)
    return math.log(p / (1.0 - p))


def _sig(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def _ll(pares) -> float:
    t = 0.0
    for p, y in pares:
        q = min(max(float(p), 1e-6), 1 - 1e-6)
        t += -(math.log(q) if y == 1 else math.log(1.0 - q))
    return t / max(len(pares), 1)


def quanto_e_ESCALA_e_quanto_e_ORDEM(pares) -> None:
    """Separa "erra o tamanho" de "erra quem e melhor".

    ESCALA se conserta esticando ou encolhendo a probabilidade -- e barato,
    conhecido e reversivel. ORDEM nao: se o modelo poe o time errado na
    frente, nenhuma recalibracao salva, porque recalibrar preserva a ordem.

    A conta: acha o melhor `T` (temperatura) e o melhor deslocamento `b`
    aplicados no logito. O que sobrar de perda DEPOIS disso e o erro que nao
    e de escala. Ajustado NOS MESMOS dados de proposito -- e o TETO do que
    recalibrar poderia dar; se nem o teto compensar, a conversa acabou.
    """
    base = _ll(pares)
    melhor = (base, 1.0, 0.0)
    T = 0.5
    while T <= 3.01:
        b = -1.0
        while b <= 1.001:
            cand = _ll([(_sig(_logit(p) / T + b), y) for p, y in pares])
            if cand < melhor[0]:
                melhor = (cand, T, b)
            b += 0.05
        T += 0.05

    ll_otimo, t_otimo, b_otimo = melhor
    aleatorio = math.log(2.0)
    print()
    print("QUANTO E ESCALA, QUANTO E ORDEM")
    print("   logloss como esta hoje ............ %.5f" % base)
    print("   logloss com a MELHOR recalibracao . %.5f  (T=%.2f, deslocamento=%+.2f)"
          % (ll_otimo, t_otimo, b_otimo))
    print("   logloss de moeda ao ar ............ %.5f" % aleatorio)
    print()
    ganho = base - ll_otimo
    sobra = ll_otimo - 0.55          # 0.55 = "elite" na escala do projeto
    print("   recalibrar ganharia no MAXIMO ..... %.5f de logloss" % ganho)
    print("   e AINDA sobrariam ................. %.5f ate o nivel elite" % sobra)
    print()
    if ganho <= 0.005:
        print("LEITURA: recalibrar nao resolve. O erro nao e de tamanho da")
        print("         probabilidade -- e de ORDEM: o modelo nao ve quem e")
        print("         melhor. Isso pede sinal novo, nao ajuste de escala.")
    else:
        print("LEITURA: ha ganho real em recalibrar, e ele e medivel. Mas veja")
        print("         o quanto SOBRA depois: o grosso do erro continua sendo")
        print("         de ordem, nao de escala.")
    if t_otimo > 1.05:
        print("         T>1 confirma o que a tabela mostrou: o modelo e EXTREMO")
        print("         DEMAIS, e o melhor ajuste o encolhe na direcao de 50%%.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Onde o modelo de vencedor erra.")
    ap.add_argument("--arquivo", default=str(PADRAO))
    args = ap.parse_args()

    alvo = Path(args.arquivo)
    if not alvo.exists():
        print("[erra] nao achei %s" % alvo)
        print("       rode antes: python tools/nota_honesta.py --cadencia diaria")
        return 1

    pares = _carregar(alvo)
    if not pares:
        print("[erra] o arquivo nao tem previsoes jogo a jogo (`por_jogo`).")
        return 1

    print("[erra] fonte: %s" % alvo.name)
    print("[erra] %d jogos, TODOS pontuados fora da amostra" % len(pares))
    print()
    print("%-14s %6s %10s %10s %14s %s" % (
        "faixa", "n", "o modelo", "aconteceu", "diferenca", "intervalo 95%"))

    subconf_alto = subconf_baixo = 0
    for lo, hi in FAIXAS:
        bloco = [(p, y) for p, y in pares if lo <= p < hi]
        if len(bloco) < 30:
            continue
        n = len(bloco)
        prev = sum(p for p, _ in bloco) / n
        real = sum(y for _, y in bloco) / n
        ci = _wilson(sum(y for _, y in bloco), n)
        dif = real - prev
        # Subconfiante = acima de 50% a realidade e MAIOR que a previsao;
        # abaixo de 50%, MENOR. O sinal do erro acompanha o lado da faixa.
        if prev >= 0.5 and ci[0] > prev:
            subconf_alto += 1
        if prev < 0.5 and ci[1] < prev:
            subconf_baixo += 1
        marca = ""
        if (prev >= 0.5 and ci[0] > prev) or (prev < 0.5 and ci[1] < prev):
            marca = "  <-- fora do intervalo"
        print("%-14s %6d %9.1f%% %9.1f%% %+13.1f pp  [%.1f%%, %.1f%%]%s" % (
            "%.0f-%.0f%%" % (100 * lo, 100 * min(hi, 1.0)), n,
            100 * prev, 100 * real, 100 * dif, 100 * ci[0], 100 * ci[1], marca))

    print()
    faixas_fora = subconf_alto + subconf_baixo
    if faixas_fora >= 2:
        print("LEITURA: o modelo e SUBCONFIANTE -- ele encolhe tudo na direcao")
        print("         de 50%% e nao se compromete. %d faixas erram para o lado" % faixas_fora)
        print("         do encolhimento, com o intervalo de 95%% inteiro fora da")
        print("         previsao. Isso tem conserto conhecido (recalibrar), e o")
        print("         conserto e medivel na mesma regua.")
    else:
        print("LEITURA: nao ha subconfianca. Se as faixas baixas apontarem para")
        print("         CIMA e as altas para BAIXO, e o contrario -- o modelo e")
        print("         extremo demais. A conta abaixo diz quanto disso se")
        print("         conserta recalibrando e quanto nao se conserta.")
    quanto_e_ESCALA_e_quanto_e_ORDEM(pares)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


if __name__ == "__main__":
    raise SystemExit(main())
