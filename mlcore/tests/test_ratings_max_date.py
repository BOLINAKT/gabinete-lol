# -*- coding: utf-8 -*-
"""O artifact tem que dizer a VERDADE sobre até onde os ratings foram.

`data_max_date` grava o fim de TODOS os dados; o train_offline só aplica aos
ratings até o corte do holdout. Confundir os dois é o que fez o incidente
holdout-180 (junho/2026) passar 4 dias despercebido: a "Manutenção completa"
chamou o train_offline sem holdout explícito, o default de 180 dias entrou, os
ratings congelaram em dezembro e o app rodou degradado com nota 4.97.

`ratings_max_date` é o carimbo honesto. A distância entre os dois É a defasagem,
e quem precisa dela é o update_incremental (para saber o que falta aplicar) e o
retrain_check (para contar jogos novos de verdade).
"""
from __future__ import annotations

import unittest

from mlcore.update_incremental import _parse_dt


def _escolhe(meta: dict):
    """Mesma precedência do update_incremental e do retrain_check."""
    return _parse_dt(meta.get("ratings_max_date")) or _parse_dt(meta.get("data_max_date"))


class TestRatingsMaxDate(unittest.TestCase):
    def test_prefere_o_carimbo_honesto(self) -> None:
        d = _escolhe({"data_max_date": "2026-08-16", "ratings_max_date": "2026-07-17"})
        self.assertEqual(d.date().isoformat(), "2026-07-17")

    def test_artifact_antigo_sem_a_chave_nao_muda_de_comportamento(self) -> None:
        d = _escolhe({"data_max_date": "2026-08-16"})
        self.assertEqual(d.date().isoformat(), "2026-08-16")

    def test_incremental_deixa_os_dois_iguais(self) -> None:
        """Ele aplica todo jogo novo direto nos ratings: não há defasagem."""
        meta = {"data_max_date": "2026-08-16", "ratings_max_date": "2026-08-16"}
        self.assertEqual(_escolhe(meta), _parse_dt(meta["data_max_date"]))

    def test_sem_carimbo_nenhum_devolve_nada(self) -> None:
        self.assertIsNone(_escolhe({}))

    def test_o_cenario_do_incidente_holdout_180(self) -> None:
        """Ratings congelados 180 dias atrás com os dados em dia: tem que aparecer."""
        meta = {"data_max_date": "2026-06-05", "ratings_max_date": "2025-12-07"}
        atraso = (_parse_dt(meta["data_max_date"]) - _parse_dt(meta["ratings_max_date"])).days
        self.assertGreater(atraso, 170)
        self.assertEqual(_escolhe(meta).date().isoformat(), "2025-12-07")


if __name__ == "__main__":
    unittest.main()
