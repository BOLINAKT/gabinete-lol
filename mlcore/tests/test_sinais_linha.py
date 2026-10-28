# -*- coding: utf-8 -*-
"""O metodo dele numa linha de total de kills (app_core/sinais_linha_core.py)."""
import unittest

import pandas as pd

from app_core import sinais_linha_core as sl


def _tg(tot_a, tot_b, n=10, liga="LCK", tend=0.0):
    rows = []
    for i in range(n):
        for t, o, tot in (("A", "x%d" % i, tot_a), ("B", "y%d" % i, tot_b)):
            rows.append({"gameid": f"{t}{i}", "date": f"2026-03-{i + 1:02d}", "league": liga, "split": "Spring",
                         "map_number": 1 + (i % 2), "team": t, "opponent": o, "kills_for": tot // 2,
                         "kills_against": tot - tot // 2, "total_kills": tot, "tend_adv_kills": tend})
    return pd.DataFrame(rows)


class TestMetodo(unittest.TestCase):
    def test_times_over_tudo_a_favor_do_mais(self):
        sn = sl.sinais(_tg(34, 32), "A", "B", 28.5)
        self.assertEqual(sl.passam(sn, "over"), [True, True, True, True])
        self.assertEqual(sl.passam(sn, "under"), [False, False, False, False])
        self.assertGreater(sl.chance(sn, "over"), 0.6)
        self.assertIn("4/4", sl.resumo_html(sn, "over"))

    def test_adversarios_over_explicam_a_media_alta(self):
        # media 30 contra a linha 29,5 (contra o Menos), mas os adversarios puxavam +4:
        # ajustada 30 - 0,46*4 = 28,2 -> o Menos volta a valer no passo 2
        sn = sl.sinais(_tg(30, 30, tend=4.0), "A", "B", 29.5)
        p = sl.passam(sn, "under")
        self.assertFalse(p[0])
        self.assertTrue(p[1])

    def test_stats_da_linha_teto_de_30_do_outro_lado(self):
        sn = sl.sinais(_tg(34, 32), "A", "B", 28.5)
        sn = dict(sn, camp_mais=0.625)                 # 75% e 50% de under -> 37,5% do outro lado
        self.assertFalse(sl.passam(sn, "under")[3])
        sn = dict(sn, camp_mais=0.25)
        self.assertTrue(sl.passam(sn, "under")[3])

    def test_so_mapa1_e_pouco_jogo(self):
        self.assertEqual(sl.sinais(_tg(34, 32), "A", "B", 28.5, so_mapa1=True)["a"]["n10"], 5)
        self.assertIsNone(sl.sinais(_tg(34, 32, n=3), "A", "B", 28.5))
        self.assertIn("pouco jogo", sl.resumo_html(None, "over"))


if __name__ == "__main__":
    unittest.main()
