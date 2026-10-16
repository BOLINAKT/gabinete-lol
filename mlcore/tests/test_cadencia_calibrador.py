# -*- coding: utf-8 -*-
"""tools/cadencia_calibrador.py (16/10/2026): com que cadencia reajustar o calibrador.

O que precisa ser verdade para o resultado valer:
  1. o gatilho (P3) dispara com calibracao torta e fica quieto com calibracao
     certa -- senao ele vira um "mensal" ou um "nunca" disfarcado;
  2. a janela de reajuste e a MESMA do ajustador de producao -- medir uma
     janela e servir outra e divergencia treino/servico (D8);
  3. o plano (trimestral, Bonferroni, minimo do gatilho) nao mudou depois de
     visto o resultado -- ele foi fixado antes de rodar.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import numpy as np

from tools import cadencia_calibrador as c

RAIZ = Path(__file__).resolve().parents[2]


def _gerar(inclinacao_real, n=3000, semente=5, intercepto=0.0):
    rng = np.random.default_rng(semente)
    p = rng.uniform(0.2, 0.8, n)
    z = np.log(p / (1 - p))
    verdade = 1 / (1 + np.exp(-(intercepto + inclinacao_real * z)))
    return p, (rng.uniform(size=n) < verdade).astype(float)


class TestGatilho(unittest.TestCase):

    def test_quieto_com_calibracao_certa(self):
        p, y = _gerar(1.0)
        disparou, a0, b1 = c.fraca(p, y)
        self.assertFalse(disparou, (a0, b1))

    def test_dispara_com_modelo_timido(self):
        p, y = _gerar(1.6)
        self.assertTrue(c.fraca(p, y)[0])

    def test_dispara_com_vies_de_nivel(self):
        p, y = _gerar(1.0, intercepto=0.4)
        self.assertTrue(c.fraca(p, y)[0])


class TestPlano(unittest.TestCase):

    def test_janela_e_a_do_ajustador_de_producao(self):
        fonte = (RAIZ / "tools" / "ajustar_calibrador_grupo.py").read_text(encoding="utf-8")
        padrao = int(re.search(r'"--janela", type=int, default=(\d+)', fonte).group(1))
        self.assertEqual(c.JANELA, padrao)

    def test_plano_fixado(self):
        self.assertEqual(c.TRIMESTRAL, ("2026-04", "2026-07", "2026-10"))
        self.assertAlmostEqual(c.ALFA, 0.05 / 3)
        self.assertEqual(c.MIN_GATILHO, 200)

    def test_so_mede(self):
        fonte = (RAIZ / "tools" / "cadencia_calibrador.py").read_text(encoding="utf-8")
        self.assertNotIn("--escrever", fonte)
        self.assertNotIn("postfusion_group_calibration", fonte)


class TestORoboReajustaTrimestral(unittest.TestCase):
    """A decisao (trimestral) so vale se o robo a executa: depois do modelo novo,
    so em jan/abr/jul/out, e publicando o params_fitted.json."""

    def test_o_passo_existe_na_ordem_certa(self):
        yml = (RAIZ / ".github" / "workflows" / "retreino_completo.yml").read_text(encoding="utf-8")
        treino = yml.index("python -m mlcore.train_offline")
        reajuste = yml.index("python tools/ajustar_calibrador_grupo.py --escrever")
        commit = yml.index("git add ml_artifact.json")
        self.assertLess(treino, reajuste)
        self.assertLess(reajuste, commit)
        self.assertIn("01|04|07|10)", yml)
        linha_add = [l for l in yml.splitlines() if "git add ml_artifact.json" in l][0]
        self.assertIn("params_fitted.json", linha_add)


if __name__ == "__main__":
    unittest.main()
