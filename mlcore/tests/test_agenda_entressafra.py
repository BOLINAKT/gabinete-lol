# -*- coding: utf-8 -*-
"""Entressafra (15/11/2026): coleta vazia depois que a agenda gravada so tem jogo ja acontecido
nao e erro -- a agenda vazia e a verdade."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tools.coletar_agenda import agenda_anterior_ja_passou

AGORA = datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc)


def _arq(tmp, jogos):
    p = Path(tmp) / "agenda.json"
    p.write_text(json.dumps({"jogos": jogos}), encoding="utf-8")
    return p


class TestEntressafra(unittest.TestCase):
    def test_final_de_anteontem_ja_passou(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(agenda_anterior_ja_passou(_arq(tmp, [{"inicio_utc": "2026-11-14T19:00:00Z"}]), AGORA))

    def test_jogo_de_hoje_ou_futuro_nao(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(agenda_anterior_ja_passou(_arq(tmp, [{"inicio_utc": "2026-11-15T20:00:00Z"}]), AGORA))
            self.assertFalse(agenda_anterior_ja_passou(
                _arq(tmp, [{"inicio_utc": "2026-11-14T19:00:00Z"}, {"inicio_utc": "2026-11-17T19:00:00Z"}]), AGORA))

    def test_sem_data_ou_sem_arquivo_nao_libera(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(agenda_anterior_ja_passou(_arq(tmp, [{"inicio_utc": None}]), AGORA))
            self.assertFalse(agenda_anterior_ja_passou(_arq(tmp, []), AGORA))
            self.assertFalse(agenda_anterior_ja_passou(Path(tmp) / "nao_existe.json", AGORA))


if __name__ == "__main__":
    unittest.main()
