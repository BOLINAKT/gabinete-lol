# -*- coding: utf-8 -*-
"""Congela a FORMA dos totais num artefato, para o motor usar sem recalcular.

POR QUE CONGELAR, e nao calcular na hora: a forma sai de um replay prequencial
de tres temporadas, que leva ~5 minutos. O app nao pode pagar isso a cada
clique. E o projeto ja faz assim com a calibracao do TEMPO
(`TIME_SD_CALIBRATION = 1.4461`, congelada em 2024+25): constante medida, gate
documentado, avaliacao cega.

O QUE ENTRA NO ARQUIVO: para cada mercado, os quantis do RESIDUO
(total que aconteceu - total previsto), medidos SO em 2024 e 2025. O ano de
2026 fica de fora de proposito -- e nele que o gate avalia, as cegas.

O QUE ISSO CONSERTA (medido em 23/09/2026, 39.145 apostas cegas em 2026):

    mercado      Brier hoje   so largura   com a forma    ganho
    torres          0,20438      0,18727      0,18555    +0,0188
    dragoes         0,13183      0,13183      0,11329    +0,0185
    baroes          0,07903      0,07903      0,06772    +0,0113
    inibidores      0,09597      0,09597      0,08716    +0,0088
    tempo           0,22970      0,22812      0,22551    +0,0042
    abates          0,19988      0,19926      0,19989    neutro

A barra do gate e 0,0005. Nos tres Poisson a coluna do meio e IDENTICA a de
hoje porque `prob_over_from_total` nem le o sd deles -- so o formato resolve.

E POR QUE A TENTATIVA DE 2026-07-17 FALHOU. Ela corrigia a largura, mas com
piso: `RHO_MIN, RHO_MAX = 0.75, 1.35` e `rho = min(max(rho, RHO_MIN), ...)`.
Torres precisava de 0,44. O conserto certo estava fora do que o codigo
permitia, e o que sobrou piorou.

Uso: python tools/gerar_forma_dos_totais.py
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

# A MEDICAO PELO CAMINHO SERVIDO (`_expected_totals_dc`), e nao a V0.
#
# Para torres, baroes e inibidores as duas dao o mesmo (esses mercados nao
# passam pelo blend Dixon-Coles -- o Brier saiu identico ate a 5a casa).
# Para dragoes e tempo NAO: o blend muda a media, e a forma tem de ser a dos
# residuos em volta da media que a TELA usa. Gerar da V0 seria medir uma coisa
# e servir outra. Uma fonte so, a servida, serve para todos.
REGISTROS = ROOT / "scratchpad" / "gate_totais_registros_servido.json"
SAIDA = ROOT / "totais_forma_empirica.json"

# Quantis guardados. 201 pontos dao resolucao de 0,5% na probabilidade --
# mais fino que isso e ruido de amostra, mais grosso comeca a degrau.
N_QUANTIS = 201

# So estes anos entram. 2026 fica de fora para o gate poder avaliar as cegas.
ANOS_DE_AJUSTE = (2024, 2025)


def main() -> int:
    import numpy as np

    if not REGISTROS.exists():
        print("[forma] nao achei %s" % REGISTROS)
        print("[forma] rode antes: python tools/eval_totais_forma_empirica.py --servido")
        return 1
    registros = json.loads(REGISTROS.read_text(encoding="utf-8"))
    print("[forma] %d registros lidos" % len(registros))

    fora = {"_gerado_em": "2026-09-23",
            "_caminho": "servido (_expected_totals_dc)",
            "_anos_de_ajuste": list(ANOS_DE_AJUSTE),
            "_o_que_e": ("quantis do residuo (total real - total previsto) por "
                         "mercado; o motor usa isto no lugar da curva normal/Poisson"),
            "mercados": {}}
    qs = np.linspace(0.0, 1.0, N_QUANTIS)
    for metrica in sorted({r["metric"] for r in registros}):
        res = [r["mean"] + r["z"] * r["sd"] - r["mean"]
               for r in registros
               if r["metric"] == metrica and int(r["year"]) in ANOS_DE_AJUSTE
               and r["sd"] == r["sd"]]
        res = [float(x) for x in res if x == x]
        if len(res) < 2000:
            print("[forma] %-12s dados de menos (%d) -- fica de fora"
                  % (metrica, len(res)))
            continue
        pontos = [float(v) for v in np.quantile(np.array(res, dtype=float), qs)]
        fora["mercados"][metrica] = {"n": len(res), "quantis": pontos}
        print("[forma] %-12s %6d jogos | residuo de %+.2f a %+.2f | desvio %.2f"
              % (metrica, len(res), pontos[0], pontos[-1],
                 float(np.std(res, ddof=1))))

    SAIDA.write_text(json.dumps(fora, ensure_ascii=False), encoding="utf-8")
    print()
    print("[forma] gravado em %s (%.0f KB)"
          % (SAIDA.name, SAIDA.stat().st_size / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
