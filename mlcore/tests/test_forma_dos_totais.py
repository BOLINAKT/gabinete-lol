# -*- coding: utf-8 -*-
"""A forma real dos totais no lugar da curva normal/Poisson.

O QUE ELE PEDIU (23/09/2026): uma limpa atras de "erros de calculo mesmo, ou
erros de entendimento de uma ideia geral".

O ERRO ACHADO. `matchup_expected_totals` soma as variacoes dos dois times como
se fossem INDEPENDENTES. Nao sao: quando um time atropela, ele derruba muitas
torres e o outro quase nenhuma (correlacao -0,82 em torres). O resultado,
medido pelo desvio dos erros padronizados (1 = espalhamento certo):

    torres 0,437 | baroes 0,635 | inibidores 0,651 | dragoes 0,551

Num confronto real (T1 x Gen.G) o motor dizia sd 4,74 para torres, quando o
desvio REAL e 2,17 -- ou seja, se dizia pior do que chutar a media geral. Toda
linha de total saia achatada para perto de 50%: o modelo enxergava MENOS
vantagem do que existe.

POR QUE A TENTATIVA DE 2026-07-17 FALHOU, e por que esta passou: aquela
encolhia o sd com piso `RHO_MIN = 0.75`, e torres precisava de 0,44. E nos
Poisson encolher o sd nao faz nada -- `prob_over_from_total` nem le o campo.
A forma empirica resolve os dois. Gate (mesmo protocolo e mesma barra de
0,0005, avaliacao cega em 2026): torres +0,0188, baroes +0,0113, inibidores
+0,0088.

O QUE ESTES TESTES PROTEGEM:
  1. so entra onde o gate mediu a MESMA media que a tela usa;
  2. sem o artefato, tudo volta ao comportamento de sempre (nunca estoura);
  3. todas as telas herdam, porque o total carrega o nome do mercado;
  4. abates -- o mercado que ele mais aposta -- NAO mudou.
"""
from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

import mlcore.lines_engine as le
from mlcore.lines_engine import MatchupTotals, prob_over_from_total, total_over_prob

RAIZ = Path(__file__).resolve().parents[2]


class TestSoEntraOndeOGateValeu(unittest.TestCase):

    def test_torres_baroes_inibidores_entram(self):
        for m in ("towers", "barons", "inhibitors"):
            self.assertIn(m, le.FORMA_EMPIRICA_MERCADOS)

    def test_ABATES_nao_entra(self):
        """Ganho medido: -0,00000. E o mercado que ele mais aposta; trocar a
        conta sem ganho seria mexer por mexer."""
        self.assertNotIn("kills", le.FORMA_EMPIRICA_MERCADOS)

    def test_dragoes_e_tempo_esperam_a_remedicao_pelo_caminho_servido(self):
        """O gate mediu a media V0; a tela usa a media com Dixon-Coles para
        kills, dragoes e tempo. Ligar assim seria medir uma coisa e servir
        outra (PRINCIPIO V)."""
        for m in ("dragons", "time"):
            if m in le.FORMA_EMPIRICA_MERCADOS:
                # So pode entrar se o gate SERVIDO tiver rodado.
                self.assertTrue(
                    (RAIZ / "scratchpad" / "gate_totais_registros_servido.json").exists(),
                    "%s entrou sem a remedicao pelo caminho da tela" % m)

    def test_nenhum_mercado_com_dixon_coles_entra_sem_remedicao(self):
        comuns = set(le._DC_BLEND_COLS) & set(le.FORMA_EMPIRICA_MERCADOS)
        if comuns:
            self.assertTrue(
                (RAIZ / "scratchpad" / "gate_totais_registros_servido.json").exists(),
                "mercados com blend DC na forma sem gate servido: %s" % comuns)


class TestOTotalCarregaOProprioMercado(unittest.TestCase):
    """E isso que faz o conserto chegar em TODAS as telas de uma vez."""

    def test_o_motor_marca_cada_mercado(self):
        from mlcore.lines_engine import TeamProfile
        campos = {f: 10.0 for f in TeamProfile.__dataclass_fields__
                  if f not in ("team", "n_games")}
        p = TeamProfile(team="A", n_games=20, **campos)
        t = le.matchup_expected_totals(p, p)
        for m, x in t.items():
            self.assertEqual(x.metric, m, "%s saiu marcado como %r" % (m, x.metric))

    def test_o_blend_dixon_coles_PRESERVA_o_mercado(self):
        """Quem reconstroi o total nao pode apagar o nome -- senao a forma
        some em silencio, so naquele mercado."""
        import inspect
        fonte = inspect.getsource(le.apply_dc_blend)
        self.assertIn('metric=getattr(tot, "metric", None) or metric', fonte)

    def test_a_calibracao_do_tempo_PRESERVA_o_mercado(self):
        t = {"time": MatchupTotals(mean=32.0, sd=4.0, dist="normal", metric="time")}
        self.assertEqual(le.apply_time_sd_calibration(t)["time"].metric, "time")

    def test_total_sem_mercado_continua_valendo_como_antes(self):
        """Quem constroi MatchupTotals sem dizer o mercado (codigo antigo,
        testes antigos) tem de continuar funcionando exatamente como era."""
        t = MatchupTotals(mean=11.58, sd=4.74, dist="normal")
        self.assertIsNone(t.metric)
        esperado = 1.0 - le._norm_cdf(13.5, 11.58, 4.74)
        self.assertAlmostEqual(prob_over_from_total(t, 13.5), esperado, places=12)


class TestAFormaMudaOPrecoOndeDeve(unittest.TestCase):

    def setUp(self):
        if not le._forma_dos_totais():
            self.skipTest("o artefato totais_forma_empirica.json nao esta aqui")

    def test_torres_fica_MENOS_achatada_que_a_curva(self):
        """O ponto todo: com o espalhamento certo, uma linha acima da media
        fica bem menos provavel do que a curva larga dizia."""
        curva = MatchupTotals(mean=11.58, sd=4.74, dist="normal")
        forma = MatchupTotals(mean=11.58, sd=4.74, dist="normal", metric="towers")
        self.assertLess(prob_over_from_total(forma, 13.5),
                        prob_over_from_total(curva, 13.5) - 0.10)

    def test_o_sd_nao_importa_mais_para_quem_usa_a_forma(self):
        """A forma substitui a curva inteira; o sd exagerado deixa de pesar."""
        a = MatchupTotals(mean=11.58, sd=4.74, dist="normal", metric="towers")
        b = MatchupTotals(mean=11.58, sd=1.00, dist="normal", metric="towers")
        self.assertAlmostEqual(prob_over_from_total(a, 13.5),
                               prob_over_from_total(b, 13.5), places=12)

    def test_abates_sai_IDENTICO_ao_de_antes(self):
        k1 = MatchupTotals(mean=30.4, sd=10.4, dist="normal")
        k2 = MatchupTotals(mean=30.4, sd=10.4, dist="normal", metric="kills")
        self.assertEqual(prob_over_from_total(k1, 31.5),
                         prob_over_from_total(k2, 31.5))

    def test_a_funcao_das_TELAS_tambem_herda(self):
        """resumo_core, lines_table_core e consistencia chamam
        `total_over_prob`, nao `prob_over_from_total`."""
        t = MatchupTotals(mean=11.58, sd=4.74, dist="normal", metric="towers")
        self.assertEqual(total_over_prob(t, 13.5), prob_over_from_total(t, 13.5))

    def test_probabilidade_sempre_entre_0_e_1(self):
        for linha in (-50.0, 0.5, 11.5, 30.5, 500.0):
            p = prob_over_from_total(
                MatchupTotals(mean=11.58, sd=4.74, dist="normal", metric="towers"), linha)
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 1.0)

    def test_linha_mais_alta_da_probabilidade_menor_ou_igual(self):
        t = MatchupTotals(mean=11.58, sd=4.74, dist="normal", metric="towers")
        ps = [prob_over_from_total(t, x + 0.5) for x in range(5, 20)]
        for a, b in zip(ps, ps[1:]):
            self.assertGreaterEqual(a, b)


class TestSemOArtefatoNadaEstoura(unittest.TestCase):
    """Um preco pior e ruim; um preco que estoura e pior."""

    def test_sem_arquivo_cai_na_curva_de_sempre(self):
        guardado = dict(le._FORMA_CACHE)
        try:
            le._FORMA_CACHE.clear()
            le._FORMA_CACHE["tabela"] = {}          # como se o arquivo faltasse
            t = MatchupTotals(mean=11.58, sd=4.74, dist="normal", metric="towers")
            esperado = 1.0 - le._norm_cdf(13.5, 11.58, 4.74)
            self.assertAlmostEqual(prob_over_from_total(t, 13.5), esperado, places=12)
        finally:
            le._FORMA_CACHE.clear()
            le._FORMA_CACHE.update(guardado)

    def test_media_invalida_nao_vira_numero(self):
        t = MatchupTotals(mean=float("nan"), sd=4.74, dist="normal", metric="towers")
        self.assertTrue(math.isnan(prob_over_from_total(t, 13.5)))


class TestOArtefatoFoiMontadoSoComOPassado(unittest.TestCase):
    """2026 e o ano da avaliacao cega. Se ele entrar no artefato, o gate
    passa a medir o proprio treino."""

    def test_os_anos_de_ajuste_nao_incluem_o_ano_cego(self):
        alvo = RAIZ / "totais_forma_empirica.json"
        if not alvo.exists():
            self.skipTest("artefato ausente")
        d = json.loads(alvo.read_text(encoding="utf-8"))
        self.assertNotIn(2026, d.get("_anos_de_ajuste") or [])
        self.assertTrue(d.get("_anos_de_ajuste"))

    def test_os_quantis_estao_em_ordem(self):
        alvo = RAIZ / "totais_forma_empirica.json"
        if not alvo.exists():
            self.skipTest("artefato ausente")
        d = json.loads(alvo.read_text(encoding="utf-8"))
        for m, reg in d["mercados"].items():
            q = reg["quantis"]
            self.assertEqual(q, sorted(q), "quantis fora de ordem em %s" % m)
            self.assertGreater(reg["n"], 2000)


if __name__ == "__main__":
    unittest.main()
