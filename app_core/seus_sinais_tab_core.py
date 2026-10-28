# -*- coding: utf-8 -*-
"""A aba "SEUS SINAIS" -- a primeira do jogo (28/10/2026, pedido dele).

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


def render_seus_sinais_tab(*, st: Any, ctx: Mapping[str, Any]) -> None:
    from app_core.modelo_mercado_html_core import pagina
    from app_core.sinais_linha_core import chance, passam, sinais
    from app_core.suas_casas_core import CASAS_PADRAO, MARCAS, achar, carregar, chance_do_modelo
    confronto = ctx.get("confronto") or {}
    time_a, time_b = str(confronto.get("teamA") or ""), str(confronto.get("teamB") or "")
    tg = ctx.get("team_games")
    st.markdown("### Seus sinais · Total de kills")
    if not (time_a and time_b) or tg is None or getattr(tg, "empty", True):
        st.info("Abra um jogo (lista \"Jogos\" no topo) para ver os seus sinais.")
        return
    raiz = Path(ctx.get("raiz") or ".")
    # o seletor "Casas que voce usa" mora na aba Modelo x Mercado (a mesma chave nao pode
    # ter dois widgets); aqui so se le a escolha -- padrao Stake + Polymarket
    nomes = [n for _, n in MARCAS if n != "Pinnacle"]
    try:
        escolhidas = list(st.session_state.get("suas_casas_escolhidas") or [])
    except Exception:
        escolhidas = []
    escolhidas = [n for n in escolhidas if n in nomes] or [n for n in CASAS_PADRAO if n in nomes]
    doc = carregar(raiz)
    jogo, inv = achar(doc.get("jogos") or [], time_a, time_b, ctx.get("resolver_time"))
    linhas_casa = linhas_de_kills(jogo, inv, list(escolhidas or []))
    opcoes = sorted(linhas_casa)
    principal = linha_principal(linhas_casa)
    st.caption(f"**{time_a} × {time_b}** · casas: {', '.join(escolhidas)} (troque na aba Modelo × Mercado) · "
               + (f"{len(opcoes)} linha(s) de total de kills nas suas casas" if opcoes
                  else "as suas casas ainda não abriram total de kills para este jogo (OddsPapi, de 3 em 3 h)"))
    c1, c2 = st.columns([3, 1])
    with c1:
        escolha = None
        if opcoes:
            rot = {p: (_f(p) + (" ★" if p == principal else "")) for p in opcoes}
            escolha = st.radio("Linha", opcoes, index=opcoes.index(principal) if principal in opcoes else 0,
                               format_func=rot.get, horizontal=True, key=f"ss_linha_{time_a}_{time_b}")
    with c2:
        livre = st.number_input("Outra linha", min_value=0.0, max_value=80.0, step=1.0,
                                value=float(escolha if escolha is not None else 27.5), key=f"ss_livre_{time_a}_{time_b}")
    L = float(livre) if (escolha is None or abs(float(livre) - float(escolha)) > 1e-9) else float(escolha)
    modo = st.radio("Jogos considerados", ["Todos os mapas", "Só mapa 1"], horizontal=True,
                    key=f"ss_modo_{time_a}_{time_b}")
    so_m1 = modo == "Só mapa 1"
    sn = sinais(tg, time_a, time_b, L, so_mapa1=so_m1)
    # O MODELO DO CONFRONTO (29/10/2026, ele: "a pior parte e saber se NAQUELE CONFRONTO o
    # time vai ser over ou under"): o motor de totais cruza o quanto cada time mata com o
    # quanto deixa matar CONTRA este adversario. O total esperado = o ponto em que ele da
    # 50% para o Mais.
    _cache: dict = {}

    def _p_mod(x):
        try:
            return chance_do_modelo({"jogo": 1, "periodo": 1, "unidade": "kills", "tipo": "total", "lado": "over",
                                     "pontos": float(x)}, time_a=time_a, time_b=time_b,
                                    calcular_totais=ctx.get("calcular_totais"), prob_over=ctx.get("prob_over"),
                                    _cache=_cache)
        except Exception:
            return None
    p_mod = _p_mod(L)
    esperado = None
    if p_mod is not None:
        lo, hi = 5.0, 70.0
        for _ in range(30):
            mid = (lo + hi) / 2
            pm = _p_mod(mid)
            if pm is None:
                break
            lo, hi = (mid, hi) if pm > 0.5 else (lo, mid)
        esperado = (lo + hi) / 2
    if esperado is not None:
        st.markdown("**Para ESTE confronto, o modelo espera ~{} kills** (mapa 1) — {} da linha {}."
                    .format(_f(esperado), "acima" if esperado > L else "abaixo", _f(L)))
    odds_m1 = (linhas_casa.get(L) or {}).get(1) or {}
    corpo = html_painel(time_a, time_b, sn, odds_m1, p_mod)
    try:
        import streamlit.components.v1 as _cmp
        _cmp.html(pagina(corpo), height=640, scrolling=True)
    except Exception:
        st.markdown(corpo, unsafe_allow_html=True)
    st.caption("A FAVOR/CONTRA seguem as suas regras: 1) média recente do lado certo da linha; 2) a média "
               "ajustada pelos adversários enfrentados do lado certo; 3) 5, 20 e 10 jogos com 60%+ do lado (o ano "
               "só aparece); 4) no campeonato, a média dos dois do OUTRO lado até 30%. A chance é a do seu método, "
               "medida no histórico. **ENTRA** = 2 de 4 a favor e a casa paga acima da fair."
               + (" Só mapa 1: tudo com jogos de mapa 1 (menos jogos, mais ruído)." if so_m1 else ""))

    if linhas_casa:
        cache: Dict = {}

        def resumo(pts, mapa, lado):
            ch = (pts, lado)
            if ch not in cache:
                g = sinais(tg, time_a, time_b, pts)
                m = sinais(tg, time_a, time_b, pts, so_mapa1=True)
                if not g:
                    cache[ch] = None
                else:
                    pg = passam(g, lado)
                    cache[ch] = {"k": sum(1 for v in pg if v), "tot": sum(1 for v in pg if v is not None),
                                 "p": chance(g, lado),
                                 "k1m": None if not m else sum(1 for v in passam(m, lado) if v)}
            r = cache[ch]
            if not r:
                return None
            return dict(r, k1=r["k1m"] if mapa == 1 else None)
        st.markdown("#### Todas as linhas das suas casas")
        tab = html_todas(linhas_casa, resumo)
        n = tab.count("<tr>") - 1
        try:
            import streamlit.components.v1 as _cmp
            _cmp.html(pagina(tab), height=60 + 44 * max(n, 1), scrolling=n > 25)
        except Exception:
            st.markdown(tab, unsafe_allow_html=True)
