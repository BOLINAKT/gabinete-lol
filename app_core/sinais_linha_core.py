# -*- coding: utf-8 -*-
"""O METODO DELE numa linha de TOTAL (kills, torres, dragoes, baroes, inibidores, tempo).

Para o MENOS de L (no MAIS e o espelho), os dois times juntos (28-29/10/2026, nas
palavras dele):
  1. Medias     -- "a media recente dos dois times tem que estar menor que a linha"
                   (ultimos 10 de cada).
  2. Adversario -- "se as medias estao mais altas e os adversarios eram over: so foi over
                   porque os adversarios eram over; se eram under, a analise deu errado".
                   Conta: a media AJUSTADA pelos adversarios enfrentados (desconta uma
                   fracao -- medida por mercado -- do quanto eles puxavam o total acima
                   da liga) do lado certo da linha.
  3. Historico  -- "5 / 20 / 10 / ano; o ano eu menos ligo": os ultimos 5, 20 e 10 (dos
                   dois somados) com 60%+ do lado. O ano so aparece.
  4. Stats da linha -- "pego no maximo 30% do outro lado": a media dos dois, no
                   campeonato, do OUTRO lado da linha <= 30%.
  Referencia dele: 1,72 / 1,67 (58% / 60%).

MEDIDO por mercado (scratchpad metodo_geral.py, 29/10/2026), cego 2026 com pesos de
2025, linhas perto da media: ver BATEU. A chance (fair) e uma logistica nas mesmas
medidas, ganho sobre so o historico: kills +0,016, torres +0,024, dragoes +0,031,
tempo +0,015, baroes +0,044, inibidores +0,039. Baroes e inibidores (poucos valores
possiveis) tem a contagem de passos instavel: o painel avisa.
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
NOMES = ("Médias", "Adversário", "Histórico", "Stats da linha")

# metrica -> colunas (a favor, contra) ou a coluna do tempo; ajuste do adversario medido;
# pesos (b0, media-L, media_aj-L, logit h5, logit h10, logit h20, logit stats) -> logit P(mais);
# o que bateu no cego com 0..4 passos a favor (linhas perto da media)
METRICAS: Dict[str, Dict[str, Any]] = {
    "kills": {"cols": ("kills_for", "kills_against"), "ajuste": 0.46, "unidade": "kills",
              "pesos": (-0.0068, -0.0278, 0.1472, 0.0046, -0.2024, 0.4476, 0.1338),
              "bateu": {"over": {0: 34, 1: 47, 2: 56, 3: 63, 4: 70}, "under": {0: 41, 1: 53, 2: 59, 3: 67, 4: 71}}},
    "towers": {"cols": ("towers_for", "towers_against"), "ajuste": 0.38, "unidade": "torres",
               "pesos": (-0.0633, 0.0737, 0.5861, 0.0003, -0.4066, 0.5907, 0.1233),
               "bateu": {"over": {0: 32, 1: 45, 2: 56, 3: 68, 4: 72}, "under": {0: 39, 1: 54, 2: 59, 3: 66, 4: 73}}},
    "dragons": {"cols": ("dragons_for", "dragons_against"), "ajuste": 0.42, "unidade": "dragões",
                "pesos": (0.0340, 0.6868, 1.0331, -0.0042, -0.3335, 0.3814, 0.1265),
                "bateu": {"over": {0: 32, 1: 50, 2: 62, 3: 65, 4: 76}, "under": {0: 36, 1: 41, 2: 57, 3: 63, 4: 74}}},
    "barons": {"cols": ("barons_for", "barons_against"), "ajuste": 0.41, "unidade": "barões", "instavel": True,
               "pesos": (0.0562, 1.2615, 1.3517, -0.0504, -0.3025, 0.3516, 0.1531),
               "bateu": {"over": {0: 32, 1: 40, 2: 68, 3: 59, 4: 82}, "under": {0: 50, 1: 32, 2: 46, 3: 63, 4: 73}}},
    "inhibitors": {"cols": ("inhibitors_for", "inhibitors_against"), "ajuste": 0.45, "unidade": "inibidores",
                   "instavel": True,
                   "pesos": (0.0504, 0.8246, 1.0123, -0.0168, -0.3842, 0.7102, 0.0197),
                   "bateu": {"over": {0: 26, 1: 39, 2: 55, 3: 47, 4: 49},
                             "under": {0: 48, 1: 42, 2: 54, 3: 69, 4: 77}}},
    "time": {"cols": None, "ajuste": 0.40, "unidade": "min",
             "pesos": (-0.0942, -0.0637, 0.2318, -0.0090, -0.1413, 0.4924, 0.1270),
             "bateu": {"over": {0: 34, 1: 45, 2: 54, 3: 62, 4: 69}, "under": {0: 42, 1: 54, 2: 62, 3: 67, 4: 71}}},
}
# coluna da Analise de Linha -> metrica
COLUNA_PARA_METRICA = {"total_kills": "kills", "mv2_total_kills": "kills", "mv2_total_towers": "towers",
                       "total_towers": "towers", "mv2_total_dragons": "dragons", "total_dragons": "dragons",
                       "mv2_total_barons": "barons", "total_nashors": "barons",
                       "mv2_total_inhibitors": "inhibitors", "total_inhibitors": "inhibitors",
                       "game_time_min": "time"}
PESOS = METRICAS["kills"]["pesos"]            # compatibilidade
_CACHE_TEND: Dict[Any, pd.DataFrame] = {}


def _lg(p: float) -> float:
    p = min(max(float(p), 0.02), 0.98)
    return math.log(p / (1 - p))


def _total(d: pd.DataFrame, met: str) -> pd.Series:
    cols = METRICAS[met]["cols"]
    if cols is None:
        t = pd.to_numeric(d.get("game_time_min", pd.Series(dtype=float, index=d.index)), errors="coerce")
        if len(t) and t.isna().all() and "gamelength" in d.columns:
            t = pd.to_numeric(d["gamelength"], errors="coerce") / 60.0
        return t
    return pd.to_numeric(d[cols[0]], errors="coerce") + pd.to_numeric(d[cols[1]], errors="coerce")


def com_tendencia(team_games: pd.DataFrame, met: str) -> pd.DataFrame:
    """team_games + 'tend_<met>': quanto o ADVERSARIO de cada jogo puxava o total acima da liga,
    ANTES do jogo (seus 10 anteriores menos os ultimos 200 da liga). Kills reaproveita a coluna
    de cruzamento_estatistica_core."""
    col = f"tend_{met}"
    if met == "kills":
        from app_core.cruzamento_estatistica_core import com_tendencia_dos_adversarios
        d = com_tendencia_dos_adversarios(team_games)
        if "tend_adv_kills" in d.columns and col not in d.columns:
            d = d.assign(**{col: d["tend_adv_kills"]})
        return d
    if col in team_games.columns:
        return team_games
    chave = (id(team_games), len(team_games), met)
    if chave in _CACHE_TEND:
        return _CACHE_TEND[chave]
    try:
        d = team_games.copy()
        d["_d"] = pd.to_datetime(d["date"], errors="coerce")
        d["_tot"] = _total(d, met)
        d = d.sort_values(["_d", "gameid"])
        d["_pt"] = d.groupby("team")["_tot"].transform(lambda x: x.shift(1).rolling(10, min_periods=3).mean())
        d["_pl"] = d.groupby("league")["_tot"].transform(lambda x: x.shift(1).rolling(200, min_periods=30).mean())
        adv = d[["gameid", "team", "_pt"]].drop_duplicates(["gameid", "team"]).rename(
            columns={"team": "opponent", "_pt": "_pa"})
        d = d.merge(adv, on=["gameid", "opponent"], how="left")
        d[col] = (d["_pa"] - d["_pl"]).fillna(0.0)
        d = d.drop(columns=["_d", "_tot", "_pt", "_pl", "_pa"])
    except (KeyError, TypeError, ValueError):
        return team_games
    if len(_CACHE_TEND) > 8:
        _CACHE_TEND.clear()
    _CACHE_TEND[chave] = d
    return d


def _jogos(tg: pd.DataFrame, time: str, so_mapa1: bool) -> pd.DataFrame:
    d = tg[tg["team"].astype(str) == str(time)]
    if so_mapa1 and "map_number" in d.columns:
        d = d[pd.to_numeric(d["map_number"], errors="coerce").fillna(1).astype(int) == 1]
    return d.assign(_d=pd.to_datetime(d["date"], errors="coerce")).dropna(subset=["_d"]).sort_values("_d")


def _camp(d: pd.DataFrame, met: str) -> pd.Series:
    """Os jogos do time no CAMPEONATO atual (liga + split + ano do ultimo jogo)."""
    if d.empty:
        return pd.Series(dtype=float)
    u = d.iloc[-1]
    c = d[(d["league"].astype(str) == str(u["league"])) & (d["split"].astype(str) == str(u.get("split")))
          & (d["_d"].dt.year == u["_d"].year)]
    return _total(c, met).dropna()


def sinais(team_games: pd.DataFrame, time_a: str, time_b: str, linha: float,
           so_mapa1: bool = False, metrica: str = "kills") -> Optional[Dict[str, Any]]:
    """As medidas do metodo dele para a linha L, por time e somadas. None = pouco jogo. Pura."""
    if team_games is None or team_games.empty or metrica not in METRICAS:
        return None
    cfg = METRICAS[metrica]
    tg = com_tendencia(team_games, metrica)
    col_t = f"tend_{metrica}"
    da, db = _jogos(tg, time_a, so_mapa1), _jogos(tg, time_b, so_mapa1)
    if len(da) < MINIMO_POR_TIME or len(db) < MINIMO_POR_TIME:
        return None
    L = float(linha)

    def _time(d):
        tot = _total(d, metrica).dropna()
        tend = pd.to_numeric(d.get(col_t, pd.Series(0.0, index=d.index)), errors="coerce") \
            .reindex(tot.index).fillna(0.0)
        u10 = tot.tail(10)
        t10 = tend.reindex(u10.index).fillna(0.0)
        c = _camp(d, metrica)
        ult = d.iloc[-1]
        return {"media": float(u10.mean()), "media_aj": float((u10 - cfg["ajuste"] * t10).mean()),
                "adv": float(t10.mean()), "n10": int(len(u10)),
                "janelas": {n: (int((tot.tail(n) > L).sum()), int(len(tot.tail(n)))) for n in JANELAS},
                "ano": (int((tot > L).sum()), int(len(tot))),
                "camp": (int((c > L).sum()), int(len(c))),
                "camp_rotulo": " ".join(str(x) for x in (ult["league"], ult.get("split"))
                                        if x is not None and str(x) not in ("", "nan"))}
    a, b = _time(da), _time(db)
    if not (a["n10"] and b["n10"]):
        return None
    media = (a["media"] + b["media"]) / 2
    media_aj = (a["media_aj"] + b["media_aj"]) / 2
    h = {n: (a["janelas"][n][0] + b["janelas"][n][0]) / max(1, a["janelas"][n][1] + b["janelas"][n][1])
         for n in JANELAS}
    camp = None
    if a["camp"][1] >= MINIMO_CAMPEONATO and b["camp"][1] >= MINIMO_CAMPEONATO:
        camp = (a["camp"][0] / a["camp"][1] + b["camp"][0] / b["camp"][1]) / 2     # % MAIS, media dos dois
    out = {"linha": L, "mapa1": bool(so_mapa1), "metrica": metrica, "a": a, "b": b, "media": media,
           "media_aj": media_aj, "h": h, "camp_mais": camp}
    if camp is not None:
        b0, wm, wa, w5, w10, w20, wc = cfg["pesos"]
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
