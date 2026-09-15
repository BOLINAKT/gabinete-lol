# -*- coding: utf-8 -*-
"""Testes do "Usar este jogo" quando o nome do time nao casa com o CSV.

O DEFEITO (relatado por ele em 15/09/2026, com print): ele escolheu um jogo
salvo da agenda, clicou em "Usar este jogo", e o **Time 1 ficou vazio**. O
Time 2 preencheu normalmente. Nenhuma mensagem, nenhum aviso — parecia que o
botao nao tinha funcionado.

A CAUSA: a checagem era `nome in teams`, exata letra por letra. A agenda dele
tinha "Barczaca Esports" e o CSV tem "Barczaca Esports by Yumisu". Sufixo
diferente, campo vazio, silencio.

E o mais frustrante: o resolvedor com apelidos JA EXISTIA no projeto — e o
mesmo que a aba Jogos usa ao importar — e nunca tinha sido chamado aqui. Alem
disso, o nome certo aparecia em TERCEIRO nas sugestoes automaticas.

CAMPO VAZIO SEM EXPLICACAO E O PIOR DESFECHO: nao da nem para saber se o erro
foi do app, do dado ou do clique.
"""
from __future__ import annotations

import unittest

from app_core.matchup_selection_core import (
    _CHAVE_NAO_RESOLVIDOS,
    _resolver_time_salvo,
    set_pending_unresolved,
)

TIMES = ["Barcząca Esports by Yumisu", "French Flair", "Gen.G", "T1"]


class TestOCasoDele(unittest.TestCase):

    def test_nome_exato_passa_direto(self):
        self.assertEqual(_resolver_time_salvo({}, "French Flair", TIMES), "French Flair")

    def test_nome_com_sufixo_faltando_NAO_e_adivinhado(self):
        """PRINCIPIO IV: "Barczaca Esports" pode ser outro time.

        Adivinhar aqui seria pior que o campo vazio — analisaria o confronto
        errado com toda a confianca. O certo e DIZER que nao casou e deixar
        ele escolher; foi isso que passou a acontecer.
        """
        self.assertEqual(_resolver_time_salvo({}, "Barcząca Esports", TIMES), "")

    def test_nome_inexistente_devolve_vazio(self):
        self.assertEqual(_resolver_time_salvo({}, "Time Que Nao Existe", TIMES), "")

    def test_vazio_devolve_vazio(self):
        self.assertEqual(_resolver_time_salvo({}, "", TIMES), "")
        self.assertEqual(_resolver_time_salvo({}, "   ", TIMES), "")

    def test_o_nome_certo_esta_nas_SUGESTOES(self):
        """E o que torna o conserto de um clique: o palpite ja vem pronto."""
        from app_core.schedule_import_core import suggest_schedule_teams
        sug = suggest_schedule_teams("Barcząca Esports", TIMES)
        self.assertIn("Barcząca Esports by Yumisu", sug)


class TestApelidoAprendidoResolve(unittest.TestCase):
    """Depois de ensinar uma vez, o problema nao volta."""

    def test_com_apelido_salvo_o_nome_passa_a_casar(self):
        import tempfile
        from pathlib import Path

        from app_core.schedule_import_core import (
            normalize_schedule_team_key,
            resolve_schedule_team,
        )
        apelidos = {normalize_schedule_team_key("Barcząca Esports"):
                    "Barcząca Esports by Yumisu"}
        achado, ok = resolve_schedule_team("Barcząca Esports", TIMES, apelidos)
        self.assertTrue(ok)
        self.assertEqual(achado, "Barcząca Esports by Yumisu")


class TestOQueNaoCasouFicaDITO(unittest.TestCase):
    """Campo vazio sem explicacao parece botao quebrado."""

    def test_guarda_o_que_faltou_para_a_tela_avisar(self):
        est = {}
        set_pending_unresolved(est, [("Time 1", "Barcząca Esports")])
        self.assertEqual(est[_CHAVE_NAO_RESOLVIDOS],
                         [("Time 1", "Barcząca Esports")])

    def test_lista_vazia_nao_estoura(self):
        est = {}
        set_pending_unresolved(est, [])
        self.assertEqual(est[_CHAVE_NAO_RESOLVIDOS], [])

    def test_estado_que_nao_aceita_escrita_nao_derruba(self):
        class _Travado:
            def __setitem__(self, k, v):
                raise TypeError("nao aceita")
        set_pending_unresolved(_Travado(), [("Time 1", "X")])   # nao pode estourar


class TestATelaUsaOResolvedor(unittest.TestCase):
    """A comparacao exata nao pode voltar."""

    def test_nao_ha_mais_comparacao_exata_com_a_lista(self):
        import inspect

        from app_core import matchup_selection_core as m
        src = inspect.getsource(m.render_matchup_selection)
        self.assertNotIn('if str(game.get("teamA", "")) in teams:', src)
        self.assertIn("_resolver_time_salvo", src)

    def test_a_tela_avisa_e_oferece_o_conserto(self):
        import inspect

        from app_core import matchup_selection_core as m
        src = inspect.getsource(m.render_matchup_selection)
        self.assertIn("ficou vazio", src)
        self.assertIn("suggest_schedule_teams", src)
        self.assertIn("save_schedule_aliases", src)


if __name__ == "__main__":
    unittest.main()
