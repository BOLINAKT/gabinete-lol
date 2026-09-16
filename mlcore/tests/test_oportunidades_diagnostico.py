# -*- coding: utf-8 -*-
"""A aba Oportunidades tem de dizer POR QUE esta vazia.

ELE PERGUNTOU DUAS VEZES (16/09/2026):
    "essa parte ai das Oportunidades, eu ainda nao entendi, ate agora porque
     nao esta mostrando nada, voce nao disse que ja estava conseguindo pegar
     pelo menos as odds dos ml's?"

E a resposta era simples -- a tela e que nao dava. O confronto aberto era
eSuba x Meavedron, do Hitpoint Masters, e a PINNACLE NAO OFERECE Hitpoint
Masters (ela cobre LPL, LEC, LCS, CBLOL, Rift Legends e WSCI). Nao havia o
que comparar.

Mas a tela dizia "Nenhuma aposta com vantagem", que soa como "procurei e nao
achei nada bom". Para quem vai apostar, "nao achei valor" e "nao tinha o que
olhar" sao coisas MUITO diferentes -- e viraram a mesma frase.

Mesma familia do defeito que segurou kills por horas: o silencio com cara de
resposta completa.
"""
from __future__ import annotations

import inspect
import unittest

from app_core import oportunidades_tab_core as m

FONTE = inspect.getsource(m)


class _StFalso:
    """Guarda o que a tela escreveu, para os testes lerem."""

    def __init__(self):
        self.infos = []
        self.avisos = []
        self.notas = []

    def info(self, txt):
        self.infos.append(str(txt))

    def warning(self, txt):
        self.avisos.append(str(txt))

    def caption(self, txt):
        self.notas.append(str(txt))

    def tudo(self):
        return " || ".join(self.infos + self.avisos + self.notas)


def _odds():
    return {"jogos": [
        {"id": 1, "liga": "LEC", "casa": "Natus Vincere", "fora": "Movistar KOI", "bo": 5},
        {"id": 2, "liga": "LPL", "casa": "Top Esports", "fora": "Invictus", "bo": 5},
    ]}


def _eu_mesmo(n):
    return n


class TestOConfrontoAbertoNaoEstaNaCasa(unittest.TestCase):
    """O caso real dele."""

    def test_diz_o_NOME_do_confronto_que_ficou_de_fora(self):
        st = _StFalso()
        ok = m._diagnostico_do_confronto(
            st, _odds(), {"teamA": "eSuba", "teamB": "Meavedron"}, _eu_mesmo)
        self.assertFalse(ok)
        self.assertIn("eSuba", st.tudo())
        self.assertIn("Meavedron", st.tudo())
        self.assertIn("nao esta na Pinnacle", st.tudo())

    def test_LISTA_os_jogos_que_a_casa_tem(self):
        """E a informacao que resolve: basta abrir um deles."""
        st = _StFalso()
        m._diagnostico_do_confronto(
            st, _odds(), {"teamA": "eSuba", "teamB": "Meavedron"}, _eu_mesmo)
        self.assertIn("Natus Vincere", st.tudo())
        self.assertIn("Top Esports", st.tudo())

    def test_NAO_diz_que_procurou_e_nao_achou(self):
        """"Nao achei valor" e "nao tinha o que olhar" nao podem virar a
        mesma frase."""
        st = _StFalso()
        m._diagnostico_do_confronto(
            st, _odds(), {"teamA": "eSuba", "teamB": "Meavedron"}, _eu_mesmo)
        self.assertNotIn("Nenhuma aposta com vantagem", st.tudo())


class TestOConfrontoAbertoESTANaCasa(unittest.TestCase):

    def test_diz_que_esta_comparando_e_qual_BO(self):
        st = _StFalso()
        ok = m._diagnostico_do_confronto(
            st, _odds(), {"teamA": "Natus Vincere", "teamB": "Movistar KOI"}, _eu_mesmo)
        self.assertTrue(ok)
        self.assertIn("Comparando", st.tudo())
        self.assertIn("BO5", st.tudo())

    def test_ordem_INVERTIDA_tambem_e_reconhecida(self):
        """A casa lista "A x B" e a tela pode ter "B x A". E o mesmo jogo."""
        st = _StFalso()
        ok = m._diagnostico_do_confronto(
            st, _odds(), {"teamA": "Movistar KOI", "teamB": "Natus Vincere"}, _eu_mesmo)
        self.assertTrue(ok)


class TestSemConfrontoEscolhido(unittest.TestCase):

    def test_pede_para_escolher_em_vez_de_ficar_calada(self):
        st = _StFalso()
        ok = m._diagnostico_do_confronto(st, _odds(), {}, _eu_mesmo)
        self.assertFalse(ok)
        self.assertIn("Escolha um confronto", st.tudo())

    def test_ja_mostra_o_que_a_casa_tem(self):
        """Assim ele escolhe um que da certo de primeira."""
        st = _StFalso()
        m._diagnostico_do_confronto(st, _odds(), {}, _eu_mesmo)
        self.assertIn("Natus Vincere", st.tudo())


class TestQuandoNaoHaNADADaCasa(unittest.TestCase):

    def test_diz_que_a_coleta_veio_vazia(self):
        st = _StFalso()
        ok = m._diagnostico_do_confronto(
            st, {"jogos": []}, {"teamA": "eSuba", "teamB": "Meavedron"}, _eu_mesmo)
        self.assertFalse(ok)
        self.assertIn("nao trouxe jogo nenhum", st.tudo())

    def test_sem_resolvedor_nao_estoura(self):
        st = _StFalso()
        self.assertFalse(m._diagnostico_do_confronto(
            st, _odds(), {"teamA": "a", "teamB": "b"}, None))

    def test_resolvedor_que_estoura_nao_derruba(self):
        def _explode(n):
            raise RuntimeError("sem CSV")
        st = _StFalso()
        self.assertFalse(m._diagnostico_do_confronto(
            st, _odds(), {"teamA": "a", "teamB": "b"}, _explode))


class TestATelaCHAMAODiagnostico(unittest.TestCase):

    def test_a_aba_usa_o_diagnostico(self):
        src = inspect.getsource(m.render_oportunidades_tab)
        self.assertIn("_diagnostico_do_confronto", src)

    def test_a_frase_de_nada_encontrado_so_sai_quando_HOUVE_o_que_olhar(self):
        """Senao volta o problema: vazio por falta de jogo parecendo vazio
        por falta de valor."""
        src = inspect.getsource(m.render_oportunidades_tab)
        self.assertIn("elif _jogos_que_dao:", src)


if __name__ == "__main__":
    unittest.main()


class TestAAbaLeOMESMONumeroQueOCard(unittest.TestCase):
    """DOIS NUMEROS PARA A MESMA PERGUNTA -- relatado por ele em 16/09/2026.

    Ele mandou dois prints do MESMO confronto:
        aba Oportunidades:  eSuba 1.85   Meavedron 2.18
        card Visao Geral:   eSuba 1.71   Meavedron 2.40
    e escreveu: "esta pegando uma odd do modelo que nao existe".

    Tinha razao. O card (e a Analise de Linha, e o entre-mapas) leem
    `_p_map_used`/`_p_series_used` -- o FIM do caminho, depois das camadas de
    escalacao e do ajuste de serie. Eu estava passando `p_map_cal`/`p_series`,
    que sao o MEIO. Mesma pergunta, duas respostas.

    E a doenca que este projeto passou a sessao inteira combatendo: existe um
    modulo (mlcore/replay_pre_jogo) escrito porque ja houve TRES
    implementacoes da probabilidade pre-jogo.
    """

    def test_a_aba_recebe_o_numero_do_FIM_do_caminho(self):
        from pathlib import Path
        raiz = Path(__file__).resolve().parents[2]
        src = (raiz / "plays_app.py").read_text(encoding="utf-8")
        corte = src.split("TAB_OPORTUNIDADES: lambda:", 1)[1][:2000]
        self.assertIn('_p_map_used', corte)
        self.assertIn('_p_series_used', corte)

    def test_a_expressao_e_a_MESMA_que_o_card_usa(self):
        """Letra por letra: se as duas divergirem de novo, os numeros
        divergem junto, e o sintoma volta a ser um print dele."""
        from pathlib import Path
        raiz = Path(__file__).resolve().parents[2]
        app = (raiz / "plays_app.py").read_text(encoding="utf-8")
        card = (raiz / "app_core" / "visao_tab_core.py").read_text(encoding="utf-8")
        for expr in ('get("_p_map_used", p_map_cal)', 'get("_p_series_used", p_series)'):
            alvo = expr.replace('"', "'")
            self.assertTrue(expr in app or alvo in app, "a aba nao usa %s" % expr)
            self.assertTrue(expr in card or alvo in card, "o card nao usa %s" % expr)
