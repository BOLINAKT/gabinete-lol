# -*- coding: utf-8 -*-
"""Ajuste de força (gap WHR) nos mercados First X — só nos eventos DECIDIDOS.

Base empírica (22/07, 10.638 jogos OOS): first_tower +0.78% e first_baron
+1.16% de ganho no Brier (ACCEPT); first_blood e first_dragon ~neutro (não
ajustam). Estes testes travam a regra e o comportamento seguro.
"""
from __future__ import annotations

import math
import unittest

from app_core.first_x_gap_core import (
    FIRST_X_GAP_CALIB,
    adjust_first_x_prob,
    first_x_gap_supported,
)


class SuporteDeEventoTests(unittest.TestCase):
    def test_so_eventos_decididos_recebem_ajuste(self):
        self.assertTrue(first_x_gap_supported("firsttower"))
        self.assertTrue(first_x_gap_supported("firstbaron"))
        # os cedo/aleatórios NÃO — medido ~neutro
        self.assertFalse(first_x_gap_supported("firstblood"))
        self.assertFalse(first_x_gap_supported("firstdragon"))
        self.assertFalse(first_x_gap_supported("firstherald"))

    def test_tolera_caixa_e_espaco(self):
        self.assertTrue(first_x_gap_supported("  FirstBaron "))

    def test_entrada_vazia(self):
        self.assertFalse(first_x_gap_supported(""))
        self.assertFalse(first_x_gap_supported(None))


class AjusteTests(unittest.TestCase):
    def test_time_mais_forte_sobe_a_probabilidade(self):
        p, info = adjust_first_x_prob(0.50, event_col="firstbaron", mu_gap=+1.0)
        self.assertTrue(info["applied"])
        self.assertGreater(p, 0.50)

    def test_time_mais_fraco_desce_a_probabilidade(self):
        p, info = adjust_first_x_prob(0.50, event_col="firstbaron", mu_gap=-1.0)
        self.assertTrue(info["applied"])
        self.assertLess(p, 0.50)

    def test_gap_zero_nao_muda_nada(self):
        p, _ = adjust_first_x_prob(0.42, event_col="firsttower", mu_gap=0.0)
        self.assertAlmostEqual(p, 0.42, places=9)

    def test_evento_cedo_passa_intacto(self):
        # first_blood não ajusta, mesmo com gap enorme (medido ~neutro)
        p, info = adjust_first_x_prob(0.50, event_col="firstblood", mu_gap=+5.0)
        self.assertEqual(p, 0.50)
        self.assertFalse(info["applied"])
        self.assertEqual(info["reason"], "evento_sem_ajuste_medido")

    def test_simetria_do_ajuste(self):
        """Favorito ganha o que o azarão perde (em logit) — sem viés de lado."""
        pa, _ = adjust_first_x_prob(0.50, event_col="firstbaron", mu_gap=+1.5)
        pb, _ = adjust_first_x_prob(0.50, event_col="firstbaron", mu_gap=-1.5)
        self.assertAlmostEqual(pa + pb, 1.0, places=9)

    def test_resultado_sempre_probabilidade_valida(self):
        for gap in (-50.0, -1.0, 0.0, 1.0, 50.0):
            for base in (0.01, 0.5, 0.99):
                p, _ = adjust_first_x_prob(base, event_col="firstbaron", mu_gap=gap)
                self.assertGreater(p, 0.0)
                self.assertLess(p, 1.0)

    def test_gap_indisponivel_devolve_base(self):
        p, info = adjust_first_x_prob(0.55, event_col="firstbaron", mu_gap=None)
        self.assertEqual(p, 0.55)
        self.assertFalse(info["applied"])
        self.assertEqual(info["reason"], "gap_indisponivel")
        p2, _ = adjust_first_x_prob(0.55, event_col="firstbaron", mu_gap=float("nan"))
        self.assertEqual(p2, 0.55)

    def test_p_base_invalida_nao_inventa_numero(self):
        p, info = adjust_first_x_prob("lixo", event_col="firstbaron", mu_gap=1.0)
        self.assertTrue(math.isnan(p))
        self.assertFalse(info["applied"])

    def test_info_traz_rastro(self):
        _, info = adjust_first_x_prob(0.5, event_col="firsttower", mu_gap=2.0)
        for k in ("applied", "event", "p_before", "p_after", "mu_gap", "beta", "diff_pp"):
            self.assertIn(k, info)


class CalibracaoTests(unittest.TestCase):
    """Os coeficientes vêm da medição OOS — travados para não virarem chute."""

    def test_apenas_os_dois_eventos_aceitos(self):
        self.assertEqual(set(FIRST_X_GAP_CALIB), {"firsttower", "firstbaron"})

    def test_betas_positivos(self):
        # mais forte => mais provável pegar o objetivo decidido
        for k, cal in FIRST_X_GAP_CALIB.items():
            self.assertGreater(cal["beta"], 0.0, k)
            self.assertGreater(cal["gap_sd"], 0.0, k)


if __name__ == "__main__":
    unittest.main()
