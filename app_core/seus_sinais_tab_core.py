# -*- coding: utf-8 -*-
"""OS PASSOS DELE no total de kills -- o painel da Analise de Linha (28-29/10/2026).

Foi a aba "Seus sinais" (28/10); em 29/10 ele pediu o painel dentro da Analise de Linha.

Ele: "isso dai e basicamente TUDO o que eu vejo... comecar por ela". Para o total
de kills do confronto aberto:
  - as linhas que as casas DELE (Stake, Polymarket) abriram, com troca rapida, e
    uma linha livre;
  - os 4 sinais (Historico, Medias, Adversario, StatsCamps) com o NUMERO por tras
    e separado por time, para Mais e Menos, no geral e so no mapa 1;
  - a fair do conjunto, a do modelo, a odd da casa e o veredito no criterio dele:
    2 de 4 passam e a casa paga acima da fair do conjunto -> ENTRA.
  - embaixo, todas as linhas das casas dele com o mesmo veredito.

A FAIR DO VEREDITO E A GERAL. Medido nas linhas de kills da Pinnacle (496, 140
partidas, 28/10/2026): conjunto 0,692 x modelo 0,699 x Pinnacle 0,690 de logloss
(conjunto a frente do modelo, nao conclusivo); nas linhas de mapa 1 a fair "so
mapa 1" errou MAIS que a geral (0,684 x 0,660) -- recorte de poucos jogos. O
"so mapa 1" fica como leitura dos sinais, nao como preco.
"""
from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

VEREDITO_ENTRA = "ENTRA"


def _f(x: Any, casas: int = 1) -> str:
    try:
        return f"{float(x):.{casas}f}".replace(".", ",")
    except (TypeError, ValueError):
        return "-"


def linhas_de_kills(jogo: Optional[Mapping[str, Any]], inv: bool, casas: List[str]) -> Dict[float, Dict]:
    """{pontos: {mapa: {"over": (odd, casa), "under": (odd, casa)}}} -- a MELHOR odd de cada
    lado entre as casas escolhidas. Pura."""
    from app_core.suas_casas_core import linhas_de_mapa
    if not jogo:
        return {}
    fora: Dict[float, Dict] = {}
    for l in linhas_de_mapa(jogo, inv, "lol", casas_dele=casas):
        if l["unidade"] != "kills" or l["tipo"] != "total" or l["slug"] == "pinnacle":
            continue
        cel = fora.setdefault(float(l["pontos"]), {}).setdefault(int(l["periodo"]), {})
        atual = cel.get(l["lado"])
        if atual is None or l["odd"] > atual[0]:
            cel[l["lado"]] = (float(l["odd"]), l["casa_aposta"])
    return fora


def linha_principal(linhas: Dict[float, Dict]) -> Optional[float]:
    """A linha mais equilibrada do mapa 1 (a "linha da casa"); sem mapa 1, de qualquer mapa."""
    melhor, dif = None, 99.0
    for pts, mapas in linhas.items():
        for mapa in sorted(mapas, key=lambda m: (m != 1, m)):
            ou = mapas[mapa]
            if "over" in ou and "under" in ou:
                d = abs(ou["over"][0] - ou["under"][0]) + (0 if mapa == 1 else 0.5)
                if d < dif:
                    melhor, dif = pts, d
                break
    return melhor


def veredito(k: int, valor: Optional[float]) -> str:
    if k >= 2 and valor is not None and valor > 0:
        return VEREDITO_ENTRA
    if k >= 2:
        return "2+ sinais, odd abaixo da fair"
    return "não entra"


def _marca(v: Optional[bool]) -> str:
    if v is None:
        return '<span class="sx">·</span>'
    return '<span class="sv">✓</span>' if v else '<span class="sn">✗</span>'


CSS_SINAIS = """
<style>
  .ss { width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; background:var(--painel);
        border:1px solid var(--borda); border-top:3px solid var(--boa); border-radius:12px; overflow:hidden; }
  .ss th { background:var(--cab); font-size:12px; padding:8px; text-align:center; }
  .ss th.g { border-left:2px solid var(--borda); }
  .ss td { border-top:1px solid var(--linha); padding:7px 8px; text-align:center; vertical-align:middle; }
  .ss td.n { text-align:left; font-weight:700; white-space:nowrap; }
  .ss td.d { text-align:left; color:var(--fraco); font-size:12px; line-height:1.45; }
  .ss td.g { border-left:2px solid var(--borda); }
  .ss .sv { color:var(--boa); font-weight:800; font-size:16px; }
  .ss .sn { color:var(--ruim); font-weight:800; font-size:16px; }
  .ss .sx { color:var(--fraco); }
  .ss .num { display:block; font-size:11.5px; color:var(--fraco); }
  .ss tr.tot td { background:var(--cab); font-weight:800; }
  .ss .k2 { color:var(--boa); font-size:17px; } .ss .k0 { color:var(--fraco); font-size:17px; }
  .ss .ent { color:#0e1117; background:var(--boa); border-radius:7px; padding:3px 9px; font-weight:800; }
  .ss .meio { color:var(--pin); font-weight:700; font-size:12px; }
  .ss .nao { color:var(--fraco); font-size:12px; }
  .ss .vb { color:var(--boa); font-weight:800; } .ss .vr { color:var(--ruim); font-weight:800; }
</style>
"""


# O que o historico mostrou para cada numero de passos a favor (cego 2026, metodo.py)
BATEU_NO_HISTORICO = {"over": {0: 38, 1: 46, 2: 54, 3: 61, 4: 68},
                      "under": {0: 43, 1: 53, 2: 60, 3: 64, 4: 67}}
REFERENCIA = 0.58                 # a dele: 1,72 (58%) / 1,67 (60%)


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def _adv(x: float) -> str:
    rot = ("pegou adversários <b>over</b>" if x > 0.5 else "pegou adversários <b>under</b>" if x < -0.5
           else "pegou adversários na média")
    return f"{rot} ({'+' if x >= 0 else ''}{_f(x)})"


def passos_do_lado(sn: dict, lado: str, time_a: str, time_b: str) -> List[Dict[str, Any]]:
    """Os 4 passos dele, em frases, para 'over' (Mais) ou 'under' (Menos). Pura."""
    from app_core.sinais_linha_core import JANELAS, PASSA_HIST, TETO_OUTRO_LADO, passam
    L = sn["linha"]
    mais = lado == "over"
    a, b = sn["a"], sn["b"]
    ok = passam(sn, lado)
    ta, tb = escape(time_a), escape(time_b)
    pos = "acima" if mais else "abaixo"
    contra = "abaixo" if mais else "acima"
    # 1. medias
    lado_med = "acima" if sn["media"] > L else "abaixo"
    t1 = (f"Média recente <b>{_f(sn['media'])}</b> ({ta} {_f(a['media'])} · {tb} {_f(b['media'])}) — "
          f"<b>{lado_med}</b> de {_f(L)}.")
    # 2. adversario
    det = f"{ta} {_adv(a['adv'])} · {tb} {_adv(b['adv'])}. Ajustada: <b>{_f(sn['media_aj'])}</b>"
    if ok[0] and ok[1]:
        t2 = f"Média já a favor e o ajuste confirma. {det}."
    elif ok[0]:
        t2 = f"Média a favor, MAS só por causa dos adversários. {det} — {contra} da linha."
    elif ok[1]:
        t2 = f"Média contra, MAS os adversários explicam. {det} — {pos} da linha."
    else:
        t2 = f"Média contra e os adversários confirmam. {det} — a leitura não se sustenta."
    # 3. historico 5 / 20 / 10 / ano
    partes = []
    for n in JANELAS:
        x = a["janelas"][n][0] + b["janelas"][n][0]
        tot = a["janelas"][n][1] + b["janelas"][n][1]
        k = x if mais else tot - x
        r = k / tot if tot else 0
        partes.append(f'{n} jogos <span class="{"vb" if r >= PASSA_HIST else "vr"}">{k}/{tot}</span>')
    ax, an = a["ano"][0] + b["ano"][0], a["ano"][1] + b["ano"][1]
    ka = ax if mais else an - ax

    def _cinco(t):
        x, n = t["janelas"][5]
        return f"{x if mais else n - x}/{n}"
    t3 = (" · ".join(partes) + f' · ano {ka}/{an} <span class="num" style="display:inline">(só referência)</span>'
          f'<span class="num">últimos 5: {ta} {_cinco(a)} · {tb} {_cinco(b)}</span>')
    # 4. stats da linha
    if sn.get("camp_mais") is None:
        t4 = "Pouco jogo no campeonato (mínimo 3 de cada)."
    else:
        def _outro(t):
            x, n = t["camp"]
            return (n - x) / n if mais else x / n
        oa, ob = _outro(a), _outro(b)
        m = (oa + ob) / 2
        t4 = (f"Outro lado ({'Menos' if mais else 'Mais'}): {ta} {_pct(oa)} · {tb} {_pct(ob)} → média "
              f"<b>{_pct(m)}</b> {'≤' if m <= TETO_OUTRO_LADO else '>'} 30%"
              f'<span class="num">{escape(a["camp_rotulo"])} · {escape(b["camp_rotulo"])}</span>')
    return [{"nome": "1. Médias", "ok": ok[0], "txt": t1}, {"nome": "2. Adversário", "ok": ok[1], "txt": t2},
            {"nome": "3. Histórico (5 · 20 · 10)", "ok": ok[2], "txt": t3},
            {"nome": "4. Stats da linha", "ok": ok[3], "txt": t4}]


def _coluna(sn: dict, lado: str, time_a: str, time_b: str, odd: Any, p_mod: Optional[float]) -> str:
    from app_core.sinais_linha_core import chance
    passos = passos_do_lado(sn, lado, time_a, time_b)
    k = sum(1 for x in passos if x["ok"])
    p = chance(sn, lado)
    linhas = ""
    for x in passos:
        if x["ok"]:
            st_ = '<span class="fav">A FAVOR</span>'
        elif x["ok"] is None:
            st_ = '<span class="sx">sem dado</span>'
        else:
            st_ = '<span class="con">CONTRA</span>'
        linhas += f'<div class="passo"><div class="pn">{x["nome"]} {st_}</div><div class="pt">{x["txt"]}</div></div>'
    val = None if (p is None or not odd) else (p * odd[0] - 1) * 100
    vr = veredito(k, val)
    bat = BATEU_NO_HISTORICO[lado].get(k)
    nome_lado = "Mais" if lado == "over" else "Menos"
    ref = "" if p is None else (' <span class="vb">≥ 58%</span>' if p >= REFERENCIA
                                else ' <span class="nao">abaixo de 58%</span>')
    mod = "-" if p_mod is None else _f(1 / (p_mod if lado == "over" else 1 - p_mod), 2)
    vtxt = "" if val is None else f' → <span class="{"vb" if val > 0 else "vr"}">{"+" if val > 0 else ""}{_f(val)}%</span>'
    otxt = "-" if not odd else f"{_f(odd[0], 2)}</b> {escape(odd[1])}<b>"
    vd = (f'<span class="ent">{vr}</span>' if vr == VEREDITO_ENTRA
          else f'<span class="{"meio" if k >= 2 else "nao"}">{vr}</span>')
    res = (f'<div class="res"><div class="rk {"k2" if k >= 2 else "k0"}">{k} de 4 a favor</div>'
           f'<div class="num">no histórico, com {k} de 4 o {nome_lado} bateu {bat}%</div>'
           f'<div class="rl">Chance pelo seu método <b>{"-" if p is None else _pct(p)}</b>'
           f' · fair <b>{"-" if not p else _f(1 / p, 2)}</b>{ref}</div>'
           f'<div class="rl">Modelo: fair {mod}</div>'
           f'<div class="rl">Melhor odd (mapa 1): <b>{otxt}</b>{vtxt}</div>'
           f'<div class="vd">{vd}</div></div>')
    titulo = "MENOS" if lado == "under" else "MAIS"
    return f'<div class="col"><div class="ct">{titulo} {_f(sn["linha"])}</div>{linhas}{res}</div>'


CSS_PASSOS = """
<style>
  .cols { display:flex; gap:14px; flex-wrap:wrap; }
  .col { flex:1 1 380px; background:var(--painel); border:1px solid var(--borda); border-radius:12px; overflow:hidden; }
  .ct { background:var(--cab); font-weight:800; font-size:15px; padding:9px 12px; letter-spacing:.04em; }
  .passo { padding:8px 12px; border-top:1px solid var(--linha); }
  .pn { font-weight:700; font-size:13px; display:flex; gap:8px; align-items:center; }
  .pt { color:var(--texto); font-size:12.5px; line-height:1.5; margin-top:3px; }
  .fav { color:#0e1117; background:var(--boa); border-radius:6px; padding:0 7px; font-size:11px; font-weight:800; }
  .con { color:#fff; background:var(--ruim); border-radius:6px; padding:0 7px; font-size:11px; font-weight:800; }
  .sx { color:var(--fraco); font-size:11px; }
  .num { display:block; color:var(--fraco); font-size:11.5px; }
  .vb { color:var(--boa); font-weight:800; } .vr { color:var(--ruim); font-weight:800; }
  .res { border-top:2px solid var(--borda); padding:10px 12px; background:var(--cab); }
  .rk { font-size:18px; font-weight:800; } .k2 { color:var(--boa); } .k0 { color:var(--fraco); }
  .rl { font-size:13px; margin-top:3px; }
  .vd { margin-top:8px; }
  .ent { color:#0e1117; background:var(--boa); border-radius:7px; padding:3px 10px; font-weight:800; }
  .meio { color:var(--pin); font-weight:700; } .nao { color:var(--fraco); font-weight:700; }
</style>
"""


def html_painel(time_a: str, time_b: str, sn: Optional[dict], odds_m1: Mapping[str, Any],
                p_modelo_over: Optional[float]) -> str:
    """As duas colunas (Menos | Mais) com os 4 passos dele em frases. Pura."""
    if not sn:
        return '<div class="nota">Poucos jogos de um dos times para os seus passos (mínimo 5 cada).</div>'
    return CSS_PASSOS + '<div class="cols">' + "".join(
        _coluna(sn, lado, time_a, time_b, odds_m1.get(lado), p_modelo_over) for lado in ("under", "over")) + "</div>"


def html_todas(linhas_casa: Dict[float, Dict], resumo: Callable[[float, int, str], Optional[dict]]) -> str:
    """Todas as linhas das casas dele com o veredito; ENTRA primeiro. Pura (com `resumo` de fora)."""
    rows = []
    for pts, mapas in linhas_casa.items():
        for mapa, ou in mapas.items():
            for lado in ("over", "under"):
                if lado not in ou:
                    continue
                r = resumo(pts, mapa, lado)
                if not r:
                    continue
                val = None if r["p"] is None else (r["p"] * ou[lado][0] - 1) * 100
                rows.append({"pts": pts, "mapa": mapa, "lado": lado, "odd": ou[lado][0], "casa": ou[lado][1],
                             "k": r["k"], "k1": r.get("k1"), "tot": r["tot"], "p": r["p"], "val": val,
                             "ver": veredito(max(r["k"], r.get("k1") or 0), val)})
    if not rows:
        return ""
    ordem = {VEREDITO_ENTRA: 0, "2+ sinais, odd abaixo da fair": 1, "não entra": 2}
    rows.sort(key=lambda x: (ordem[x["ver"]], -(x["val"] if x["val"] is not None else -999), x["mapa"], x["pts"]))
    corpo = ""
    for x in rows:
        ver = (f'<span class="ent">{x["ver"]}</span>' if x["ver"] == VEREDITO_ENTRA
               else f'<span class="{"meio" if x["ver"] != "não entra" else "nao"}">{x["ver"]}</span>')
        k1 = "-" if x["k1"] is None else f'<span class="{"k2" if x["k1"] >= 2 else "k0"}">{x["k1"]}/4</span>'
        corpo += (f'<tr><td>Mapa {x["mapa"]}</td><td class="n">{"Mais" if x["lado"] == "over" else "Menos"} '
                  f'{_f(x["pts"])}</td><td>{_f(x["odd"], 2)} <span class="num">{escape(x["casa"])}</span></td>'
                  f'<td><span class="{"k2" if x["k"] >= 2 else "k0"}">{x["k"]}/{x["tot"]}</span></td><td>{k1}</td>'
                  f'<td>{"-" if not x["p"] else _f(1 / x["p"], 2)}</td>'
                  f'<td>{"-" if x["val"] is None else ("<span class=vb>+" if x["val"] > 0 else "<span class=vr>") + _f(x["val"]) + "%</span>"}</td>'
                  f'<td>{ver}</td></tr>')
    return (CSS_SINAIS + '<table class="ss"><tr><th>Mapa</th><th style="text-align:left">Aposta</th><th>Melhor odd</th>'
            '<th>Sinais (geral)</th><th>Só mapa 1</th><th>Fair do conjunto</th><th>Vantagem</th><th>Veredito</th></tr>'
            + corpo + '</table>')


# ---- O PAINEL DENTRO DA ANALISE DE LINHA (29/10/2026) --------------------------------
# Ele: "joga so essa tela para a analise de linha, e nao precisa mais dessa aba". E
# "quando eu troco de linha, ele nao muda" -- o campo "Outra linha" da aba prendia o
# valor. Aqui a linha e a que ele ja escolhe na Analise de Linha.
_CACHE_MODELO: Dict[Any, Any] = {}


def _modelo_do_confronto(tg: Any, time_a: str, time_b: str):
    """Os totais esperados do confronto pelo motor do app (mapa 1, meia-vida 180), ou None."""
    chave = (id(tg), len(tg), time_a, time_b)
    if chave not in _CACHE_MODELO:
        try:
            from app_core.runtime_wrappers_core import _expected_totals_dc
            from mlcore.lines_engine import Filters, build_profile
            f = Filters(year=None, league=None, split=None, playoffs=None)
            pa = build_profile(tg, team=time_a, filters=f, league_mode="all", map_mode="m1",
                               half_life_days=180.0, max_games=None)
            pb = build_profile(tg, team=time_b, filters=f, league_mode="all", map_mode="m1",
                               half_life_days=180.0, max_games=None)
            _CACHE_MODELO.clear()
            _CACHE_MODELO[chave] = _expected_totals_dc(tg, pa, pb) if (pa.n_games and pb.n_games) else None
        except Exception:
            _CACHE_MODELO[chave] = None
    t = _CACHE_MODELO.get(chave)
    return None if not t else t.get("kills")


def _odds_da_linha(tg: Any, time_a: str, time_b: str, L: float) -> Dict[str, Any]:
    """A melhor odd de Mais/Menos do MAPA 1 nas casas dele, para a linha L."""
    import json
    from app_core.schedule_import_core import resolve_schedule_team
    from app_core.suas_casas_core import CASAS_PADRAO, achar, carregar
    raiz = Path(__file__).resolve().parents[1]
    try:
        apelidos = json.loads((raiz / "user_team_aliases.json").read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        apelidos = {}
    times = sorted({str(x) for x in tg["team"].dropna().unique()})

    def _res(n):
        r = resolve_schedule_team(str(n or ""), times, apelidos)
        return r[0] if r[1] else n
    jogo, inv = achar(carregar(raiz).get("jogos") or [], time_a, time_b, _res)
    try:
        import streamlit as _st
        casas = list(_st.session_state.get("suas_casas_escolhidas") or []) or list(CASAS_PADRAO)
    except Exception:
        casas = list(CASAS_PADRAO)
    return (linhas_de_kills(jogo, inv, casas).get(float(L)) or {}).get(1) or {}


def render_painel_na_analise(*, st: Any, tg: Any, time_a: str, time_b: str, linha: float, chave: str) -> None:
    """Os passos dele (Menos | Mais) para a linha da Analise de Linha. So LoL, total de kills."""
    from app_core.modelo_mercado_html_core import pagina
    from app_core.sinais_linha_core import sinais
    L = float(linha)
    modo = st.radio("Seus passos com", ["Todos os mapas", "Só mapa 1"], horizontal=True, key=f"ss_modo_{chave}")
    sn = sinais(tg, time_a, time_b, L, so_mapa1=(modo == "Só mapa 1"))
    total = _modelo_do_confronto(tg, time_a, time_b)
    p_mod, esperado = None, None
    if total is not None:
        try:
            from mlcore.lines_engine import prob_over_from_total
            p_mod = float(prob_over_from_total(total, L))
            lo, hi = 5.0, 70.0
            for _ in range(30):
                mid = (lo + hi) / 2
                lo, hi = (mid, hi) if float(prob_over_from_total(total, mid)) > 0.5 else (lo, mid)
            esperado = (lo + hi) / 2
        except Exception:
            p_mod = esperado = None
    if esperado is not None:
        st.markdown("**Para ESTE confronto, o modelo espera ~{} kills** (mapa 1) — {} da linha {}."
                    .format(_f(esperado), "acima" if esperado > L else "abaixo", _f(L)))
    corpo = html_painel(time_a, time_b, sn, _odds_da_linha(tg, time_a, time_b, L), p_mod)
    try:
        import streamlit.components.v1 as _cmp
        _cmp.html(pagina(corpo), height=600, scrolling=True)
    except Exception:
        st.markdown(corpo, unsafe_allow_html=True)
