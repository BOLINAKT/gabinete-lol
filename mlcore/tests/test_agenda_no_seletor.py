# -*- coding: utf-8 -*-
"""Os jogos do calendario aparecem no seletor de confronto, sem importar nada.

O DEFEITO (relatado por ele em 16/09/2026, com print): abriu "Selecionar jogo
salvo (Agenda)" e so viu TRES jogos de 15/05 -- os antigos dele. Os 15 jogos
que o robo tinha coletado naquele dia nao estavam la.

A CAUSA foi decisao minha, nao bug: eu liguei a coleta a uma IMPORTACAO. Para
o jogo coletado chegar neste seletor era preciso ir na aba Jogos, clicar em
"Trazer os jogos coletados", conferir o mapeamento e clicar em "Adicionar a
agenda". Tres cliques, duas telas.

So que o pedido dele tinha sido, com estas palavras:

    "esse jogos (agenda) e onde eu quero que fiquem os jogos que voce pegar do
     calendario, PARA QUE EU NAO PRECISE FICAR INDO ATRAS DE JOGOS"

Coleta que exige ir atras dela nao resolve o problema que ele descreveu.
"""
from __future__ import annotations

import unittest

from app_core.agenda_coletada_core import (
    ORIGEM_COLETADO,
    ORIGEM_SALVO,
    juntar_para_escolher,
    rotulo_do_jogo,
)


def _salvo(**k):
    base = {"date": "15/05", "time": "13:00", "league": "EM",
            "teamA": "Barcząca Esports", "teamB": "French Flair", "bo": 3}
    base.update(k)
    return base


def _coletado(**k):
    base = {"date": "16/09", "time": "10:00", "league": "LPL",
            "teamA_raw": "Top Esports", "teamB_raw": "Invictus Gaming", "bo": 5,
            "estado": "unstarted"}
    base.update(k)
    return base


class TestOsColetadosAPARECEM(unittest.TestCase):

    def test_coletado_entra_na_lista_sem_importar(self):
        r = juntar_para_escolher([], [_coletado()])
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["teamA"], "Top Esports")
        self.assertEqual(r[0]["teamB"], "Invictus Gaming")

    def test_os_salvos_DELE_continuam_na_lista(self):
        """Nao se troca a lista dele pela minha. Soma-se."""
        r = juntar_para_escolher([_salvo()], [_coletado()])
        self.assertEqual(len(r), 2)
        self.assertIn("Barcząca Esports", [j["teamA"] for j in r])

    def test_os_coletados_vem_PRIMEIRO(self):
        """Sao os jogos POR VIR -- e por eles que ele abre a lista.

        Os salvos dele no dia do relato eram de 15/05, quatro meses velhos.
        Deixar os de hoje embaixo deles seria manter o problema.
        """
        r = juntar_para_escolher([_salvo()], [_coletado()])
        self.assertEqual(r[0]["origem"], ORIGEM_COLETADO)
        self.assertEqual(r[-1]["origem"], ORIGEM_SALVO)

    def test_a_ordem_dos_coletados_entre_si_e_mantida(self):
        r = juntar_para_escolher([], [_coletado(teamA_raw="A"), _coletado(teamA_raw="B")])
        self.assertEqual([j["teamA"] for j in r], ["A", "B"])


class TestNadaDoQueEDELESeperde(unittest.TestCase):
    """Apagar trabalho dele seria pior que nao mostrar jogo nenhum."""

    def test_partida_nas_DUAS_listas_aparece_uma_vez_so(self):
        igual_salvo = _salvo(date="16/09", time="10:00",
                             teamA="Top Esports", teamB="Invictus Gaming")
        r = juntar_para_escolher([igual_salvo], [_coletado()])
        self.assertEqual(len(r), 1)

    def test_e_quem_fica_e_a_versao_DELE(self):
        """A dele pode ter LINHA DIGITADA junto; a coletada nunca tem."""
        igual_salvo = _salvo(date="16/09", time="10:00",
                             teamA="Top Esports", teamB="Invictus Gaming",
                             lines_saved={"kills_text": "27.5"})
        r = juntar_para_escolher([igual_salvo], [_coletado()])
        self.assertEqual(r[0]["origem"], ORIGEM_SALVO)
        self.assertEqual(r[0]["lines_saved"], {"kills_text": "27.5"})

    def test_a_comparacao_nao_e_sensivel_a_maiuscula(self):
        igual = _salvo(date="16/09", time="10:00",
                       teamA="TOP ESPORTS", teamB="invictus gaming")
        self.assertEqual(len(juntar_para_escolher([igual], [_coletado()])), 1)

    def test_jogo_parecido_em_OUTRO_horario_nao_e_o_mesmo(self):
        outro = _salvo(date="16/09", time="14:00",
                       teamA="Top Esports", teamB="Invictus Gaming")
        self.assertEqual(len(juntar_para_escolher([outro], [_coletado()])), 2)


class TestORotuloDizDeOndeVEIO(unittest.TestCase):
    """Sem a marca ele nao sabe se aquele jogo tem linha dele salva junto."""

    def test_o_coletado_vem_marcado(self):
        r = juntar_para_escolher([], [_coletado()])
        self.assertIn("calendario", rotulo_do_jogo(r[0]))

    def test_o_salvo_NAO_vem_marcado(self):
        r = juntar_para_escolher([_salvo()], [])
        self.assertNotIn("calendario", rotulo_do_jogo(r[0]))

    def test_o_rotulo_tem_data_liga_times_e_bo(self):
        texto = rotulo_do_jogo(juntar_para_escolher([], [_coletado()])[0])
        for pedaco in ("16/09", "10:00", "LPL", "Top Esports", "Invictus Gaming", "BO5"):
            self.assertIn(pedaco, texto)

    def test_bo_ilegivel_nao_estoura_e_cai_no_padrao(self):
        r = juntar_para_escolher([], [_coletado(bo="nao e numero")])
        self.assertIn("BO3", rotulo_do_jogo(r[0]))

    def test_jogo_sem_liga_nao_deixa_barra_solta(self):
        texto = rotulo_do_jogo(juntar_para_escolher([], [_coletado(league="")])[0])
        self.assertNotIn("|  |", texto)


class TestListaEstragadaNaoDerruba(unittest.TestCase):

    def test_lixo_nas_duas_listas_e_ignorado(self):
        r = juntar_para_escolher(["lixo", None, _salvo()], [7, _coletado(), None])
        self.assertEqual(len(r), 2)

    def test_listas_vazias_ou_ausentes(self):
        self.assertEqual(juntar_para_escolher([], []), [])
        self.assertEqual(juntar_para_escolher(None, None), [])


class TestATelaUSAOJuntador(unittest.TestCase):
    """O seletor nao pode voltar a ler so a lista salva."""

    def test_o_seletor_chama_o_juntador(self):
        import inspect

        from app_core import matchup_selection_core as m
        src = inspect.getsource(m.render_matchup_selection)
        self.assertIn("_jogos_do_seletor", src)
        self.assertNotIn("games = get_schedule_games(session_state)", src)

    def test_o_carregador_le_a_agenda_coletada(self):
        import inspect

        from app_core import matchup_selection_core as m
        src = inspect.getsource(m._jogos_do_seletor)
        self.assertIn("carregar_agenda_coletada", src)
        self.assertIn("juntar_para_escolher", src)

    def test_se_a_leitura_FALHAR_a_lista_dele_continua(self):
        """O seletor nunca pode ficar pior do que ja era."""
        from app_core import matchup_selection_core as m

        class _EstadoQueSoTemOsSalvos(dict):
            pass

        est = _EstadoQueSoTemOsSalvos()
        est["games_list"] = [_salvo()]
        saida = m._jogos_do_seletor(est)
        self.assertTrue(any(j.get("teamA") == "Barcząca Esports" for j in saida))


class TestSemRede(unittest.TestCase):
    def test_o_juntador_nao_vai_a_rede(self):
        import inspect

        from app_core import agenda_coletada_core as m
        src = inspect.getsource(m)
        self.assertNotIn("import requests", src)
        self.assertNotIn("urlopen", src)


if __name__ == "__main__":
    unittest.main()
