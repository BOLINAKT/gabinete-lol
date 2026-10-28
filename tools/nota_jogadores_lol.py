# -*- coding: utf-8 -*-
"""NOTA POR JOGADOR no LoL (28/10/2026, aprovada por ele) -- a mesma do Dota e do CS.

Cada jogador tem uma nota (Elo por RESULTADO) que leva de time em time; a forca do
time = media das notas do ULTIMO elenco visto. O app mistura com a chance do mapa,
depois do blend hibrido (app_core/nota_jogadores_lol_core.py):
    logit = c * ((1-w)*logit(p_modelo) + w*logit(p_jogador))

PROVA CEGA (28/10/2026), sobre a regua honesta igual ao que o app serve (semcj),
ajuste 28/02-27/06 e cego 28/06-26/10 (3.878 jogos), elenco = o ultimo conhecido:
  - em tudo:                          +0,0134 IC95 [+0,0059; +0,0213]
  - controles: so esticar 0,0000; Elo so de time +0,0075 (o ganho e do jogador)
  - ligas nacionais jul/ago/set +0,02 cada; internacionais ~0; outubro (promocao) -0,06
  - REGRA EM PRODUCAO: so quando os dois times tem a MESMA liga de origem (a mais
    comum nos ultimos 15 jogos fora de torneio internacional) e o jogo nao e entre
    regioes: total +0,0119 IC95 [+0,0055; +0,0184]. Escolhida por ele (a mais segura).

HISTORICO NUNCA PARTIDO: o time e o teamid do Oracle's Elixir; todo nome que o
teamid ja usou aponta para a mesma entrada.

Uso: python tools/nota_jogadores_lol.py   -> grava nota_jogadores_lol.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
SAIDA = RAIZ / "nota_jogadores_lol.json"
K_TIME, KJ = 24, 32
W_JOGADOR, TEMPERATURA = 0.7, 1.3          # escolhidos no ajuste (28/02-27/06)
JOGOS_LIGA_DE_ORIGEM = 15
# torneios que juntam regioes ou niveis: nao contam para a liga de origem
LIGAS_INTERNACIONAIS = ("WLDs", "MSI", "EWC", "FST", "DCGI", "WSCI", "EM", "LAS", "DCup", "CD", "AC")
COLUNAS = ["gameid", "date", "league", "split", "side", "position", "playername", "playerid",
           "teamname", "teamid", "result"]


def csvs() -> list:
    return sorted((RAIZ / "CSV_HISTORICO").glob("*_LoL_esports_match_data_from_OraclesElixir.csv")) + \
        sorted((RAIZ / "CSV_DIARIO").glob("*_LoL_esports_match_data_from_OraclesElixir.csv"))


def jogos_dos_csvs(arquivos) -> list:
    """[(data, gameid, time azul, time vermelho, y azul, elenco azul, elenco vermelho, liga, nome azul,
    nome vermelho, conta para a liga de origem)] em ordem de data. Time = teamid (nome so na falta); jogador = playerid."""
    d = pd.concat([pd.read_csv(c, usecols=COLUNAS, low_memory=False) for c in arquivos], ignore_index=True)
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["date"])
    pl = d[d.position != "team"].copy()
    pl["pid"] = pl.playerid.fillna("").astype(str)
    sem = pl.pid.isin(["", "nan"])
    pl.loc[sem, "pid"] = "nome:" + pl.loc[sem, "playername"].astype(str)
    tm = d[d.position == "team"].copy()
    tm["tkey"] = tm.teamid.fillna("").astype(str)
    sem = tm.tkey.isin(["", "nan"])
    tm.loc[sem, "tkey"] = "nome:" + tm.loc[sem, "teamname"].astype(str)
    tm = tm.drop_duplicates(["gameid", "side"])
    # PROMOCAO (28/10/2026): o Oracle's Elixir marca a promocao da LCS/CBLOL com a
    # liga principal e SEM split -- a Maryville (NACL) virava "LCS". Numa liga que
    # tem split, jogo sem split nao conta para a liga de origem.
    com_split = set(tm.loc[tm.split.notna() & (tm.split.astype(str).str.strip() != ""), "league"].astype(str))
    tm["conta_origem"] = ~(tm.league.astype(str).isin(com_split)
                          & (tm.split.isna() | (tm.split.astype(str).str.strip() == "")))
    elenco = pl.groupby(["gameid", "side"]).pid.apply(lambda s: sorted(set(s))).to_dict()
    fora = []
    for gid, g in tm.groupby("gameid", sort=False):
        b, r = g[g.side == "Blue"], g[g.side == "Red"]
        if len(g) != 2 or b.empty or r.empty:
            continue
        b, r = b.iloc[0], r.iloc[0]
        fora.append((b.date, gid, b.tkey, r.tkey, int(b.result), elenco.get((gid, "Blue"), []),
                     elenco.get((gid, "Red"), []), str(b.league), str(b.teamname), str(r.teamname),
                     bool(b.conta_origem)))
    fora.sort(key=lambda x: (x[0], x[1]))
    return fora


def p_elo(fa: float, fb: float) -> float:
    return 1 / (1 + 10 ** (-(fa - fb) / 400))


def rodar(jogos, k: float = K_TIME, kj: float = KJ):
    """Prequencial, atualizando com o elenco REAL de cada jogo. Devolve o estado final."""
    r, pr, ult = defaultdict(float), {}, {}
    hist = defaultdict(lambda: deque(maxlen=JOGOS_LIGA_DE_ORIGEM))
    nomes, visto = defaultdict(set), {}

    def forca(t, e):
        if len(e) < 3:
            return r[t]
        for j in e:
            pr.setdefault(j, r[t])
        return sum(pr[j] for j in e) / len(e)
    for dt, gid, a, b, y, ea, eb, liga, na, nb, conta in jogos:
        p = p_elo(forca(a, ea), forca(b, eb))
        r[a] += k * (y - p)
        r[b] -= k * (y - p)
        for e, s in ((ea, 1), (eb, -1)):
            for j in e:
                pr[j] = pr.get(j, 0.0) + s * kj * (y - p)
        for t, e, n in ((a, ea, na), (b, eb, nb)):
            if e:
                ult[t] = e
            nomes[t].add(n)
            visto[t] = (dt, n)
            if conta and liga not in LIGAS_INTERNACIONAIS:
                hist[t].append(liga)
    return r, pr, ult, hist, nomes, visto


def montar(jogos) -> dict:
    r, pr, ult, hist, nomes, visto = rodar(jogos)
    times = {}
    for t in visto:
        e = ult.get(t, [])
        forca = sum(pr.get(j, r[t]) for j in e) / len(e) if len(e) >= 3 else r[t]
        liga = Counter(hist[t]).most_common(1)[0][0] if hist[t] else None
        ent = {"forca": round(forca, 2), "elo_time": round(r[t], 2), "liga_de_origem": liga,
               "elenco": len(e), "visto_em": visto[t][0].strftime("%Y-%m-%d"), "nome_atual": visto[t][1]}
        # todos os nomes do mesmo teamid -> a mesma entrada; o nome ATUAL vence conflito
        for n in nomes[t]:
            if n not in times or times[n]["visto_em"] <= ent["visto_em"]:
                times[n] = ent
    return {"gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "parametros": {"k_time": K_TIME, "kj": KJ, "w_jogador": W_JOGADOR, "temperatura": TEMPERATURA,
                           "ligas_internacionais": list(LIGAS_INTERNACIONAIS)},
            "como_usar": "so se liga_de_origem igual e jogo nao entre regioes; p_jogador = "
                         "1/(1+10^(-(forca_A-forca_B)/400)); logit = c*((1-w)*logit(p)+w*logit(p_jogador))",
            "times": times}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    arqs = csvs()
    if not arqs:
        print("[nota jogadores lol] sem CSV")
        return 1
    out = montar(jogos_dos_csvs(arqs))
    SAIDA.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[nota jogadores lol] {len(out['times'])} nomes de time; w={W_JOGADOR} c={TEMPERATURA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
