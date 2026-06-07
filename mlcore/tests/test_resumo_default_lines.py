"""Resumo default-lines behavior.

Contrato (2026-06): RESPEITA o que o usuário digitou.
- Campo vazio → padrão FIXO da métrica (27.5 kills, ...), nunca um valor de um
  confronto anterior (sem "fantasma 25.5").
- Campo com linhas → usa EXATAMENTE essas (o usuário pode remover o padrão, ex.:
  deixar só 28.5). Antes o padrão era forçado junto e não dava pra remover.
"""
from __future__ import annotations

import unittest

from app_core.resumo_runtime_core import RESUMO_DEFAULT_LINES, merge_with_default_lines


class TestResumoDefaultLines(unittest.TestCase):

    def test_empty_shows_standard_default(self):
        self.assertEqual(merge_with_default_lines("kills", []), [27.5])
        self.assertEqual(merge_with_default_lines("towers", []), [11.5])
        self.assertEqual(merge_with_default_lines("dragons", []), [4.5])
        self.assertEqual(merge_with_default_lines("barons", []), [1.5])
        self.assertEqual(merge_with_default_lines("inhibitors", []), [1.5])
        self.assertEqual(merge_with_default_lines("time", []), [32.5])

    def test_typed_lines_are_respected_exactly(self):
        # Usuário digitou só 5.5 → analisa SÓ 5.5 (o padrão 11.5 NÃO é forçado;
        # ele pode remover o padrão de propósito).
        self.assertEqual(merge_with_default_lines("towers", [5.5]), [5.5])
        self.assertEqual(merge_with_default_lines("towers", [12.5]), [12.5])
        # Tirou 27.5 e deixou só 28.5 (o caso exato do bug): só 28.5.
        self.assertEqual(merge_with_default_lines("kills", [28.5]), [28.5])

    def test_multiple_custom_lines_respected_sorted(self):
        # Várias linhas digitadas: usa só elas, ordenadas (sem injetar o padrão).
        self.assertEqual(merge_with_default_lines("kills", [30.5, 26.5]), [26.5, 30.5])
        # Se o usuário INCLUIR o padrão junto, ele aparece (porque foi digitado).
        self.assertEqual(merge_with_default_lines("kills", [27.5, 28.5]), [27.5, 28.5])

    def test_typing_the_default_is_not_duplicated(self):
        self.assertEqual(merge_with_default_lines("kills", [27.5]), [27.5])

    def test_unknown_metric_empty_stays_empty(self):
        self.assertEqual(merge_with_default_lines("unknown", []), [])

    def test_default_is_a_copy_not_shared_reference(self):
        # Mutating the returned list must not corrupt the module constant.
        out = merge_with_default_lines("kills", [])
        out.append(99.0)
        self.assertEqual(RESUMO_DEFAULT_LINES["kills"], [27.5])


if __name__ == "__main__":
    unittest.main()
