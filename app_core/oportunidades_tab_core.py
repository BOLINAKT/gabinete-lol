# -*- coding: utf-8 -*-
"""A aba que mostra onde a casa paga mais do que o modelo acha que vale.

O PEDIDO DELE, com as palavras dele (15/09/2026):
    "dai eu nao vou precisar mais ficar colocando linha, tu vai pegar a linha
     desses sites e ja procurar a melhor linha para mim"
e, sobre o formato: SO ONDE HA VANTAGEM, ordenado pela vantagem.

O QUE ESTA TELA NAO FAZ, E POR QUE ISSO APARECE NELA
Ela precifica TOTAIS por mapa (kills e, quando a casa abrir, torre, dragao,
barao, inibidor). Ela NAO precifica vencedor, placar exato, total de mapas nem
handicap -- isso vem do modelo de vencedor, que hoje so e chamavel de dentro
do fluxo de um confronto, com dezenas de regulagens da barra lateral. Ligar
isso aqui por um atalho criaria um SEGUNDO numero para a mesma pergunta, e
este projeto ja tem historia com isso.

Entao a tela DIZ quantas linhas ficaram de fora e por que, mercado por
mercado. Uma tela que mostra tres apostas e cala duzentas parece completa e
nao e -- foi exatamente esse tipo de silencio que segurou kills por horas.

NADA AQUI VAI A REDE. Le-se o arquivo que o robo gravou.
"""
from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from app_core.odds_coletadas_core import carregar_odds_coletadas
from app_core.oportunidades_core import (
    JOGOS_MINIMOS,
    VANTAGEM_MINIMA_PCT,
    bo_bate,
    mesmo_confronto,
    montar_oportunidades,
    prob_do_vencedor,
)

# Quanto de vantagem a tela oferece filtrar. Comeca em 1%: abaixo disso a
# diferenca cabe dentro do erro do proprio modelo.
OPCOES_DE_CORTE = (0.0, 1.0, 3.0, 5.0, 10.0)


def _fmt(v: Any, casas: int = 2, sufixo: str = "") -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if f != f:
        return "—"
    return "{:.{}f}{}".format(f, int(casas), sufixo)


def _linha_do_jogo(a: Mapping[str, Any]) -> str:
    return "{} x {}".format(a.get("casa") or "?", a.get("fora") or "?")


def _descricao_da_aposta(a: Mapping[str, Any]) -> str:
    """"kills do mapa 1 acima de 31,5" -- em vez do jargao da casa."""
    if str(a.get("metrica") or "") == "vencedor":
        lado = str(a.get("lado") or "").lower()
        quem = a.get("casa") if lado == "home" else a.get("fora")
        return "{} vencer ({})".format(quem, a.get("mercado") or "vencedor")
    lado = str(a.get("lado") or "").lower()
    palavra = "acima de" if lado == "over" else "abaixo de"
    metrica = {"kills": "kills", "towers": "torres", "dragons": "dragoes",
               "barons": "baroes", "inhibitors": "inibidores"}.get(
                   str(a.get("metrica") or ""), str(a.get("metrica") or ""))
    mapa = str(a.get("mapa") or "")
    nmapa = mapa[1:] if mapa.startswith("m") else mapa
    ponto = _fmt(a.get("pontos"), 1).replace(".", ",")
    return "{} do mapa {} {} {}".format(metrica, nmapa, palavra, ponto)


def render_oportunidades_tab(*, st: Any, ctx: Mapping[str, Any]) -> None:
    """Desenha a aba. `ctx` traz o caminho de PRODUCAO, nunca uma copia dele."""
    raiz: Path = Path(ctx.get("raiz") or ".")
    calcular_totais: Callable[..., Any] = ctx["calcular_totais"]
    prob_over: Callable[..., Any] = ctx["prob_over"]
    jogos_por_time = ctx.get("jogos_por_time")
    nao_casados: List[str] = list(ctx.get("times_nao_casados") or [])
    confronto: Mapping[str, Any] = ctx.get("confronto") or {}
    resolver: Optional[Callable[[str], str]] = ctx.get("resolver_time")

    st.markdown("### Onde a Pinnacle paga mais do que o modelo acha que vale")

    odds = carregar_odds_coletadas(raiz)
    if odds.get("motivo"):
        st.info("Sem odds para comparar: {}.".format(odds["motivo"]))
        st.caption("Quem coleta e o robo do GitHub, de 3 em 3 horas. "
                   "O app nunca vai ao site da casa.")
        return

    idade = odds.get("idade_horas")
    carimbo = "lido ha {} ({})".format(
        "menos de 1 hora" if (idade is not None and idade < 1) else _fmt(idade, 1, " horas"),
        odds.get("lido_em") or "sem carimbo")
    if odds.get("velha"):
        st.warning("Estas odds tem {}. Preco de aposta muda: confira na casa "
                   "antes de apostar.".format(_fmt(idade, 1, " horas")))
    else:
        st.caption(carimbo)

    _jogos_que_dao = _diagnostico_do_confronto(st, odds, confronto, resolver)

    corte = st.selectbox(
        "Mostrar a partir de qual vantagem",
        OPCOES_DE_CORTE,
        index=list(OPCOES_DE_CORTE).index(VANTAGEM_MINIMA_PCT),
        format_func=lambda v: "tudo" if v <= 0 else "+{:.0f}% ou mais".format(v),
        key="oportunidades_corte",
    )

    _vencedor = _montar_prob_de_vencedor(st, confronto, resolver)
    r = montar_oportunidades(odds, calcular_totais, prob_over=prob_over,
                             minimo_pct=float(corte), jogos_por_time=jogos_por_time,
                             prob_de_vencedor=_vencedor)

    achados = r.get("achados") or []
    if achados:
        st.markdown("#### {} aposta(s) com vantagem".format(len(achados)))
        for a in achados:
            _cartao(st, a)
    elif _jogos_que_dao:
        st.info("Nenhuma aposta com vantagem de {}% ou mais nas linhas que "
                "este painel sabe precificar.".format(_fmt(corte, 0)))

    _o_que_ficou_de_fora(st, r, nao_casados)


def _diagnostico_do_confronto(st: Any, odds: Mapping[str, Any],
                              confronto: Mapping[str, Any],
                              resolver: Optional[Callable[[str], str]]) -> bool:
    """Diz POR QUE a tela pode estar vazia, em vez de deixar ele adivinhar.

    ELE PERGUNTOU DUAS VEZES (16/09/2026): "nao entendi, ate agora porque nao
    esta mostrando nada, voce nao disse que ja estava conseguindo pegar pelo
    menos as odds dos ml's?".

    A resposta era simples e a tela nao dava: o confronto que ele tinha aberto
    era eSuba x Meavedron, do Hitpoint Masters -- e a Pinnacle NAO OFERECE
    Hitpoint Masters. Nao havia o que comparar.

    So que a tela dizia "nenhuma aposta com vantagem", que soa como "procurei
    e nao achei nada bom". Sao coisas MUITO diferentes para quem vai apostar,
    e viraram a mesma frase. Agora ela diz qual e o confronto aberto, se a
    casa tem esse jogo, e QUAIS jogos ela tem -- que e a informacao que
    resolve: basta abrir um deles.

    Devolve True quando havia como precificar alguma coisa.
    """
    jogos = [j for j in (odds.get("jogos") or []) if isinstance(j, dict)]
    time_a = str((confronto or {}).get("teamA") or "")
    time_b = str((confronto or {}).get("teamB") or "")

    if not (time_a and time_b):
        st.info("Escolha um confronto e clique em **Analisar Confronto**. "
                "O mercado de vencedor e comparado para o confronto aberto.")
        _listar_o_que_a_casa_tem(st, jogos)
        return False

    achou = None
    if resolver is not None:
        for j in jogos:
            if mesmo_confronto(j, time_a, time_b, resolver) is not None:
                achou = j
                break

    if achou is None:
        st.warning(
            "O confronto aberto (**{} x {}**) nao esta na Pinnacle, entao nao "
            "ha odd dela para comparar. Ela cobre poucas ligas.".format(
                time_a, time_b))
        _listar_o_que_a_casa_tem(st, jogos)
        return False

    st.caption("Comparando o confronto aberto: **{} x {}** (BO{} na casa).".format(
        achou.get("casa"), achou.get("fora"), achou.get("bo")))
    return True


def _listar_o_que_a_casa_tem(st: Any, jogos: List[Mapping[str, Any]]) -> None:
    """Os jogos que a casa oferece. Abrir um deles e o que resolve."""
    if not jogos:
        st.caption("A ultima coleta nao trouxe jogo nenhum da Pinnacle.")
        return
    st.caption("Jogos que a Pinnacle oferece nesta leitura -- abra um deles "
               "para o painel ter o que comparar:")
    for j in jogos:
        st.caption("· {} — {} x {} (BO{})".format(
            j.get("liga"), j.get("casa"), j.get("fora"), j.get("bo")))


def _montar_prob_de_vencedor(st: Any, confronto: Mapping[str, Any],
                             resolver: Optional[Callable[[str], str]]):
    """A odd justa do VENCEDOR, vinda do confronto aberto na tela.

    ELE ESTRANHOU a aba mostrando zero: "nao faz mt sentido". Tinha razao --
    o numero ja existe. O card do confronto mostra, por exemplo, MD5 1,66 x
    2,51. Faltava traze-lo ate aqui.

    NAO SE RECALCULA NADA. O `p_map`/`p_series` sao os MESMOS que ele ve no
    card; o projeto ja teve tres implementacoes do pre-jogo com contagens
    diferentes, e nao vai ganhar uma quarta.

    Por isso so vale para o confronto ABERTO -- e o unico para o qual o app
    calculou o numero. Se nenhum jogo da casa for esse confronto, a tela diz
    isso em vez de ficar calada.
    """
    if not confronto or resolver is None:
        return None
    time_a = str(confronto.get("teamA") or "")
    time_b = str(confronto.get("teamB") or "")
    p_map = confronto.get("p_map")
    p_series = confronto.get("p_series")
    bo_tela = confronto.get("bo")
    if not (time_a and time_b):
        return None

    avisado = {"bo": False}

    def _prob(jogo, linha):
        lado_certo = mesmo_confronto(jogo, time_a, time_b, resolver)
        if lado_certo is None:
            return None
        if not bo_bate(jogo, bo_tela):
            # UM BO5 PRECIFICADO COMO BO3 muda a probabilidade da serie
            # inteira. Fica de fora, e dito uma vez.
            if not avisado["bo"]:
                avisado["bo"] = True
                st.warning(
                    "A casa oferece este confronto em BO{} e a tela esta em "
                    "BO{}. O mercado de vencedor da serie ficou de fora: o "
                    "formato muda a probabilidade.".format(
                        jogo.get("bo"), bo_tela))
            try:
                if int(linha.get("periodo", 0) or 0) == 0:
                    return None
            except (TypeError, ValueError):
                return None
        return prob_do_vencedor(linha, p_map=p_map, p_series=p_series,
                                casa_e_time_a=bool(lado_certo))

    return _prob


def _cartao(st: Any, a: Mapping[str, Any]) -> None:
    """Um achado. O aviso vem ANTES do numero, nao depois."""
    avisos = []
    if a.get("suspeito"):
        avisos.append("vantagem grande demais para ser verdade — a Pinnacle abre "
                      "com ~5% de margem; desconfie do modelo antes da casa")
    if a.get("dados_finos"):
        avisos.append("poucos jogos no historico ({}) — conta fina".format(
            a.get("jogos_no_historico")))

    st.markdown(
        "**{:+.2f}%**  ·  {}  ·  _{}_".format(
            float(a.get("vantagem_pct") or 0.0),
            escape(_descricao_da_aposta(a)),
            escape(_linha_do_jogo(a))))
    st.caption("casa paga {} · justa {} · limite {} · margem da casa {}".format(
        _fmt(a.get("odd_casa")), _fmt(a.get("odd_justa")),
        a.get("limite") if a.get("limite") is not None else "—",
        _fmt(a.get("margem_pct"), 2, "%")))
    for av in avisos:
        st.warning(av)


def _o_que_ficou_de_fora(st: Any, r: Mapping[str, Any], nao_casados: List[str]) -> None:
    """A parte que impede a tela de mentir por omissao."""
    fora = r.get("nao_precificados") or []
    sem_modelo = r.get("sem_modelo") or []
    total_fora = sum(int(g.get("linhas") or 0) for g in fora)
    if not (total_fora or sem_modelo or nao_casados):
        return

    with st.expander("O que este painel NAO olhou ({} linha(s))".format(total_fora)):
        if nao_casados:
            st.markdown("**Times que nao casaram com o CSV**")
            st.caption("Sem casar o nome nao ha historico, e sem historico nao ha "
                       "odd justa. Ensine o apelido uma vez na aba Jogos e nao volta.")
            st.write(", ".join(escape(n) for n in nao_casados))
        if sem_modelo:
            st.markdown("**Confrontos sem numero do modelo**")
            for s in sem_modelo:
                st.caption("· {} x {} (mapa {})".format(
                    s.get("casa"), s.get("fora"), str(s.get("mapa") or "")[1:]))
        if fora:
            st.markdown("**Mercados que este painel ainda nao precifica**")
            for g in fora:
                st.caption("· {} — {} linha(s) — {}".format(
                    g.get("mercado"), g.get("linhas"), g.get("motivo")))
