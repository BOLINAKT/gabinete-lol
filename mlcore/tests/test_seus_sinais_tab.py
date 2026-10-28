# -*- coding: utf-8 -*-
"""A aba "Seus sinais" (app_core/seus_sinais_tab_core.py)."""
import unittest

import pandas as pd

from app_core import seus_sinais_tab_core as ss
from app_core.navigation import pick_tabs

JOGO = {"time1": "A", "time2": "B", "casas": {},
        "linhas": {"stake": [["kills", "total", 1, 27.5, 1.80, 1.95, None], ["kills", "total", 1, 25.5, 1.40, 2.80, None],
                             ["kills", "total", 2, 27.5, 1.85, 1.90, None]],
                   "polymarket": [["kills", "total", 1, 27.5, 1.96, 1.96, None]]}}


def _tg(tot_a, tot_b, n=10):
    rows = []
    for i in range(n):
        for t, tot in (("A", tot_a), ("B", tot_b)):
            rows.append({"gameid": f"{t}{i}", "date": f"2026-03-{i + 1:02d}", "league": "LCK", "split": "Spring",
                         "map_number": 1 + (i % 2), "team": t, "opponent": f"x{i}", "kills_for": tot // 2,
                         "kills_against": tot - tot // 2, "total_kills": tot, "tend_adv_kills": 0.0})
    return pd.DataFrame(rows)


class TestAba(unittest.TestCase):
    def test_e_a_primeira_aba_do_lol(self):
        self.assertEqual(pick_tabs("Fluxo Rápido")[0], "Seus sinais")

    def test_melhor_odd_por_lado_e_linha_principal(self):
        lk = ss.linhas_de_kills(JOGO, False, ["Stake", "Polymarket"])
        self.assertEqual(lk[27.5][1]["over"], (1.96, "Polymarket"))
        self.assertEqual(lk[27.5][1]["under"], (1.96, "Polymarket"))
        self.assertEqual(ss.linha_principal(lk), 27.5)               # a mais equilibrada do mapa 1

    def test_veredito(self):
        self.assertEqual(ss.veredito(2, 3.0), ss.VEREDITO_ENTRA)
        self.assertEqual(ss.veredito(3, -2.0), "2+ sinais, odd abaixo da fair")
        self.assertEqual(ss.veredito(1, 10.0), "não entra")

    def test_painel_mostra_o_numero_por_tras(self):
        from app_core.sinais_linha_core import sinais
        tg = _tg(34, 32)
        h = ss.html_painel("A", "B", 28.5, sinais(tg, "A", "B", 28.5), sinais(tg, "A", "B", 28.5, so_mapa1=True),
                           {"over": (1.90, "Stake")}, 0.6)
        self.assertIn("A 10/10", h)                                  # historico do time A
        self.assertIn("ENTRA", h)                                    # 4/4 no over e 1,90 acima da fair
        self.assertIn("LCK Spring", h)


if __name__ == "__main__":
    unittest.main()
