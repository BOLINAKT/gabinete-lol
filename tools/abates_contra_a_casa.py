# -*- coding: utf-8 -*-
"""A fair odd de ABATES que a tela mostra, contra o preco da Pinnacle.

ELE EXPLICOU O QUE PRECISA (22/09/2026):

    "eu entendo o modelo ele ser afastado do ml da pinnacle, ate porque e a
    casa mais sharp que nos temos, o que eu preciso e realmente a vantagem em
    relacao as kills, porque elas sao mais logicas, se a pinnacle oferecer
    27.5, e for uma linha que ainda e boa, sei la, vamos dizer que la no
    resumo ele aparece com uma fair de 1.40 e na pinnacle ele esta com 1,72
    de odd, e ele que eu vou girar"

Isso muda a pergunta. Nao interessa se o modelo empata com a Pinnacle no
vencedor -- interessa se a FAIR DE ABATES que ele ve na tela ganha dinheiro.

O QUE ESTA FERRAMENTA MEDE, E O QUE ISSO EXIGE

Ela mede a fair odd DA TELA, nao uma minha. O caminho e o mesmo do app:

    build_profile(dos dois times) -> _expected_totals_dc -> prob_over_from_total

com as regulagens padrao (meia-vida 180 dias, sem filtro de ano/liga/split).
Medir um modelo melhor que o servido responderia outra pergunta: diria o que
seria possivel, nao o que ele tem na mao.

PONTO-NO-TEMPO: para cada partida, o quadro de jogos e cortado ANTES da data
dela. `apply_dc_blend` usa a data mais recente do quadro que recebe, entao
cortar o quadro ja acerta o `as_of`.

SO A LINHA PRINCIPAL. As alternativas sao a maioria das leituras e cobram
mais caro; medir nelas responderia sobre uma aposta que ele nao deveria
fazer.

A MARGEM SAI ANTES. 1/odd dos dois lados soma mais que 1 (7,08% de mediana
neste mercado). Sem tirar, a casa pareceria pior do que e.

A INCERTEZA CONTA PARTIDA, NAO APOSTA. Varias linhas do mesmo mapa acertam
ou erram juntas.

Uso: python tools/abates_contra_a_casa.py
"""
from __future__ import annotations

import json
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

PARTIDAS = ROOT / "odds_pinnacle_partidas.jsonl"
PRECOS = ROOT / "odds_pinnacle_historico.jsonl"

# A unidade como a CASA escreve.
UNIDADE = "kills"
PARTIDAS_MINIMAS = 60
MEIA_VIDA = 180.0          # o padrao da barra lateral


def _linhas(arq):
    if not arq.exists():
        return []
    fora = []
    for linha in arq.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        try:
            fora.append(json.loads(linha))
        except ValueError:
            continue
    return fora


def apostas_de_total(unidade=UNIDADE):
    """As linhas PRINCIPAIS de total, sem a margem da casa.

    Uma aposta e (jogo, mapa, pontos): o par over/under da mesma linha.
    """
    ultimo = {}
    for x in _linhas(PRECOS):
        if x.get("tipo") != "total" or x.get("alternativa"):
            continue
        if str(x.get("unidade") or "").strip().lower() != unidade:
            continue
        lado = str(x.get("lado") or "").strip().lower()
        if lado not in ("over", "under"):
            continue
        try:
            odd = float(x.get("odd"))
            pontos = float(x.get("pontos"))
            periodo = int(x.get("periodo") or 0)
        except (TypeError, ValueError):
            continue
        if not odd > 1.0 or not 1 <= periodo <= 5:
            continue
        ch = (x.get("jogo"), periodo, pontos, lado)
        ant = ultimo.get(ch)
        if ant is None or str(x.get("lido_em")) > str(ant.get("lido_em")):
            ultimo[ch] = x

    fora = []
    for j, mp, pts in {(a, b, c) for (a, b, c, _l) in ultimo}:
        o, u = ultimo.get((j, mp, pts, "over")), ultimo.get((j, mp, pts, "under"))
        if not o or not u:
            continue          # sem os dois lados nao da para tirar a margem
        io_, iu = 1.0 / float(o["odd"]), 1.0 / float(u["odd"])
        soma = io_ + iu
        if soma <= 0:
            continue
        fora.append({"jogo": j, "mapa": mp, "linha": pts,
                     "p_over": io_ / soma, "p_under": iu / soma,
                     "odd_over": float(o["odd"]), "odd_under": float(u["odd"]),
                     "margem_pct": 100.0 * (soma - 1.0),
                     "limite": o.get("limite")})
    return fora


def main() -> int:
    import numpy as np
    import pandas as pd

    from app_core.schedule_import_core import resolve_schedule_team
    from mlcore.lines_engine import Filters, build_profile, prob_over_from_total
    from mlcore.stats_teams import build_team_games, load_team_rows
    from tools.modelo_contra_a_casa import _apelidos
    from tools.nota_honesta import default_csvs

    # O MESMO caminho da tela. Importado do app, nao reescrito.
    from app_core.runtime_wrappers_core import _expected_totals_dc

    nomes = {x["id"]: x for x in _linhas(PARTIDAS) if x.get("id") is not None}
    apostas = apostas_de_total()
    print("[abates] %d apostas de linha principal em %d partidas"
          % (len(apostas), len({a["jogo"] for a in apostas})))
    if not apostas:
        return 1

    tg = pd.concat([build_team_games(load_team_rows(str(c))) for c in default_csvs()],
                   ignore_index=True)
    tg["date"] = pd.to_datetime(tg["date"], errors="coerce")
    tg = tg.dropna(subset=["date"])
    azul = tg[tg["side"].astype(str).str.lower() == "blue"]

    ap = _apelidos()
    times = sorted({str(t) for t in tg["team"].dropna().unique()})

    def resolver(n):
        try:
            achado, ok = resolve_schedule_team(str(n or ""), times, ap)
        except (TypeError, ValueError):
            return ""
        return str(achado) if ok else ""

    indice = {}
    for r in azul.itertuples(index=False):
        par = tuple(sorted((str(r.team), str(r.opponent))))
        mp = int(getattr(r, "map_number", 1) or 1)
        indice.setdefault((str(r.date)[:10], par, mp), []).append(r)

    filtros = Filters(year=None, league=None, split=None, playoffs=None)
    cache = {}
    casos, sem = [], {"apelido": 0, "jogo": 0, "modelo": 0}

    for a in apostas:
        j = nomes.get(a["jogo"])
        if not j or not j.get("inicio_utc"):
            sem["jogo"] += 1
            continue
        ca, fa = resolver(j.get("casa")), resolver(j.get("fora"))
        if not ca or not fa:
            sem["apelido"] += 1
            continue
        par = tuple(sorted((ca, fa)))
        dia = str(j["inicio_utc"])[:10]
        achados = []
        for delta in (0, -1, 1):
            dd = (pd.Timestamp(dia) + pd.Timedelta(days=delta)).strftime("%Y-%m-%d")
            achados += indice.get((dd, par, a["mapa"]), [])
        if not achados:
            sem["jogo"] += 1
            continue
        r = achados[0]
        real = pd.to_numeric(pd.Series([getattr(r, "total_kills", None)]),
                             errors="coerce").iloc[0]
        if real != real:
            sem["jogo"] += 1
            continue

        ch = (ca, fa, a["mapa"], str(r.date))
        if ch not in cache:
            # PONTO-NO-TEMPO: so o que existia ANTES desta partida.
            antes = tg[tg["date"] < r.date]
            mapa = "m%d" % a["mapa"]
            try:
                pa = build_profile(antes, team=ca, filters=filtros, league_mode="all",
                                   map_mode=mapa, half_life_days=MEIA_VIDA,
                                   max_games=None)
                pb = build_profile(antes, team=fa, filters=filtros, league_mode="all",
                                   map_mode=mapa, half_life_days=MEIA_VIDA,
                                   max_games=None)
                cache[ch] = (_expected_totals_dc(antes, pa, pb)
                             if (pa.n_games and pb.n_games) else None)
            except Exception:
                cache[ch] = None
        totais = cache[ch]
        if not totais or "kills" not in totais:
            sem["modelo"] += 1
            continue
        p_over = prob_over_from_total(totais["kills"], float(a["linha"]))
        if not (p_over == p_over and 0.0 < p_over < 1.0):
            sem["modelo"] += 1
            continue

        casos.append({"partida": a["jogo"], "mapa": a["mapa"], "linha": a["linha"],
                      "p_modelo": float(p_over), "p_casa": float(a["p_over"]),
                      "y": 1.0 if float(real) > float(a["linha"]) else 0.0,
                      "margem": a["margem_pct"], "limite": a.get("limite"),
                      "odd_over": a["odd_over"], "odd_under": a["odd_under"],
                      "confronto": "%s x %s" % (j.get("casa"), j.get("fora")),
                      "liga": j.get("liga")})

    n_part = len({c["partida"] for c in casos})
    print("[abates] casaram: %d apostas em %d partidas | fora: apelido %d, "
          "jogo %d, modelo %d"
          % (len(casos), n_part, sem["apelido"], sem["jogo"], sem["modelo"]))
    if not casos:
        print("[abates] nada para medir ainda.")
        return 0

    pm = np.array([c["p_modelo"] for c in casos])
    pc = np.array([c["p_casa"] for c in casos])
    y = np.array([c["y"] for c in casos])

    def _perda(p):
        q = np.clip(p, 1e-9, 1 - 1e-9)
        return -(y * np.log(q) + (1 - y) * np.log(1 - q))

    lm, lc = float(np.mean(_perda(pm))), float(np.mean(_perda(pc)))
    print()
    print("=== A FAIR DE ABATES DA TELA, CONTRA A CASA ===")
    print("margem media da casa: %.2f%% (ja retirada)"
          % float(np.mean([c["margem"] for c in casos])))
    print("distancia media entre os dois precos: %.1f pp"
          % float(np.mean(np.abs(pm - pc)) * 100))
    print()
    print("  logloss do modelo ... %.4f" % lm)
    print("  logloss da casa ..... %.4f" % lc)
    print("  diferenca ........... %+.4f  (%s)"
          % (lm - lc, "o modelo perde" if lm > lc else "o modelo ganha"))

    dif = _perda(pm) - _perda(pc)
    por_partida = {}
    for c, d in zip(casos, dif):
        por_partida.setdefault(c["partida"], []).append(float(d))
    medias = np.array([float(np.mean(v)) for v in por_partida.values()])
    print()
    print("INCERTEZA, contando PARTIDA e nao aposta (%d partidas)" % len(medias))
    if len(medias) > 1:
        print("  margem de erro: +-%.4f"
              % (1.96 * float(np.std(medias, ddof=1)) / math.sqrt(len(medias))))
        print("  partidas em que o modelo bateu a casa: %d de %d"
              % (int((medias < 0).sum()), len(medias)))

    # O QUE ELE FARIA DE VERDADE: apostar so onde a fair da tela diz que ha
    # vantagem. Nao e a mesma pergunta que "quem preve melhor" -- da para
    # prever pior no geral e ainda assim escolher bem onde apostar.
    print()
    print("SE ELE APOSTASSE SO ONDE A TELA APONTA VANTAGEM")
    print("%-14s %7s %9s %10s  %s"
          % ("vantagem min.", "apostas", "acerto", "retorno",
             "intervalo de 95% (reamostrando PARTIDAS)"))
    for minimo in (0.0, 0.03, 0.05, 0.10):
        lucro = n = acertos = 0.0
        for c in casos:
            for lado, p, odd, deu in (("over", c["p_modelo"], c["odd_over"], c["y"]),
                                      ("under", 1 - c["p_modelo"], c["odd_under"],
                                       1 - c["y"])):
                if p * odd - 1.0 <= minimo:
                    continue
                n += 1
                acertos += deu
                lucro += (odd - 1.0) if deu else -1.0
        if n < 5:
            print("%-14s %7d  (poucas apostas)" % ("%.0f%%" % (100 * minimo), int(n)))
            continue
        # A INCERTEZA DO RETORNO, reamostrando PARTIDAS.
        #
        # Um mapa costuma ter varias linhas (24.5, 26.5, 28.5...). Se o modelo
        # acerta o total daquele mapa, TODAS ganham juntas. Entao 51 apostas
        # nao sao 51 eventos -- sao ~20. Uma barra de erro calculada por
        # aposta daria uma certeza que nao existe, e num numero de +23% isso
        # seria caro.
        por_p = {}
        for c in casos:
            for p_, odd, deu in ((c["p_modelo"], c["odd_over"], c["y"]),
                                 (1 - c["p_modelo"], c["odd_under"], 1 - c["y"])):
                if p_ * odd - 1.0 <= minimo:
                    continue
                por_p.setdefault(c["partida"], []).append(
                    (odd - 1.0) if deu else -1.0)
        chaves = list(por_p)
        if len(chaves) >= 5:
            rng = np.random.default_rng(20260922)
            amostras = []
            for _ in range(2000):
                esc = rng.integers(0, len(chaves), size=len(chaves))
                vals = [v for i in esc for v in por_p[chaves[i]]]
                amostras.append(100.0 * sum(vals) / max(len(vals), 1))
            lo, hi = np.percentile(amostras, [2.5, 97.5])
        else:
            lo = hi = float("nan")
        print("%-14s %7d %8.1f%% %9.1f%%  [%+.0f%%, %+.0f%%] em %d partidas"
              % ("%.0f%%" % (100 * minimo), int(n), 100 * acertos / n,
                 100 * lucro / n, lo, hi, len(chaves)))
    print()
    print("(retorno = lucro por unidade apostada; a margem da casa ja esta")
    print(" dentro das odds usadas, entao isto e o que sobraria no bolso)")

    if len(medias) < PARTIDAS_MINIMAS:
        print()
        print("  >> AMOSTRA PEQUENA DEMAIS (%d partidas de %d). Nenhuma"
              % (len(medias), PARTIDAS_MINIMAS))
        print("     conclusao sai daqui, nem a favor nem contra.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
