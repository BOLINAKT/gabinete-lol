# -*- coding: utf-8 -*-
"""Apostas simuladas da regua modelo x Pinnacle (27/10/2026)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import modelo_contra_a_casa as mc  # noqa: E402


class TestApostasSimuladas(unittest.TestCase):
    def test_aposta_so_na_faixa_e_com_a_margem_de_volta(self):
        casos = [{"liga": "LCK", "p_modelo": 0.6, "p_mercado": 0.5, "y": 1, "margem": 4, "gameid": "1"},   # +15%: aposta
                 {"liga": "LCK", "p_modelo": 0.3, "p_mercado": 0.5, "y": 1, "margem": 4, "gameid": "2"},   # +34% no outro lado: fora
                 {"liga": "LPL", "p_modelo": 0.5, "p_mercado": 0.5, "y": 0, "margem": 4, "gameid": "3"}]   # -4%: nada
        r = mc.apostas_simuladas(casos)
        self.assertEqual(r["total"]["apostas"], 1)
        self.assertAlmostEqual(r["total"]["lucro"], round(1 / (0.5 * 1.04) - 1, 2))
        self.assertEqual(list(r["por_liga"]), ["LCK"])


if __name__ == "__main__":
    unittest.main()
