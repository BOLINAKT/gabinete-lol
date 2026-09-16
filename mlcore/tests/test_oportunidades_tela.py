# -*- coding: utf-8 -*-
"""A tela de comparacao da aba Oportunidades.

ELE PEDIU (16/09/2026), olhando a lista de cartoes com aviso vermelho:

    "acho que e melhor fazer uma tela comparada, a linha da casa de uma cor,
     com a linha do modelo de outra, talvez ao lado... eu selecionaria por
     exemplo, Vencedor e voce me mostraria a 'tela' da visao geral, com a odd
     do modelo e ao lado a odd da casa junto com a vantagem"

A lista antiga tinha um defeito alem do visual: SO MOSTRAVA O LADO COM
VANTAGEM. O outro lado e metade da informacao -- e olhando o par que se ve o
tamanho da discordancia. No primeiro confronto real:

    Natus Vincere   modelo 1,78   casa 2,84   +59,65%
    Movistar KOI    modelo 2,28   casa 1,43   -37,58%

Modelo: 56% x 44%. Casa: 35% x 70%. O abismo aparece nos dois lados de uma
vez -- e a lista de um lado so nao deixava ver isso.
"""
from __future__ import annotations

import inspect
import re
import unittest

from app_core import oportunidades_tab_core as m


class _StFalso:
    def __init__(self):
        self.htmls = []
        self.notas = []

    def markdown(self, txt, **k):
        self.htmls.append(str(txt))

    def caption(self, txt):
        self.notas.append(str(txt))

    def texto(self):
        bruto = " ".join(self.htmls)
        return re.sub(r"<[^>]+>", " ", bruto)


def _achado(**k):
    base = {"mercado": "Vencedor - serie", "lado": "home", "pontos": None,
            "odd_casa": 2.84, "odd_justa": 1.78, "probabilidade": 0.56,
            "vantagem_pct": 59.65, "limite": 1250, "metrica": "vencedor",
            "mapa": "", "casa": "Natus Vincere", "fora": "Movistar KOI",
            "suspeito": True, "dados_finos": False}
    base.update(k)
    return base


class TestOsDOISLadosAparecem(unittest.TestCase):
    """O motivo de existir desta tela."""

    def test_o_lado_sem_vantagem_tambem_e_mostrado(self):
        st = _StFalso()
        m._tabela_comparada(st, "Vencedor - serie", [
            _achado(),
            _achado(lado="away", odd_casa=1.43, odd_justa=2.28,
                    vantagem_pct=-37.58, suspeito=False),
        ])
        t = st.texto()
        self.assertIn("Natus Vincere", t)
        self.assertIn("Movistar KOI", t)
        self.assertIn("+59.65%", t)
        self.assertIn("-37.58%", t)

    def test_as_tres_colunas_existem_e_sao_nomeadas(self):
        st = _StFalso()
        m._tabela_comparada(st, "Vencedor - serie", [_achado()])
        t = st.texto().lower()
        for coluna in ("aposta", "modelo", "casa", "vantagem"):
            self.assertIn(coluna, t)

    def test_modelo_e_casa_tem_CORES_diferentes(self):
        """Foi o pedido literal: "a linha da casa de uma cor, com a linha do
        modelo de outra"."""
        self.assertNotEqual(m._COR_MODELO, m._COR_CASA)
        st = _StFalso()
        m._tabela_comparada(st, "x", [_achado()])
        bruto = " ".join(st.htmls)
        self.assertIn(m._COR_MODELO, bruto)
        self.assertIn(m._COR_CASA, bruto)

    def test_o_limite_da_casa_aparece(self):
        """Vantagem de 8% num mercado de R$100 vale menos que 3% num de
        R$2.000."""
        st = _StFalso()
        m._tabela_comparada(st, "x", [_achado(limite=1250)])
        self.assertIn("1250", st.texto())


class TestONomeDoLadoEmPortugues(unittest.TestCase):
    """"home"/"over" nao dizem nada para quem esta apostando."""

    def test_casa_e_fora_viram_o_NOME_do_time(self):
        self.assertEqual(m._nome_do_lado(_achado(lado="home")), "Natus Vincere")
        self.assertEqual(m._nome_do_lado(_achado(lado="away")), "Movistar KOI")

    def test_over_e_under_viram_acima_e_abaixo(self):
        self.assertEqual(
            m._nome_do_lado(_achado(lado="over", pontos=31.5)), "acima de 31,5")
        self.assertEqual(
            m._nome_do_lado(_achado(lado="under", pontos=31.5)), "abaixo de 31,5")

    def test_lado_com_nome_proprio_e_mantido(self):
        """Placar exato tem lados como "Fuego 3, 9z 0"."""
        self.assertEqual(m._nome_do_lado(_achado(lado="Fuego 3, 9z 0")),
                         "Fuego 3, 9z 0")


class TestOsAvisosViramETIQUETA(unittest.TestCase):
    """Antes cada aviso era uma tarja vermelha do tamanho da tela, repetida
    quatro vezes. Vira etiqueta na linha a que pertence."""

    def test_vantagem_grande_demais_fica_marcada(self):
        st = _StFalso()
        m._tabela_comparada(st, "x", [_achado(suspeito=True)])
        self.assertIn("grande demais", st.texto())

    def test_poucos_jogos_fica_marcado(self):
        st = _StFalso()
        m._tabela_comparada(st, "x", [_achado(suspeito=False, dados_finos=True)])
        self.assertIn("poucos jogos", st.texto())

    def test_linha_sadia_nao_ganha_etiqueta(self):
        st = _StFalso()
        m._tabela_comparada(st, "x", [_achado(suspeito=False, dados_finos=False,
                                              vantagem_pct=3.2)])
        t = st.texto()
        self.assertNotIn("grande demais", t)
        self.assertNotIn("poucos jogos", t)


class TestAOrdemDentroDoMercado(unittest.TestCase):
    """Os dois lados da MESMA linha tem de ficar colados.

    Numa tabela de kills com cinco linhas (31,5 a 35,5), separar o Over do
    Under obrigaria a procurar o par -- que e justamente o que se quer
    comparar.
    """

    def test_o_par_da_mesma_linha_fica_junto(self):
        linhas = [
            _achado(lado="under", pontos=32.5), _achado(lado="over", pontos=31.5),
            _achado(lado="under", pontos=31.5), _achado(lado="over", pontos=32.5),
        ]
        ordenadas = sorted(linhas, key=m._ordem_da_linha)
        pares = [(a["pontos"], a["lado"]) for a in ordenadas]
        self.assertEqual(pares, [(31.5, "over"), (31.5, "under"),
                                 (32.5, "over"), (32.5, "under")])

    def test_over_vem_antes_de_under(self):
        a = m._ordem_da_linha(_achado(lado="over", pontos=31.5))
        b = m._ordem_da_linha(_achado(lado="under", pontos=31.5))
        self.assertLess(a, b)

    def test_linha_sem_numero_nao_estoura(self):
        m._ordem_da_linha(_achado(lado="home", pontos=None))


class TestNadaQuebraComDadoRUIM(unittest.TestCase):

    def test_vantagem_ausente_nao_vira_zero(self):
        """PRINCIPIO IV: "nao sei" nao pode virar "medi, e da zero"."""
        st = _StFalso()
        m._tabela_comparada(st, "x", [_achado(vantagem_pct=None)])
        self.assertIn("—", st.texto())

    def test_odd_ausente_vira_travessao(self):
        st = _StFalso()
        m._tabela_comparada(st, "x", [_achado(odd_casa=None, odd_justa=None)])
        self.assertIn("—", st.texto())

    def test_lista_vazia_nao_estoura(self):
        st = _StFalso()
        m._tabela_comparada(st, "x", [])

    def test_nome_de_time_com_html_e_escapado(self):
        """Nome vindo de arquivo nao pode virar marcacao na tela."""
        st = _StFalso()
        m._tabela_comparada(st, "x", [_achado(casa="<b>hack</b>", lado="home")])
        self.assertNotIn("<b>hack</b>", " ".join(st.htmls))


class TestATelaUSAOSeletorDeMercado(unittest.TestCase):

    def test_a_aba_oferece_escolher_o_mercado(self):
        src = inspect.getsource(m.render_oportunidades_tab)
        self.assertIn("Qual mercado voce quer comparar", src)

    def test_a_aba_mostra_TODAS_as_linhas_e_nao_so_as_boas(self):
        """Com o corte por vantagem, o lado negativo do par sumiria."""
        src = inspect.getsource(m.render_oportunidades_tab)
        self.assertIn('r.get("todas")', src)
        self.assertIn("minimo_pct=0.0", src)

    def test_a_lista_de_cartoes_com_tarja_saiu(self):
        fonte = inspect.getsource(m)
        self.assertNotIn("def _cartao(", fonte)


if __name__ == "__main__":
    unittest.main()
