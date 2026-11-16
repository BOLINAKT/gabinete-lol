# -*- coding: utf-8 -*-
"""O espalhamento dos totais esta certo? (abates, torres, dragoes, baroes)

O ACHADO (23/09/2026). `mlcore/lines_engine.matchup_expected_totals` soma as
variacoes dos dois times COMO SE FOSSEM INDEPENDENTES:

    sd_total = sqrt(sd_A^2 + sd_B^2)

Eles nao sao independentes. Quando um time atropela, ele derruba muitas torres
e o outro quase nenhuma. Medido em 29.178 jogos:

    mercado    correlacao   sd pela formula   sd real   exagero
    torres        -0,822          5,12          2,17     +137%
    dragoes       -0,670          1,93          1,11      +74%
    baroes        -0,479          1,01          0,73      +39%
    abates        -0,229         11,31          9,93      +14%

Num confronto real (T1 x Gen.G) o motor devolve sd=4,74 para torres. O desvio
REAL e 2,17 -- ou seja, o modelo afirma ser pior do que chutar a media geral.
Isso nao pode estar certo: chutar a media sempre da 2,17.

A CONSEQUENCIA e que toda linha de total fica achatada para perto de 50%. O
modelo enxerga MENOS vantagem do que existe, e quando aponta uma, o tamanho
esta errado.

O TESTE QUE DECIDE, e que este arquivo faz: padronizar o erro do modelo.

    z = (total que aconteceu - total previsto) / desvio previsto

Se o desvio estiver certo, o desvio de z e 1. Menor que 1 = espalhamento
exagerado (o modelo se diz mais incerto do que e). Maior que 1 = o contrario.

Tudo PONTO-NO-TEMPO: o perfil de cada time sai so de jogos anteriores aquele.
E tudo pelo caminho de PRODUCAO -- build_profile + _expected_totals_dc --,
porque medir outra conta responderia sobre outro modelo.

Uso: python tools/espalhamento_dos_totais.py [quantos_jogos]
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MEIA_VIDA = 180.0

# metrica do motor -> coluna do CSV com o total do jogo
COLUNA_DO_TOTAL = {
    "kills": "total_kills",
    "towers": "total_towers",
    "dragons": "total_dragons",
    "barons": "total_nashors",
    "inhibitors": "total_inhibitors",
    "time": "game_time_min",
}


def main() -> int:
    import numpy as np
    import pandas as pd

    from app_core.runtime_wrappers_core import _expected_totals_dc
    from mlcore.lines_engine import Filters, build_profile
    from mlcore.stats_teams import build_team_games, load_team_rows
    from tools.nota_honesta import default_csvs

    quantos = int(sys.argv[1]) if len(sys.argv) > 1 else 600

    tg = pd.concat([build_team_games(load_team_rows(str(c))) for c in default_csvs()],
                   ignore_index=True)
    tg["date"] = pd.to_datetime(tg["date"], errors="coerce")
    tg = tg.dropna(subset=["date"]).sort_values(["date", "gameid"], kind="mergesort")
    jogos = tg[tg["side"].astype(str).str.lower() == "blue"]
    # Os mais RECENTES: e sobre eles que o modelo vai ser usado.
    jogos = jogos.tail(quantos)
    print("[espalhamento] %d jogos, de %s a %s"
          % (len(jogos), str(jogos["date"].min())[:10], str(jogos["date"].max())[:10]))

    filtros = Filters(year=None, league=None, split=None, playoffs=None)
    z = {m: [] for m in COLUNA_DO_TOTAL}
    erros = {m: [] for m in COLUNA_DO_TOTAL}
    reais = {m: [] for m in COLUNA_DO_TOTAL}
    sem = 0

    for r in jogos.itertuples(index=False):
        # PONTO-NO-TEMPO: so o que existia ANTES deste jogo.
        antes = tg[tg["date"] < r.date]
        if len(antes) < 500:
            sem += 1
            continue
        try:
            pa = build_profile(antes, team=str(r.team), filters=filtros,
                               league_mode="all", map_mode="avg",
                               half_life_days=MEIA_VIDA, max_games=None)
            pb = build_profile(antes, team=str(r.opponent), filters=filtros,
                               league_mode="all", map_mode="avg",
                               half_life_days=MEIA_VIDA, max_games=None)
            if not pa.n_games or not pb.n_games:
                sem += 1
                continue
            totais = _expected_totais = _expected_totals_dc(antes, pa, pb)
        except Exception:
            sem += 1
            continue

        for metrica, coluna in COLUNA_DO_TOTAL.items():
            t = totais.get(metrica)
            if t is None:
                continue
            real = getattr(r, coluna, None)
            try:
                real = float(real)
            except (TypeError, ValueError):
                continue
            if real != real or t.mean != t.mean or t.sd != t.sd or t.sd <= 0:
                continue
            z[metrica].append((real - t.mean) / t.sd)
            erros[metrica].append(real - t.mean)
            reais[metrica].append(real)

    print("[espalhamento] %d jogos sem perfil dos dois times" % sem)
    print()
    print("%-12s %7s %10s %12s %12s %s"
          % ("mercado", "jogos", "desvio z", "sd do modelo", "sd do erro", "veredito"))
    for metrica in COLUNA_DO_TOTAL:
        if len(z[metrica]) < 100:
            continue
        zz = np.array(z[metrica], dtype=float)
        er = np.array(erros[metrica], dtype=float)
        sd_z = float(np.std(zz, ddof=1))
        sd_erro = float(np.std(er, ddof=1))
        sd_modelo = sd_erro / max(sd_z, 1e-9)     # o que o modelo dizia, em media
        if sd_z < 0.85:
            v = "ESPALHAMENTO EXAGERADO em %.0f%%" % (100 * (1 / sd_z - 1))
        elif sd_z > 1.15:
            v = "espalhamento curto demais"
        else:
            v = "ok"
        print("%-12s %7d %10.3f %12.2f %12.2f  %s"
              % (metrica, len(zz), sd_z, sd_modelo, sd_erro, v))

    print()
    print("desvio de z = 1 significa que o modelo acerta o proprio espalhamento.")
    print("Menor que 1 = ele se diz mais incerto do que e, e achata toda linha")
    print("para perto de 50%.")
    print()
    print("COMPARACAO: chutar sempre a media geral daria estes desvios --")
    for metrica in COLUNA_DO_TOTAL:
        if len(reais[metrica]) < 100:
            continue
        rr = np.array(reais[metrica], dtype=float)
        print("  %-12s %.2f  (o modelo tem de ficar ABAIXO disto)"
              % (metrica, float(np.std(rr, ddof=1))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
