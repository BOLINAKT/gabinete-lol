# -*- coding: utf-8 -*-
"""OS 4 SINAIS DELE numa linha de total de kills (28/10/2026, pedido dele).

Ele: "nao vou analisar friamente so baseado no historico... sao 4 coisas que eu
vejo, se duas delas passam eu ja considero entrar, e nao tem ordem". E: "as
vezes tem analises que eu pego SO no mapa 1". Os sinais, para Mais/Menos de L:

  1. Historico   -- dos ultimos 10 jogos de cada time (20 somados), quantos
                    passaram da linha (Laplace). Passa: 60% ou mais do lado.
  2. Medias      -- media recente dos dois (mesmos 20 jogos) contra a linha.
                    Passa: 1 kill ou mais de folga do lado.
  3. Adversario  -- o historico com o total AJUSTADO pelos adversarios
                    enfrentados (ver cruzamento_estatistica_core). Passa: 60%.
  4. StatsCamps  -- os jogos dos dois no CAMPEONATO atual (liga + split + ano
                    do ultimo jogo de cada). Passa: 60%.
  Mapa 1: o mesmo, so com jogos de mapa 1.

FAIR DO CONJUNTO: regressao logistica nos 4 sinais, pesos ajustados no
historico 2025-2026 (scratchpad sinais.py, 28/10/2026). Cego 2026 (pesos de 2025):
  qualquer mapa: 0/1/2/3/4 sinais -> over bate 40/54/60/61/65%; conjunto +0,0106
                 de logloss sobre o historico puro (IC95 [+0,0097; +0,0116]);
  mapa 1:        40/54/60/62/67%; conjunto +0,0080 (IC95 [+0,0065; +0,0095]).
Contra a linha REAL da Pinnacle (496 linhas): com 0 sinais o over perde 14%;
com 2+ fica perto do zero a zero -- os sinais FILTRAM; o valor vem quando a casa
mole (Stake) se afasta da Pinnacle. Por isso a fair do conjunto fica AO LADO da
do modelo, ainda sem substitui-la.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional

import pandas as pd

JANELA = 10
MINIMO_POR_TIME = 5
MINIMO_CAMPEONATO = 4
PASSA_PCT = 0.60
FOLGA_MEDIA = 1.0
# (intercepto, historico, medias, adversario, statscamps) -- logit de p, exceto medias (kills)
PESOS = {"todos": (-0.0970, -0.3866, 0.1469, 0.2675, 0.3306),
         "mapa1": (-0.0545, -0.1710, 0.1488, 0.1297, 0.2665)}
NOMES = ("Histórico", "Médias", "Adversário", "StatsCamps")


def _lg(p: float) -> float:
    p = min(max(float(p), 1e-4), 1 - 1e-4)
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


def sinais(team_games: pd.DataFrame, time_a: str, time_b: str, linha: float,
           so_mapa1: bool = False) -> Optional[Dict[str, Any]]:
    """{'s': [hist, medias, adv, camp], 'n', 'p_over', ...} ou None (pouco jogo). Pura."""
    from app_core.cruzamento_estatistica_core import PESO_AJUSTE_KILLS, com_tendencia_dos_adversarios
    if team_games is None or team_games.empty:
        return None
    tg = com_tendencia_dos_adversarios(team_games)
    da, db = _jogos(tg, time_a, so_mapa1), _jogos(tg, time_b, so_mapa1)
    ua, ub = da.tail(JANELA), db.tail(JANELA)
    if len(ua) < MINIMO_POR_TIME or len(ub) < MINIMO_POR_TIME:
        return None
    L = float(linha)
    raw = pd.concat([_totais(ua), _totais(ub)]).dropna()
    tend = pd.concat([ua.get("tend_adv_kills", pd.Series(0.0, index=ua.index)),
                      ub.get("tend_adv_kills", pd.Series(0.0, index=ub.index))]).reindex(raw.index).fillna(0.0)
    aj = raw - PESO_AJUSTE_KILLS * tend
    n = len(raw)
    s1 = ((raw > L).sum() + 1) / (n + 2)
    s2 = float(raw.mean() - L)
    s3 = ((aj > L).sum() + 1) / (n + 2)

    def _camp(d):
        if d.empty:
            return pd.Series(dtype=float)
        u = d.iloc[-1]
        c = d[(d["league"].astype(str) == str(u["league"])) & (d["split"].astype(str) == str(u.get("split")))
              & (d["_d"].dt.year == u["_d"].year)]
        return _totais(c).dropna()
    camp = pd.concat([_camp(da), _camp(db)])
    s4 = ((camp > L).sum() + 1) / (len(camp) + 2) if len(camp) >= MINIMO_CAMPEONATO else None
    out = {"s": [float(s1), s2, float(s3), None if s4 is None else float(s4)], "n": n,
           "n_camp": int(len(camp)), "media": float(raw.mean()), "linha": L, "mapa1": bool(so_mapa1)}

    # O NUMERO POR TRAS DE CADA SINAL, por time (aba "Seus sinais", 28/10/2026: ele quer
    # ver, por exemplo, que e a LYON que puxa o under e que o historico dela esta inflado)
    def _det(d, u):
        t = _totais(u).dropna()
        td = pd.to_numeric(u.get("tend_adv_kills", pd.Series(0.0, index=u.index)), errors="coerce") \
            .reindex(t.index).fillna(0.0)
        c = _camp(d)
        ult = d.iloc[-1] if not d.empty else None
        return {"n": int(len(t)), "acima": int((t > L).sum()), "media": float(t.mean()) if len(t) else None,
                "acima_aj": int(((t - PESO_AJUSTE_KILLS * td) > L).sum()), "adv": float(td.mean()) if len(td) else 0.0,
                "camp_n": int(len(c)), "camp_acima": int((c > L).sum()),
                "camp_rotulo": "" if ult is None else " ".join(
                    str(x) for x in (ult["league"], ult.get("split")) if x is not None and str(x) not in ("", "nan"))}
    out["detalhe"] = {"a": _det(da, ua), "b": _det(db, ub)}
    if s4 is not None:
        b0, w1, w2, w3, w4 = PESOS["mapa1" if so_mapa1 else "todos"]
        z = b0 + w1 * _lg(s1) + w2 * s2 + w3 * _lg(s3) + w4 * _lg(s4)
        out["p_over"] = 1.0 / (1.0 + math.exp(-z))
    return out


def passam(sn: Dict[str, Any], lado: str) -> list:
    """[True/False/None] dos 4 sinais para 'over' ou 'under' (None = sem dado)."""
    s1, s2, s3, s4 = sn["s"]
    if str(lado).lower() == "over":
        r = [s1 >= PASSA_PCT, s2 >= FOLGA_MEDIA, s3 >= PASSA_PCT, None if s4 is None else s4 >= PASSA_PCT]
    else:
        r = [s1 <= 1 - PASSA_PCT, s2 <= -FOLGA_MEDIA, s3 <= 1 - PASSA_PCT,
             None if s4 is None else s4 <= 1 - PASSA_PCT]
    return r


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
