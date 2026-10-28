# -*- coding: utf-8 -*-
"""Nota por jogador do LoL (tools/nota_jogadores_lol.py + app_core/nota_jogadores_lol_core.py)."""
from __future__ import annotations

import math
import unittest

import pandas as pd

from app_core.nota_jogadores_lol_core import p_com_jogadores
import tools.nota_jogadores_lol as nj

DADOS = {"parametros": {"w_jogador": 0.7, "temperatura": 1.3},
         "times": {"T1": {"forca": 400.0, "liga_de_origem": "LCK"},
                   "Gen.G": {"forca": 500.0, "liga_de_origem": "LCK"},
                   "G2 Esports": {"forca": 420.0, "liga_de_origem": "LEC"},
                   "Maryville University": {"forca": 100.0, "liga_de_origem": "NACL"},
                   "Cloud9": {"forca": 200.0, "liga_de_origem": "LCS"}}}


def _jogo(dia, gid, a, b, y, liga, ea, eb, conta=True, na=None, nb=None):
    return (pd.Timestamp(dia), gid, a, b, y, ea, eb, liga, na or a, nb or b, conta)


class TestMistura(unittest.TestCase):
    def test_liga_nacional_mistura(self):
        r = p_com_jogadores("T1", "Gen.G", 0.55, dados=DADOS)
        self.assertTrue(r["aplicado"])
        pj = 1 / (1 + 10 ** (-(400 - 500) / 400))
        lg = lambda p: math.log(p / (1 - p))
        self.assertAlmostEqual(r["p_final"], 1 / (1 + math.exp(-1.3 * (0.3 * lg(0.55) + 0.7 * lg(pj)))))

    def test_fora_da_liga_nacional_nao_mexe(self):
        self.assertFalse(p_com_jogadores("T1", "G2 Esports", 0.55, dados=DADOS)["aplicado"])
        self.assertFalse(p_com_jogadores("Maryville University", "Cloud9", 0.4, dados=DADOS)["aplicado"])
        self.assertFalse(p_com_jogadores("T1", "Gen.G", 0.55, entre_regioes=True, dados=DADOS)["aplicado"])
        self.assertFalse(p_com_jogadores("T1", "Desconhecido", 0.55, dados=DADOS)["aplicado"])
        self.assertFalse(p_com_jogadores("T1", "Gen.G", float("nan"), dados=DADOS)["aplicado"])


class TestRobo(unittest.TestCase):
    def test_promocao_e_internacional_nao_contam_para_a_liga_de_origem(self):
        el = lambda p: [f"{p}{i}" for i in range(5)]
        jogos = [_jogo("2026-07-01", "g1", "mvl", "x", 1, "NACL", el("m"), el("x")),
                 _jogo("2026-10-05", "g2", "mvl", "c9", 0, "LCS", el("m"), el("c"), conta=False),
                 _jogo("2026-10-06", "g3", "mvl", "c9", 0, "LCS", el("m"), el("c"), conta=False),
                 _jogo("2026-10-07", "g4", "c9", "t1", 0, "WLDs", el("c"), el("t"))]
        out = nj.montar(jogos)["times"]
        self.assertEqual(out["mvl"]["liga_de_origem"], "NACL")
        self.assertIsNone(out["c9"]["liga_de_origem"])        # so promocao e Mundial no exemplo
        self.assertEqual(out["mvl"]["elenco"], 5)

    def test_historico_nunca_partido_nomes_do_mesmo_teamid(self):
        el = lambda p: [f"{p}{i}" for i in range(5)]
        jogos = [_jogo("2026-03-01", "g1", "oe:team:1", "oe:team:2", 1, "LCK", el("a"), el("b"), na="PVISION"),
                 _jogo("2026-07-01", "g2", "oe:team:1", "oe:team:2", 1, "LCK", el("a"), el("b"), na="PARIVISION")]
        out = nj.montar(jogos)["times"]
        self.assertIs(out["PVISION"], out["PARIVISION"])
        self.assertEqual(out["PARIVISION"]["nome_atual"], "PARIVISION")

    def test_quem_ganha_sobe(self):
        el = lambda p: [f"{p}{i}" for i in range(5)]
        out = nj.montar([_jogo("2026-03-01", "g1", "a", "b", 1, "LCK", el("a"), el("b"))])["times"]
        self.assertGreater(out["a"]["forca"], out["b"]["forca"])


if __name__ == "__main__":
    unittest.main()
