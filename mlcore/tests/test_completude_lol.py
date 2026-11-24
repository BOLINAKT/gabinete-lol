# -*- coding: utf-8 -*-
"""Completude da base do LoL contra a lolesports (24/11/2026): serie terminada fora da base aparece."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import completude_lol as CL  # noqa: E402

BASE = pd.DataFrame([
    {"gameid": "g1", "date": "2026-11-04 23:54:00", "teamname": "Gen.G", "position": "team"},
    {"gameid": "g1", "date": "2026-11-04 23:54:00", "teamname": "LYON", "position": "team"},
])
RES = {"Gen.G Esports": "Gen.G", "Gen.G": "Gen.G", "LYON": "LYON", "BILIBILI GAMING": "Bilibili Gaming"}.get


class TestCompletude(unittest.TestCase):

    def test_acha_o_que_falta_e_o_motivo(self):
        series = [{"inicio": "2026-11-04T23:00:00+00:00", "a": "Gen.G Esports", "b": "LYON", "liga": "Worlds", "placar": "3-1"},
                  {"inicio": "2026-11-14T19:00:00+00:00", "a": "Gen.G Esports", "b": "BILIBILI GAMING", "liga": "Worlds", "placar": "1-3"},
                  {"inicio": "2026-11-10T08:00:00+00:00", "a": "Saigon Warrior", "b": "LYON", "liga": "LCP", "placar": "3-0"}]
        f = CL.conferir(series, BASE, lambda n: RES(n) or "")
        self.assertEqual(len(f), 2)
        self.assertIn("ainda não tem", f[0]["motivo"])
        self.assertIn("Saigon Warrior", f[1]["motivo"])


if __name__ == "__main__":
    unittest.main()
