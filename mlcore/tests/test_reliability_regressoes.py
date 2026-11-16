# -*- coding: utf-8 -*-
"""A parte "regressoes" da nota de Confiabilidade (22/10/2026).

Ela chamava `powershell -File tools/check_regression.ps1`. No robo (ubuntu) nao
existe powershell, e no PC o ps1 usava o python do PATH em vez do .venv: a
parte dava ZERO com as regressoes passando. Agora a lista roda pelo proprio
Python -- e ela tem que continuar IGUAL a do ps1, que segue para uso a mao.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from tools import reliability_scorecard as r

RAIZ = Path(__file__).resolve().parents[2]


class TestRegressoesSemPowershell(unittest.TestCase):

    def test_lista_igual_a_do_ps1(self):
        ps1 = (RAIZ / "tools" / "check_regression.ps1").read_text(encoding="utf-8")
        do_ps1 = re.findall(r'"(mlcore\.tests\.[\w.]+)"', ps1)
        self.assertEqual(r.REGR_TESTS, do_ps1)

    def test_nao_chama_powershell(self):
        fonte = (RAIZ / "tools" / "reliability_scorecard.py").read_text(encoding="utf-8")
        self.assertNotIn('"powershell"', fonte)


class TestAlarmeDeQualidadeNoRobo(unittest.TestCase):
    """22/10/2026: o alarme pos-retreino so rodava na manutencao do app (ultima
    vez 14/07) e o baseline vivia fora do git -- no robo ele fixaria o atual e
    diria ok para sempre."""

    def test_roda_no_vigia_e_publica_o_baseline(self):
        yml = (RAIZ / ".github" / "workflows" / "nota_semanal.yml").read_text(encoding="utf-8")
        self.assertIn("python tools/ml_quality_check.py", yml)
        self.assertIn("ops/monitoring/ml_quality_baseline.json", yml)
        self.assertIn('grep -q "verdict=fail" qualidade_out.txt', yml)

    def test_o_baseline_existe_no_repositorio(self):
        self.assertTrue((RAIZ / "ops" / "monitoring" / "ml_quality_baseline.json").exists())


if __name__ == "__main__":
    unittest.main()
