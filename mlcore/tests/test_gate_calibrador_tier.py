# -*- coding: utf-8 -*-
"""tools/gate_calibrador_tier.py (16/10/2026): o gate do tier no calibrador com grupo.

O que precisa ser verdade para o resultado dele valer:
  1. ele SO mede -- nao pode gravar em params_fitted.json nem tocar no app;
  2. a base e o procedimento de PRODUCAO (os 4 agrupamentos de hoje), nao a
     cadeia crua -- base fraca da ACCEPT falso (CLAUDE.md);
  3. os candidatos novos tem POUCOS niveis (o gate de 04/09 mediu que 79
     grupos fazem o ganho sumir);
  4. o teste pareado da o p certo.
"""
from __future__ import annotations

import math
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from tools import gate_calibrador_tier as g

RAIZ = Path(__file__).resolve().parents[2]


class TestSoMede(unittest.TestCase):

    def test_nao_grava_em_params_nem_importa_o_app(self):
        fonte = (RAIZ / "tools" / "gate_calibrador_tier.py").read_text(encoding="utf-8")
        self.assertNotIn("params_fitted.json\"", fonte.replace("params_fitted.json.", ""))
        self.assertNotIn("--escrever", fonte)
        self.assertNotIn("from app_core", fonte)


class TestCandidatos(unittest.TestCase):

    def test_a_base_e_o_procedimento_de_producao(self):
        from mlcore.agrupamentos import AGRUPAMENTOS
        self.assertEqual(set(g.ATUAIS), set(AGRUPAMENTOS))

    def test_os_novos_tem_poucos_niveis(self):
        ligas = ["LCK", "LPL", "LEC", "LCS", "CBLOL", "EM", "LFL", "LCKC", "AL", "MSI"]
        bos, fases = ["1", "3", "5"], ["regular", "playoffs"]
        for nome, chave in g.NOVOS.items():
            niveis = {chave(SimpleNamespace(league=lg, bo=b, phase=f))
                      for lg in ligas for b in bos for f in fases}
            self.assertLessEqual(len(niveis), 12, (nome, niveis))

    def test_t1_e_o_tier_do_repositorio(self):
        self.assertEqual(g._t1(SimpleNamespace(league="LCK")), "T1")
        self.assertEqual(g._t1(SimpleNamespace(league="LCKC")), "resto")
        self.assertEqual(g._t12(SimpleNamespace(league="CBLOL")), "T2")


class TestPareado(unittest.TestCase):

    def test_sem_diferenca_da_p_alto(self):
        rng = np.random.default_rng(1)
        a = rng.uniform(0.3, 0.9, 5000)
        _, _, p = g.pareado(a, a + rng.normal(0, 0.05, 5000))
        self.assertGreater(p, 0.01)

    def test_ganho_real_da_p_baixo_e_sinal_certo(self):
        rng = np.random.default_rng(2)
        atual = rng.uniform(0.5, 0.9, 5000)
        novo = atual - 0.01 + rng.normal(0, 0.02, 5000)
        m, se, p = g.pareado(atual, novo)
        self.assertAlmostEqual(m, 0.01, delta=4 * se)
        self.assertLess(p, 1e-6)
        self.assertTrue(math.isfinite(se))


if __name__ == "__main__":
    unittest.main()
