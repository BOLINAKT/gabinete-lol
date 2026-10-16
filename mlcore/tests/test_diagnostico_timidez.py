# -*- coding: utf-8 -*-
"""tools/diagnostico_timidez.py (16/10/2026): a conta da inclinacao de calibracao.

O diagnostico diz "timido" quando a inclinacao passa de 1 e "extremo" quando
fica abaixo. Se a regressao logistica dele errasse, a conclusao da frente
(o modelo perde para a Pinnacle por INFORMACAO, nao por calibracao) cairia junto.
Aqui ela tem que recuperar inclinacoes conhecidas em dado sintetico.
"""
from __future__ import annotations

import unittest

import numpy as np

from tools.diagnostico_timidez import logistica, logit


def _sintetico(inclinacao, n=40000, semente=7):
    """p do 'modelo' e resultado gerado por logit(verdade) = inclinacao * logit(p)."""
    rng = np.random.default_rng(semente)
    p = rng.uniform(0.15, 0.85, n)
    verdade = 1 / (1 + np.exp(-inclinacao * logit(p)))
    y = (rng.uniform(size=n) < verdade).astype(float)
    return p, y


class TestInclinacao(unittest.TestCase):

    def test_modelo_bem_calibrado_da_inclinacao_1(self):
        p, y = _sintetico(1.0)
        b, se = logistica(np.column_stack([np.ones(len(p)), logit(p)]), y)
        self.assertAlmostEqual(b[1], 1.0, delta=3 * se[1])
        self.assertAlmostEqual(b[0], 0.0, delta=3 * se[0])

    def test_modelo_timido_da_inclinacao_maior_que_1(self):
        p, y = _sintetico(1.4)
        b, se = logistica(np.column_stack([np.ones(len(p)), logit(p)]), y)
        self.assertAlmostEqual(b[1], 1.4, delta=3 * se[1])
        self.assertGreater(b[1] - 1.96 * se[1], 1.0)

    def test_modelo_extremo_da_inclinacao_menor_que_1(self):
        p, y = _sintetico(0.6)
        b, se = logistica(np.column_stack([np.ones(len(p)), logit(p)]), y)
        self.assertAlmostEqual(b[1], 0.6, delta=3 * se[1])
        self.assertLess(b[1] + 1.96 * se[1], 1.0)

    def test_encompassing_da_zero_para_quem_nao_traz_informacao(self):
        """O teste C: um 'modelo' que e so ruido em cima da casa nao pode ganhar peso."""
        rng = np.random.default_rng(3)
        n = 30000
        casa = rng.uniform(0.15, 0.85, n)
        y = (rng.uniform(size=n) < casa).astype(float)
        ruido = 1 / (1 + np.exp(-(0.5 * logit(casa) + rng.normal(0, 0.5, n))))
        b, se = logistica(np.column_stack([np.ones(n), logit(casa), logit(ruido)]), y)
        self.assertAlmostEqual(b[1], 1.0, delta=4 * se[1])
        self.assertLess(abs(b[2]), 3 * se[2])


if __name__ == "__main__":
    unittest.main()
