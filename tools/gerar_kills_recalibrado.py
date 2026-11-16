# -*- coding: utf-8 -*-
"""O reajuste do TOTAL DE KILLS, refeito toda semana com os ultimos 60 dias.

O QUE A MEDICAO ACHOU (25/09/2026, tools/kills_total_com_vitoria.py). Ao
testar a chance de vitoria no total de kills (nao ajudou: +0,00008, dentro do
erro), apareceu outra coisa: a conta que a tela serve (media V0+Dixon-Coles,
curva normal) esta DESCALIBRADA -- onde diz 40%, acontece 37%. Reajustar a
media (reta) e usar a forma real do erro melhora o acerto.

MAS O NIVEL DE KILLS ANDA. Ajustado uma vez em 2024-2025, o mesmo tipo de
conserto PIOROU (gate de 23/09: -0,0016). Ajustado no 1o semestre de 2026, ele
melhora o 2o semestre mas desalinha 2-3 pontos para o outro lado. Por isso:
refeito TODA SEMANA com uma janela movel.

A JANELA, escolhida ANTES da prova cega (01/05-23/06/2026, refeito
semanalmente): 60 dias (+0,0052) > 90 (+0,0050) > 120 (+0,0050).
PROVA CEGA (23/06-21/09/2026, 2.813 jogos, refeito toda semana com 60 dias):
    Brier 0,23236 (no ar) -> 0,22940   ganho +0,0030  IC95 [+0,0006, +0,0054]
    calibracao condicional 1,69 pp (a conta no ar: 2,19 pp)

O QUE ESTE PROGRAMA GRAVA: `kills_recalibrado.json` na raiz -- a reta
(total real ~ a + b x media servida) e os quantis do erro, com a data. O
motor (mlcore/lines_engine) so usa se tiver ate 21 dias; mais velho que isso
volta a curva de sempre, porque ajuste velho e exatamente o que falhou.

Uso: python tools/gerar_kills_recalibrado.py [--janela 60]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

JANELA_DIAS = 60
MINIMO_DE_JOGOS = 500
ALVO = ROOT / "kills_recalibrado.json"


def main() -> int:
    import pandas as pd

    from mlcore.stats_teams import build_team_games, load_team_rows
    from tools.eval_totais_forma_empirica import _coletar_servido
    from tools.kills_total_com_vitoria import ajustar
    from tools.nota_honesta import default_csvs

    ap = argparse.ArgumentParser()
    ap.add_argument("--janela", type=int, default=JANELA_DIAS)
    args = ap.parse_args()

    tg = pd.concat([build_team_games(load_team_rows(str(c))) for c in default_csvs()],
                   ignore_index=True)
    tg["date"] = pd.to_datetime(tg["date"], errors="coerce")
    tg = tg.dropna(subset=["date"])
    ate = tg["date"].max().normalize()
    desde = ate - pd.Timedelta(days=int(args.janela))
    regs = []
    for ano in sorted({desde.year, ate.year}):
        regs += [r for r in _coletar_servido(tg, ano, desde=desde) if r["metric"] == "kills"]
    print("[kills-recal] %d jogos entre %s e %s" % (len(regs), desde.date(), ate.date()))
    if len(regs) < MINIMO_DE_JOGOS:
        print("[kills-recal] jogos de menos (minimo %d). Nada gravado; o motor segue"
              " com a curva de sempre." % MINIMO_DE_JOGOS)
        return 1
    art = ajustar([dict(r, m=0.0) for r in regs], com_p=False)
    saida = {
        "coef": art["coef"], "quantis": art["quantis"],
        "janela_dias": int(args.janela), "jogos": len(regs),
        "dados_ate": str(ate.date()), "gerado_em": date.today().isoformat(),
        "_o_que_e": ("total real de kills ~ coef[0] + coef[1] x media servida, e os "
                     "quantis do erro; mlcore/lines_engine usa se tiver ate 21 dias"),
    }
    ALVO.write_text(json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[kills-recal] gravado: total ~ %.2f + %.3f x media | %s"
          % (art["coef"][0], art["coef"][1], ALVO.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
