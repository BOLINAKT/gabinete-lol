# -*- coding: utf-8 -*-
"""Os 4 sinais dele numa linha de total de kills (app_core/sinais_linha_core.py)."""
import unittest

import pandas as pd

from app_core import sinais_linha_core as sl


def _tg(tot_a, tot_b, n=10, liga="LCK"):
    rows = []
    for i in range(n):
        for t, o, tot in (("A", "x%d" % i, tot_a), ("B", "y%d" % i, tot_b)):
            rows.append({"gameid": f"{t}{i}", "date": f"2026-03-{i + 1:02d}", "league": liga, "split": "Spring",
                         "map_number": 1 + (i % 2), "team": t, "opponent": o, "kills_for": tot // 2,
                         "kills_against": tot - tot // 2, "total_kills": tot, "tend_adv_kills": 0.0})
    return pd.DataFrame(rows)


class TestSinais(unittest.TestCase):
    def test_times_over_passam_os_4_no_over(self):
        sn = sl.sinais(_tg(34, 32), "A", "B", 28.5)
        self.assertEqual(sl.passam(sn, "over"), [True, True, True, True])
        self.assertEqual(sl.passam(sn, "under"), [False, False, False, False])
        self.assertGreater(sl.chance(sn, "over"), 0.6)
        self.assertIn("4/4", sl.resumo_html(sn, "over"))

    def test_so_mapa1_usa_so_jogos_de_mapa1(self):
        sn = sl.sinais(_tg(34, 32), "A", "B", 28.5, so_mapa1=True)
        self.assertEqual(sn["n"], 10)                     # 5 de mapa 1 de cada time

    def test_pouco_jogo_nao_afirma(self):
        self.assertIsNone(sl.sinais(_tg(34, 32, n=3), "A", "B", 28.5))
        self.assertIn("pouco jogo", sl.resumo_html(None, "over"))


if __name__ == "__main__":
    unittest.main()
