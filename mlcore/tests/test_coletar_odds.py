# -*- coding: utf-8 -*-
"""Testes do coletor de odds da Pinnacle.

PARA QUE SERVE
A Pinnacle trabalha com margem baixa e limite alto e aceita dinheiro afiado em
vez de barrar a conta — o preco dela e o mais proximo de probabilidade
verdadeira que o mercado oferece. Guardado COM HORA, ele vira a regua externa
que este projeto nao tem: medir se o modelo bate o fechamento (CLV) e a unica
medicao que responde se existe lucro.

DE ONDE VEM, SEM DISFARCE
E a API interna do site DELES, aberta e sem credencial — a porta dos fundos,
nao a oficial (que fechou, e que para esports exige autorizacao especial).
Ele decidiu usa-la sabendo disso em 15/09/2026. Por isso os testes de
EDUCACAO abaixo: 403/429 tem de parar na hora, sem insistir nem contornar.

O QUE ESTES TESTES PROTEGEM, em ordem:
  1. o historico guarda SO o que mudou — senao viram ~9 MB/mes no repositorio,
     e o que o CLV precisa e o movimento, nao o retrato repetido;
  2. mudanca de formato da API vira ERRO ALTO, nunca lista vazia calada;
  3. preco ilegivel vira ausencia, nunca 1,0 ou 2,0 disfarcado de odd.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.coletar_odds import (
    _ultimas_odds,
    chave_da_linha,
    margem,
    normalizar,
    para_decimal,
)


def _matchup(**k):
    base = {
        "id": 1, "parentId": None, "isLive": False, "bestOfX": 5,
        "startTime": "2026-09-18T20:00:00Z",
        "league": {"name": "League of Legends - LCS"},
        "participants": [
            {"alignment": "home", "name": "Shopify Rebellion"},
            {"alignment": "away", "name": "Sentinels"},
        ],
    }
    base.update(k)
    return base


def _mercado(**k):
    base = {
        "matchupId": 1, "type": "moneyline", "period": 0, "isAlternate": False,
        "cutoffAt": "2026-09-18T20:00:00+00:00",
        "limits": [{"amount": 2000, "type": "maxRiskStake"}],
        "prices": [{"designation": "home", "price": 190},
                   {"designation": "away", "price": -243}],
    }
    base.update(k)
    return base


class TestOddAmericanaViraDecimal(unittest.TestCase):

    def test_positiva(self):
        self.assertAlmostEqual(para_decimal(190), 2.90, places=4)

    def test_negativa(self):
        self.assertAlmostEqual(para_decimal(-243), 1.4115, places=4)

    def test_favorito_pesado(self):
        self.assertAlmostEqual(para_decimal(-853), 1.1172, places=4)

    def test_preco_ilegivel_vira_AUSENCIA_e_nao_odd(self):
        """PRINCIPIO IV: 1,0 ou 2,0 chutado viraria aposta de graca na tela."""
        for ruim in (None, "", "abc", 0):
            self.assertIsNone(para_decimal(ruim), ruim)


class TestAMargemDenunciaAConfianca(unittest.TestCase):
    """Medido em 15/09/2026: LPL 4,8% · LCS 5,3% · WSCI 9,4%.

    Margem alta e a casa dizendo "nao sei direito, entao me protejo".
    """

    def test_calcula_a_margem_das_duas_pernas(self):
        m = margem([2.90, 1.4115])
        self.assertAlmostEqual(m, 5.34, delta=0.1)

    def test_margem_menor_em_mercado_mais_liquido(self):
        self.assertLess(margem([2.150, 1.714]), margem([1.166, 4.220]))

    def test_perna_faltando_NAO_vira_margem_inventada(self):
        self.assertIsNone(margem([2.90]))
        self.assertIsNone(margem([]))

    def test_odd_invalida_nao_vira_margem(self):
        self.assertIsNone(margem([2.90, None]))
        self.assertIsNone(margem([2.90, 1.0]))


class TestOQueEntraEOQueFicaDeFora(unittest.TestCase):

    def test_le_a_serie_com_times_e_formato(self):
        d = normalizar([_matchup()], [_mercado()])
        self.assertEqual(len(d["jogos"]), 1)
        j = d["jogos"][0]
        self.assertEqual(j["casa"], "Shopify Rebellion")
        self.assertEqual(j["fora"], "Sentinels")
        self.assertEqual(j["bo"], 5)
        self.assertEqual(j["liga"], "LCS")

    def test_ao_vivo_fica_de_fora(self):
        """O escopo deste projeto e PRE-JOGO."""
        d = normalizar([_matchup(isLive=True)], [_mercado()])
        self.assertEqual(d["jogos"], [])
        self.assertEqual(d["descartes"]["ao_vivo"], 1)

    def test_confronto_FILHO_fica_de_fora(self):
        """Placar exato e mapa avulso; o pai ja traz o que interessa."""
        d = normalizar([_matchup(parentId=99)], [_mercado()])
        self.assertEqual(d["jogos"], [])
        self.assertEqual(d["descartes"]["filho"], 1)

    def test_outro_jogo_fica_de_fora(self):
        d = normalizar([_matchup(league={"name": "Counter-Strike - BLAST"})], [_mercado()])
        self.assertEqual(d["jogos"], [])
        self.assertEqual(d["descartes"]["outro_jogo"], 1)

    def test_serie_sem_mercado_e_contada(self):
        d = normalizar([_matchup()], [])
        self.assertEqual(d["jogos"], [])
        self.assertEqual(d["descartes"]["sem_mercado"], 1)

    def test_guarda_limite_e_hora_de_fechamento(self):
        """O limite e a casa dizendo em qual preco ela acredita."""
        l = normalizar([_matchup()], [_mercado()])["linhas"][0]
        self.assertEqual(l["limite"], 2000)
        self.assertTrue(l["fecha_em"])

    def test_handicap_e_total_tambem_entram(self):
        mks = [
            _mercado(type="spread", prices=[
                {"designation": "home", "points": 1.5, "price": -114},
                {"designation": "away", "points": -1.5, "price": -106}]),
            _mercado(type="total", prices=[
                {"designation": "over", "points": 4.5, "price": 172},
                {"designation": "under", "points": 4.5, "price": -247}]),
        ]
        tipos = {l["tipo"] for l in normalizar([_matchup()], mks)["linhas"]}
        self.assertEqual(tipos, {"spread", "total"})

    def test_a_linha_do_handicap_e_guardada(self):
        mk = _mercado(type="spread", prices=[
            {"designation": "home", "points": 1.5, "price": -114},
            {"designation": "away", "points": -1.5, "price": -106}])
        pts = sorted(l["pontos"] for l in normalizar([_matchup()], [mk])["linhas"])
        self.assertEqual(pts, [-1.5, 1.5])


class TestSeAAPIMudarELOUD(unittest.TestCase):
    """Lista vazia calada seria o pior desfecho: "sem odds hoje" com toda a
    confianca do mundo, num dia cheio de jogo."""

    def test_matchups_que_nao_e_lista_estoura(self):
        with self.assertRaises(ValueError):
            normalizar({"data": []}, [])

    def test_markets_que_nao_e_lista_estoura(self):
        with self.assertRaises(ValueError):
            normalizar([], {"data": []})

    def test_a_mensagem_aponta_a_causa(self):
        try:
            normalizar("nada", [])
        except ValueError as e:
            self.assertIn("API mudou", str(e))

    def test_lixo_no_meio_da_lista_nao_derruba_o_resto(self):
        d = normalizar([None, "texto", 42, _matchup()], [_mercado()])
        self.assertEqual(len(d["jogos"]), 1)


class TestOHistoricoGuardaSoOMovimento(unittest.TestCase):
    """Retrato repetido daria ~9 MB/mes. O CLV precisa do MOVIMENTO."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hist = Path(self.tmp.name) / "hist.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _grava(self, registros):
        with open(self.hist, "a", encoding="utf-8") as fh:
            for r in registros:
                fh.write(json.dumps(r) + "\n")

    def test_le_o_ultimo_preco_de_cada_aposta(self):
        self._grava([{"chave": "a", "odd": 2.0}, {"chave": "a", "odd": 2.2},
                     {"chave": "b", "odd": 1.5}])
        u = _ultimas_odds(self.hist)
        self.assertEqual(u["a"], 2.2, "tem de valer o ULTIMO, nao o primeiro")
        self.assertEqual(u["b"], 1.5)

    def test_historico_ausente_nao_estoura(self):
        self.assertEqual(_ultimas_odds(self.hist), {})

    def test_linha_truncada_nao_derruba_o_resto(self):
        with open(self.hist, "w", encoding="utf-8") as fh:
            fh.write('{"chave": "a", "odd": 2.0}\n')
            fh.write('{"chave": "b", "odd\n')          # cortada no meio
            fh.write('{"chave": "c", "odd": 1.8}\n')
        u = _ultimas_odds(self.hist)
        self.assertEqual(u.get("a"), 2.0)
        self.assertEqual(u.get("c"), 1.8)

    def test_a_chave_separa_apostas_diferentes(self):
        base = {"jogo": 1, "tipo": "spread", "periodo": 0, "lado": "home"}
        k1 = chave_da_linha(dict(base, pontos=1.5))
        k2 = chave_da_linha(dict(base, pontos=2.5))
        self.assertNotEqual(k1, k2, "linhas diferentes do handicap sao apostas diferentes")

    def test_a_chave_separa_mapa_de_serie(self):
        base = {"jogo": 1, "tipo": "moneyline", "lado": "home", "pontos": None}
        self.assertNotEqual(chave_da_linha(dict(base, periodo=0)),
                            chave_da_linha(dict(base, periodo=1)))

    def test_a_chave_separa_os_dois_lados(self):
        base = {"jogo": 1, "tipo": "moneyline", "periodo": 0, "pontos": None}
        self.assertNotEqual(chave_da_linha(dict(base, lado="home")),
                            chave_da_linha(dict(base, lado="away")))


class TestEducacaoComACasa(unittest.TestCase):
    """E a porta dos fundos. Se eles nao quiserem, a resposta e PARAR.

    O risco nao e a conta de aposta dele (nada aqui usa login) — e bloqueio de
    IP, que tiraria o acesso ao site de onde ele aposta.
    """

    def test_403_e_429_param_na_hora(self):
        import inspect

        from tools import coletar_odds as m
        src = inspect.getsource(m.main)
        self.assertIn("403", src)
        self.assertIn("429", src)
        self.assertIn("RC_TEMPORARIO", src)

    def test_nao_ha_retentativa_nem_troca_de_identidade(self):
        """Insistir depois de um bloqueio e o caminho para ser bloqueado de vez."""
        import inspect

        from tools import coletar_odds as m
        src = inspect.getsource(m)
        self.assertNotIn("proxy", src.lower())
        self.assertNotIn("retry", src.lower())

    def test_o_agente_diz_quem_e_e_para_que(self):
        from tools.coletar_odds import AGENTE
        self.assertIn("gabinete", AGENTE.lower())
        self.assertIn("pessoal", AGENTE.lower())

    def test_sao_duas_requisicoes_por_corrida(self):
        import inspect

        from tools import coletar_odds as m
        self.assertEqual(inspect.getsource(m.main).count("requests.get"), 2)


if __name__ == "__main__":
    unittest.main()
