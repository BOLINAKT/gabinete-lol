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


def html_painel(time_a: str, time_b: str, L: float, sg: Optional[dict], s1: Optional[dict],
                odds_m1: Mapping[str, Any], p_modelo_over: Optional[float]) -> str:
    """A tabela grande: 4 sinais x (Geral Mais/Menos, So mapa 1 Mais/Menos). Pura."""
    from app_core.sinais_linha_core import chance, passam
    if not sg:
        return '<div class="nota">Poucos jogos recentes de um dos times para os sinais (mínimo 5 cada).</div>'
    pts = _f(L)
    cols = [("Geral", "over", sg), ("Geral", "under", sg), ("Só mapa 1", "over", s1), ("Só mapa 1", "under", s1)]
    a, b = sg["detalhe"]["a"], sg["detalhe"]["b"]
    det = {
        0: (f"{escape(time_a)} {a['acima']}/{a['n']} · {escape(time_b)} {b['acima']}/{b['n']} acima de {pts}"),
        1: (f"média {escape(time_a)} {_f(a['media'])} · {escape(time_b)} {_f(b['media'])} → "
            f"{_f(sg['media'])} ({'+' if sg['media'] >= L else ''}{_f(sg['media'] - L)} vs {pts})"),
        2: (f"ajustado: {escape(time_a)} {a['acima_aj']}/{a['n']} (adv. {'+' if a['adv'] >= 0 else ''}{_f(a['adv'])}) · "
            f"{escape(time_b)} {b['acima_aj']}/{b['n']} (adv. {'+' if b['adv'] >= 0 else ''}{_f(b['adv'])})"),
        3: (f"{escape(time_a)} {a['camp_acima']}/{a['camp_n']} ({escape(a['camp_rotulo'])}) · "
            f"{escape(time_b)} {b['camp_acima']}/{b['camp_n']} ({escape(b['camp_rotulo'])})"),
    }
    nomes = ("Histórico", "Médias", "Adversário", "StatsCamps")
    corpo = ""
    for i, nome in enumerate(nomes):
        celulas = ""
        for j, (_, lado, sn) in enumerate(cols):
            v = None if not sn else passam(sn, lado)[i]
            celulas += f'<td class="{"g" if j in (0, 2) else ""}">{_marca(v)}</td>'
        corpo += f'<tr><td class="n">{nome}</td><td class="d">{det[i]}</td>{celulas}</tr>'
    # totais
    ks, fairs, vals, ver, casas = [], [], [], [], []
    for j, (_, lado, sn) in enumerate(cols):
        k = 0 if not sn else sum(1 for v in passam(sn, lado) if v)
        tot = 0 if not sn else sum(1 for v in passam(sn, lado) if v is not None)
        p = chance(sg, lado)                       # a fair do veredito e a GERAL (ver o topo)
        oc = odds_m1.get(lado)
        val = None if (p is None or not oc) else (p * oc[0] - 1) * 100
        ks.append(f'<span class="{"k2" if k >= 2 else "k0"}">{k}/{tot}</span>')
        fairs.append("-" if not p else _f(1 / p, 2))
        casas.append("-" if not oc else f'{_f(oc[0], 2)} <span class="num">{escape(oc[1])}</span>')
        vals.append("-" if val is None else f'<span class="{"vb" if val > 0 else "vr"}">{"+" if val > 0 else ""}{_f(val)}%</span>')
        vr = veredito(k, val)
        ver.append(f'<span class="ent">{vr}</span>' if vr == VEREDITO_ENTRA
                   else f'<span class="{"meio" if k >= 2 else "nao"}">{vr}</span>')
    def linha(rot, xs, cls=""):
        return (f'<tr class="{cls}"><td class="n">{rot}</td><td class="d"></td>'
                + "".join(f'<td class="{"g" if j in (0, 2) else ""}">{x}</td>' for j, x in enumerate(xs)) + "</tr>")
    mod = []
    for _, lado, _ in cols:
        mod.append("-" if p_modelo_over is None else _f(1 / (p_modelo_over if lado == "over" else 1 - p_modelo_over), 2))
    corpo += linha("SINAIS", ks, "tot")
    corpo += linha("Fair do conjunto", fairs)
    corpo += linha("Fair do modelo", mod)
    corpo += linha("Melhor odd (mapa 1)", casas)
    corpo += linha("Vantagem", vals)
    corpo += linha("VEREDITO", ver, "tot")
    cab = ('<tr><th rowspan="2" style="text-align:left">Sinal</th><th rowspan="2" style="text-align:left">'
           'O número por trás <span class="num">(geral: últimos 10 de cada time)</span></th><th class="g" colspan="2">GERAL</th><th class="g" colspan="2">SÓ MAPA 1</th></tr>'
           f'<tr><th class="g">Mais {pts}</th><th>Menos {pts}</th><th class="g">Mais {pts}</th><th>Menos {pts}</th></tr>')
    return CSS_SINAIS + f'<table class="ss">{cab}{corpo}</table>'


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
    sg = sinais(tg, time_a, time_b, L)
    s1 = sinais(tg, time_a, time_b, L, so_mapa1=True)
    p_mod = None
    try:
        p_mod = chance_do_modelo({"jogo": 1, "periodo": 1, "unidade": "kills", "tipo": "total", "lado": "over",
                                  "pontos": L}, time_a=time_a, time_b=time_b,
                                 calcular_totais=ctx.get("calcular_totais"), prob_over=ctx.get("prob_over"))
    except Exception:
        p_mod = None
    odds_m1 = (linhas_casa.get(L) or {}).get(1) or {}
    corpo = html_painel(time_a, time_b, L, sg, s1, odds_m1, p_mod)
    try:
        import streamlit.components.v1 as _cmp
        _cmp.html(pagina(corpo), height=470, scrolling=False)
    except Exception:
        st.markdown(corpo, unsafe_allow_html=True)
    st.caption("✓ passa · ✗ não passa · · sem dado. Passa: Histórico e Adversário com 60%+ dos 20 jogos do lado; "
               "Médias com 1 kill de folga; StatsCamps com 60%+ no campeonato. **Veredito**: 2 de 4 e a casa paga "
               "acima da fair do conjunto → ENTRA. A fair é a GERAL (mais certeira que a só-mapa-1 na medição); "
               "o \"só mapa 1\" mostra os sinais com jogos de mapa 1.")

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
