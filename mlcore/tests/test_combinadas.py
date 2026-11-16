# -*- coding: utf-8 -*-
"""ML + total: a odd justa da combinada (app_core/combinadas_core.py)."""
import unittest

import pandas as pd

from app_core import combinadas_core as cb


def _tg():
    rows = []
    for i in range(12):
        # A vence os pares com jogos CURTOS (28 min) e perde os impares (36 min)
        for t, venceu, tempo in (("A", i % 2 == 0, 28 if i % 2 == 0 else 36), ("B", i % 2 == 1, 30)):
            rows.append({"gameid": f"{t}{i}", "date": f"2026-03-{i + 1:02d}", "league": "LCK", "split": "S",
                         "map_number": 1, "team": t, "opponent": f"x{i}", "win": int(venceu),
                         "kills_for": 15, "kills_against": 14, "game_time_min": tempo, "total_kills": 29})
    return pd.DataFrame(rows)


class TestCombinadas(unittest.TestCase):
    def test_tempo_condicional_e_soma_um(self):
        r = cb.combinadas(_tg(), "A", "B", 31.5, "time", 0.6)
        self.assertTrue(r["condicional"])
        self.assertAlmostEqual(sum(c["p"] for c in r["combos"]), 1.0, places=6)
        a_menos = next(c for c in r["combos"] if c["time"] == "A" and c["lado"] == "under")
        self.assertGreater(a_menos["p_total_dado"], a_menos["p_total"])   # A vence -> jogo curto
        self.assertEqual(a_menos["hist"][0], a_menos["hist"][1] - 0)      # jogos que A venceu: todos < 31,5

    def test_kills_multiplica_as_pernas(self):
        r = cb.combinadas(_tg(), "A", "B", 28.5, "kills", 0.6)
        self.assertFalse(r["condicional"])
        for c in r["combos"]:
            self.assertAlmostEqual(c["p_total_dado"], c["p_total"], places=9)
        self.assertIn("multiplicação", cb.html_combinadas(r, "kills"))


if __name__ == "__main__":
    unittest.main()
