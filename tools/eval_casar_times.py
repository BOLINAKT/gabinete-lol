# -*- coding: utf-8 -*-
"""Uma regra automatica de casar nomes acertaria os apelidos que ele ensinou?

O QUE ELE DISSE (23/09/2026): "ele ainda nao pega os times de forma
correta, alguns times eu ainda tenho que indicar os nomes".

A REGRA DE HOJE nao adivinha, de proposito: casa so nome exato ou apelido
ensinado. Isso veio de um erro caro -- "UP2U Meavedron" foi casado com
"UP2UMEDIA Cebulaki", time de OUTRA liga, e a analise saiu inteira sobre o
time errado.

A PERGUNTA DESTE ARQUIVO: da para casar sozinho uma parte dos casos SEM
nenhum acerto errado? Deixar para ele decidir e aceitavel. Decidir errado
nao e -- apelido errado sai na tela com toda a confianca, e o faltando pelo
menos aparece como faltando.

O TESTE: os apelidos que ele ja ensinou sao a verdade. Para cada um, finge
que nao foi ensinado e pergunta a regra. Tres desfechos:

    CERTO     -> a regra acharia sozinha o mesmo time que ele escolheu
    ABSTEVE   -> a regra nao decidiria (aceitavel: continua como hoje)
    ERRADO    -> a regra escolheria OUTRO time (inaceitavel)

A liga do confronto e o que desempatou TODOS os casos perigosos na
conferencia de 21/09/2026 (G2 Esports x G2 NORD, Invictus Gaming x Macko
Invictus, paiN Gaming x paiN Academy). Por isso a regra e medida duas vezes:
sem liga, e com a liga do proprio time certo (o melhor caso possivel -- na
tela a liga vem do adversario ja casado).

Uso: python tools/eval_casar_times.py
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# A REGRA MORA EM PRODUCAO (app_core/casar_time_core.py) e e IMPORTADA daqui,
# nao copiada. Uma copia aqui mediria uma regra e a tela serviria outra.
from app_core.casar_time_core import (  # noqa: E402
    DIAS_ATIVO,
    candidatos,
    casar_sozinho,
)


def decidir(cru, times, liga_do_time, liga=None, ligas_do_adversario=None,
            ultimo_jogo=None, hoje=None, dias_max=None):
    """Os cenarios de comparacao. O cenario REAL chama `casar_sozinho` puro."""
    if ligas_do_adversario is not None and dias_max is not None:
        return casar_sozinho(cru, times, liga_do_time, ligas_do_adversario,
                             ultimo_jogo or {}, hoje, dias_ativo=dias_max)
    cands = candidatos(cru, times)
    if liga:
        cands = [c for c in cands if liga in (liga_do_time.get(c) or ())]
    if ligas_do_adversario is not None:
        adv = set(ligas_do_adversario)
        cands = [c for c in cands if adv & set(liga_do_time.get(c) or ())]
    return cands[0] if len(cands) == 1 else None


def main() -> int:
    import pandas as pd

    from mlcore.stats_teams import build_team_games, load_team_rows
    from tools.nota_honesta import default_csvs

    tg = pd.concat([build_team_games(load_team_rows(str(c))) for c in default_csvs()],
                   ignore_index=True)
    tg["date"] = pd.to_datetime(tg["date"], errors="coerce")
    tg = tg.dropna(subset=["date"])
    # So quem jogou no ultimo ano conta: time extinto nao e candidato.
    rec = tg[tg["date"] >= tg["date"].max() - pd.Timedelta(days=365)]
    times = sorted({str(t) for t in rec["team"].dropna().unique()})
    liga_do_time = {}
    for t, lg in zip(rec["team"].astype(str), rec["league"].astype(str)):
        liga_do_time.setdefault(t, set()).add(lg)

    apelidos = json.loads((ROOT / "user_team_aliases.json").read_text(encoding="utf-8"))
    print("[casar] %d apelidos ensinados | %d times ativos no ultimo ano"
          % (len(apelidos), len(times)))

    # O adversario MAIS RECENTE de cada time, tirado do proprio CSV: e o
    # cenario da tela, onde um lado ja casou e o outro esta sendo procurado.
    ultimo_adv = {}
    ultimo_jogo = {}
    for r in rec.sort_values("date").itertuples(index=False):
        ultimo_adv[str(r.team)] = str(r.opponent)
        ultimo_jogo[str(r.team)] = r.date
    hoje = rec["date"].max()

    cenarios = [("SEM liga", False, None), ("COM a liga do confronto", True, None),
                ("COM as ligas do ADVERSARIO (o caso real)", "adv", None)]
    for dm in (DIAS_ATIVO, 90, 120, 180):
        cenarios.append(("ADVERSARIO + so candidato ativo em %d dias" % dm, "adv", dm))
    for rotulo, com_liga, dias_max in cenarios:
        certo, absteve, errado = [], [], []
        for cru, alvo in sorted(apelidos.items()):
            if alvo not in liga_do_time:
                continue        # time que nao jogou no ultimo ano: fora do teste
            liga = None
            ligas_adv = None
            if com_liga == "adv":
                adv = ultimo_adv.get(alvo)
                if not adv:
                    continue
                ligas_adv = liga_do_time.get(adv) or set()
            elif com_liga:
                # O melhor caso: a liga do time certo. Na tela ela vem do
                # adversario ja casado, que joga a mesma liga na maior parte
                # das partidas.
                ligas = sorted(liga_do_time[alvo])
                liga = ligas[0] if len(ligas) == 1 else None
                if liga is None:
                    # time em varias ligas: testa a mais frequente
                    sub = rec[rec["team"].astype(str) == alvo]["league"].astype(str)
                    liga = sub.value_counts().index[0] if len(sub) else None
            r = decidir(cru, times, liga_do_time, liga, ligas_adv,
                        ultimo_jogo=ultimo_jogo, hoje=hoje, dias_max=dias_max)
            if r is None:
                absteve.append((cru, alvo, candidatos(cru, times)))
            elif r == alvo:
                certo.append((cru, alvo))
            else:
                errado.append((cru, alvo, r))
        total = len(certo) + len(absteve) + len(errado)
        print()
        print("=== %s: %d casos ===" % (rotulo, total))
        print("  CERTO ..... %2d  (a regra acharia sozinha)" % len(certo))
        print("  ABSTEVE ... %2d  (continua pedindo a ele, como hoje)" % len(absteve))
        print("  ERRADO .... %2d  (escolheria OUTRO time -- inaceitavel)" % len(errado))
        for cru, alvo, r in errado:
            print("     ERRADO: %r -> escolheria %r, o certo e %r" % (cru, r, alvo))
        if com_liga == "adv" and dias_max == 90:
            print("  abstencoes, e por que:")
            for cru, alvo, cs in absteve:
                motivo = ("nenhum candidato" if not cs
                          else "%d candidatos: %s" % (len(cs), ", ".join(cs[:4])))
                print("     %-22r -> %-34s (%s)" % (cru, alvo[:34], motivo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
