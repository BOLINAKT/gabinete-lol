# -*- coding: utf-8 -*-
"""O METODO DELE numa linha de total de kills (28-29/10/2026, nas palavras dele).

Para apostar no MENOS de L (no MAIS e o espelho), os dois times juntos:
  1. Medias     -- "a media recente dos dois times tem que estar menor que a linha"
                   (ultimos 10 de cada).
  2. Adversario -- "se as medias estao mais altas e os adversarios eram over, pronto:
                   so foi over porque os adversarios eram over; se eram under, a
                   analise deu errado". Conta: a media AJUSTADA pelos adversarios
                   enfrentados (desconta 0,46 x o quanto eles puxavam o total acima
                   da liga; ver cruzamento_estatistica_core) do lado certo da linha.
  3. Historico  -- "em ordem: 5 / 20 / 10 / ano; o ano eu menos ligo". Passa quando os
                   ultimos 5, 20 e 10 (dos dois somados) tem 60%+ do lado. O ano so
                   aparece.
  4. Stats da linha -- StatsCamps: "pego no maximo 30% do outro lado" -- a media dos
                   dois times, no campeonato, do OUTRO lado da linha <= 30%.
  Referencia dele: 1,72 / 1,67 (58% / 60%).

MEDIDO (scratchpad metodo.py, 29/10/2026), cego 2026 com pesos de 2025, 57 mil
linhas: passos a favor 0/2/3/4 -> MAIS bate 38/54/61/68%, MENOS 43/60/64/67%;
"medias contra e adversario confirma" -> 38-43% (ele nao entra: certo). A CHANCE
(fair) e uma logistica nas mesmas medidas: +0,0148 de logloss sobre so o historico
e calibrada (onde diz 60-65%, bateu 61-63%).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import pandas as pd

JANELAS = (5, 20, 10)              # a ordem dele
MINIMO_POR_TIME = 5
MINIMO_CAMPEONATO = 3
PASSA_HIST = 0.60
TETO_OUTRO_LADO = 0.30
# (b0, media-L, media_aj-L, logit h5, logit h10, logit h20, logit stats) -> logit P(mais)
PESOS = (-0.0880, -0.0227, 0.1601, -0.0064, -0.3467, 0.4637, 0.1368)
NOMES = ("Médias", "Adversário", "Histórico", "Stats da linha")


def _lg(p: float) -> float:
    p = min(max(float(p), 0.02), 0.98)
    return math.log(p / (1 - p))


def _jogos(tg: pd.DataFrame, time: str, so_mapa1: bool) -> pd.DataFrame:
    d = tg[tg["team"].astype(str) == str(time)]
    if so_mapa1 and "map_number" in d.columns:
        d = d[pd.to_numeric(d["map_number"], errors="coerce").fillna(1).astype(int) == 1]
    return d.assign(_d=pd.to_datetime(d["date"], errors="coerce")).dropna(subset=["_d"]).sort_values("_d")


def _totais(d: pd.DataFrame) -> pd.Series:
    if "total_kills" in d.columns:
        return pd.to_numeric(d["total_kills"], errors="coerce")
    return pd.to_numeric(d["kills_for"], errors="coerce") + pd.to_numeric(d["kills_against"], errors="coerce")


def _camp(d: pd.DataFrame) -> pd.Series:
    """Os jogos do time no CAMPEONATO atual (liga + split + ano do ultimo jogo)."""
    if d.empty:
        return pd.Series(dtype=float)
    u = d.iloc[-1]
    c = d[(d["league"].astype(str) == str(u["league"])) & (d["split"].astype(str) == str(u.get("split")))
          & (d["_d"].dt.year == u["_d"].year)]
    return _totais(c).dropna()


def sinais(team_games: pd.DataFrame, time_a: str, time_b: str, linha: float,
           so_mapa1: bool = False) -> Optional[Dict[str, Any]]:
    """As medidas do metodo dele para a linha L, por time e somadas. None = pouco jogo. Pura."""
    from app_core.cruzamento_estatistica_core import PESO_AJUSTE_KILLS, com_tendencia_dos_adversarios
    if team_games is None or team_games.empty:
        return None
    tg = com_tendencia_dos_adversarios(team_games)
    da, db = _jogos(tg, time_a, so_mapa1), _jogos(tg, time_b, so_mapa1)
    if len(da) < MINIMO_POR_TIME or len(db) < MINIMO_POR_TIME:
        return None
    L = float(linha)

    def _time(d):
        tot = _totais(d).dropna()
        tend = pd.to_numeric(d.get("tend_adv_kills", pd.Series(0.0, index=d.index)), errors="coerce") \
            .reindex(tot.index).fillna(0.0)
        u10, t10 = tot.tail(10), tend.reindex(tot.tail(10).index).fillna(0.0)
        c = _camp(d)
        ult = d.iloc[-1]
        return {"media": float(u10.mean()), "media_aj": float((u10 - PESO_AJUSTE_KILLS * t10).mean()),
                "adv": float(t10.mean()), "n10": int(len(u10)),
                "janelas": {n: (int((tot.tail(n) > L).sum()), int(len(tot.tail(n)))) for n in JANELAS},
                "ano": (int((tot > L).sum()), int(len(tot))),
                "camp": (int((c > L).sum()), int(len(c))),
                "camp_rotulo": " ".join(str(x) for x in (ult["league"], ult.get("split"))
                                        if x is not None and str(x) not in ("", "nan"))}
    a, b = _time(da), _time(db)
    media = (a["media"] + b["media"]) / 2
    media_aj = (a["media_aj"] + b["media_aj"]) / 2
    h = {n: (a["janelas"][n][0] + b["janelas"][n][0]) / max(1, a["janelas"][n][1] + b["janelas"][n][1])
         for n in JANELAS}
    camp = None
    if a["camp"][1] >= MINIMO_CAMPEONATO and b["camp"][1] >= MINIMO_CAMPEONATO:
        camp = (a["camp"][0] / a["camp"][1] + b["camp"][0] / b["camp"][1]) / 2     # % MAIS, media dos dois
    out = {"linha": L, "mapa1": bool(so_mapa1), "a": a, "b": b, "media": media, "media_aj": media_aj,
           "h": h, "camp_mais": camp}
    if camp is not None:
        b0, wm, wa, w5, w10, w20, wc = PESOS
        z = (b0 + wm * (media - L) + wa * (media_aj - L) + w5 * _lg(h[5]) + w10 * _lg(h[10])
             + w20 * _lg(h[20]) + wc * _lg(camp))
        out["p_over"] = 1.0 / (1.0 + math.exp(-z))
    return out


def passam(sn: Dict[str, Any], lado: str) -> List[Optional[bool]]:
    """[Medias, Adversario, Historico, Stats] a favor do lado ('over'/'under'); None = sem dado."""
    mais = str(lado).lower() == "over"
    L = sn["linha"]
    p1 = sn["media"] > L if mais else sn["media"] < L
    p2 = sn["media_aj"] > L if mais else sn["media_aj"] < L
    hs = [sn["h"][n] if mais else 1 - sn["h"][n] for n in JANELAS]
    p3 = all(x >= PASSA_HIST for x in hs)
    c = sn.get("camp_mais")
    p4 = None if c is None else ((1 - c) if mais else c) <= TETO_OUTRO_LADO
    return [p1, p2, p3, p4]


def chance(sn: Dict[str, Any], lado: str) -> Optional[float]:
    p = sn.get("p_over")
    if p is None:
        return None
    return p if str(lado).lower() == "over" else 1.0 - p


def resumo_html(sn: Optional[Dict[str, Any]], lado: str, rotulo: str = "", odd: Any = None) -> str:
    """'✓ ✓ ✗ ✓ 3/4 · justa 1,64' em HTML curto (para celulas de tabela)."""
    if not sn:
        return '<span class="q">pouco jogo</span>'
    ps = passam(sn, lado)
    marcas = "".join('<span title="{}" style="color:{}">{}</span>'.format(
        n, "var(--boa)" if v else ("var(--fraco)" if v is None else "var(--ruim)"),
        "✓" if v else ("·" if v is None else "✗")) for n, v in zip(NOMES, ps))
    k = sum(1 for v in ps if v)
    tot = sum(1 for v in ps if v is not None)
    p = chance(sn, lado)
    justa = "" if not p else ' · justa {:.2f}'.format(1 / p).replace(".", ",")
    try:
        if p and odd and float(odd) > 1:
            v = (p * float(odd) - 1) * 100
            justa += ' <span style="color:{};font-weight:700">{}</span>'.format(
                "var(--boa)" if v > 0 else "var(--ruim)", f"{v:+.1f}%".replace(".", ","))
    except (TypeError, ValueError):
        pass
    cor = "var(--boa)" if k >= 2 else "var(--fraco)"
    fraco = 'style="color:var(--fraco);font-size:11px"'
    return '<span style="white-space:nowrap">{}<b>{}</b> <b style="color:{}">{}/{}</b><span {}>{}</span></span>'.format(
        f'<span {fraco}>{rotulo}</span>' if rotulo else "", marcas, cor, k, tot, fraco, justa)
