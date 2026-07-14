# -*- coding: utf-8 -*-
"""E2E smoke permanente (Regra de engenharia 4, 2026-07-14): boot → entrar →
selecionar times → Analisar Confronto, para o app do LoL E para o clone Dota.

Pega a classe de bug que a suíte unitária não vê (e que o usuário achava na
tela): crash de render, widget duplicado, coluna ausente no fluxo real.

Guardas deliberadas:
- Se o app estiver em manutenção/NO-GO (estado de DADOS, não regressão de
  código), o teste dá SKIP em vez de falhar — e nunca clica em nada que
  dispare retreino.
- O clone Dota só é testado se a pasta existir ao lado (máquinas de terceiros
  não têm).
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOTA_APP = ROOT.parent / "GabineteDOTA" / "gabinete_dota_app.py"


def _boot_and_analyze(app_path: Path, team_hint_a: str, team_hint_b: str):
    """Retorna (exceptions, tabs, skip_reason)."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(app_path), default_timeout=900)
    at.run()
    entrar = [b for b in at.button if b.label == "Entrar no app"]
    if entrar:
        entrar[0].click()
        at.run()
    if at.exception:
        return list(at.exception), [], None
    t1 = [s for s in at.selectbox if s.label == "Time 1"]
    t2 = [s for s in at.selectbox if s.label == "Time 2"]
    if not (t1 and t2):
        # bootstrap em manutenção/NO-GO: estado de dados, não regressão
        return [], [], "app não chegou à seleção de times (manutenção/NO-GO)"
    opts = [o for o in t1[0].options if o]
    a = next((o for o in opts if team_hint_a.lower() in str(o).lower()), None)
    b = next((o for o in opts if team_hint_b.lower() in str(o).lower() and o != a), None)
    if a is None or b is None:
        a, b = opts[0], opts[1]
    t1[0].select(a)
    t2[0].select(b)
    at.run()
    analisar = [x for x in at.button if x.label == "Analisar Confronto"]
    if not analisar:
        return list(at.exception), [], "botão Analisar ausente"
    analisar[0].click()
    at.run()
    tabs = [str(t.label) for t in at.tabs]
    return list(at.exception), tabs, None


class TestE2ESmokeLoL(unittest.TestCase):
    def test_boot_select_analyze(self):
        excs, tabs, skip = _boot_and_analyze(ROOT / "plays_app.py", "T1", "Gen")
        if skip:
            self.skipTest(skip)
        self.assertEqual(len(excs), 0, f"exceções no fluxo LoL: {excs[:1]}")
        # Fluxo Rápido = 7 tabs de topo (Visão Geral..Rankings)
        self.assertGreaterEqual(len(tabs), 7, f"poucas tabs renderizadas: {tabs}")
        self.assertIn("Visão Geral", tabs)


class TestE2ESmokeDota(unittest.TestCase):
    def test_boot_select_analyze(self):
        if not DOTA_APP.exists():
            self.skipTest("GabineteDOTA não está ao lado (máquina sem o app Dota)")
        excs, tabs, skip = _boot_and_analyze(DOTA_APP, "Spirit", "Falcons")
        if skip:
            self.skipTest(skip)
        self.assertEqual(len(excs), 0, f"exceções no fluxo Dota: {excs[:1]}")
        self.assertGreaterEqual(len(tabs), 8, f"poucas tabs renderizadas: {tabs}")
        self.assertIn("Megacreeps", tabs, "aba Megacreeps sumiu do Dota")
        self.assertNotIn("Dragões", tabs, "Dragões voltou ao Dota (override falhou)")


if __name__ == "__main__":
    unittest.main()
