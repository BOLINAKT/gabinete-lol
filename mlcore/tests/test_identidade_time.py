# -*- coding: utf-8 -*-
"""Identidade do time pelo elenco e vigia de troca de ID (26/11/2026)."""
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app_core import identidade_time_core as it  # noqa: E402

D = pd.Timestamp


def _j(*xs):
    return [(D(d), frozenset(e)) for d, e in xs]


class TestIdentidade(unittest.TestCase):
    def test_elenco_estavel(self):
        m = it.mudanca(_j(("2026-08-01", "abcde"), ("2026-10-01", "abcde"), ("2026-11-20", "abcde")))
        self.assertTrue(m["base_ok"])
        self.assertEqual(m["novos"], {})

    def test_jogador_novo_com_data(self):
        m = it.mudanca(_j(("2026-09-01", "abcde"), ("2026-11-10", "abcdx"), ("2026-11-20", "abcdx")))
        self.assertEqual(list(m["novos"]), ["x"])
        self.assertEqual(m["novos"]["x"], D("2026-11-10"))

    def test_confere(self):
        self.assertEqual(it.confere(list("abcdz"), frozenset("abcde")), (4, "ok"))
        self.assertEqual(it.confere(list("abcyz"), frozenset("abcde")), (3, "mexido"))
        self.assertEqual(it.confere(list("axyzw"), frozenset("abcde")), (1, "outro"))

    def test_troca_de_id(self):
        h = {"Velho": _j(("2026-09-01", "abcde"), ("2026-10-01", "abcde")),
             "Novo": _j(("2026-10-05", "abcde"), ("2026-11-20", "abcde")),
             "Outro": _j(("2026-10-05", "vwxyz"), ("2026-11-20", "vwxyz"))}
        ps = it.suspeitos_de_troca(h)
        self.assertEqual([(p["velho"], p["novo"], p["comum"]) for p in ps], [("Velho", "Novo", 5)])

    def test_nome_reaproveitado_por_outro_elenco_nao_une(self):
        h = {"4iki #1": _j(("2026-08-01", "abcde"), ("2026-09-06", "abcde")),
             "4iki": _j(("2026-10-31", "avwxy"), ("2026-11-20", "avwxy"))}
        self.assertEqual(it.suspeitos_de_troca(h), [])


if __name__ == "__main__":
    unittest.main()
