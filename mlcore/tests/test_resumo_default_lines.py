"""Resumo default-lines behavior (kills the 'ghost 25.5' leak).

When the user types no custom line for a metric, the Resumo must fall back to a
FIXED standard line (27.5 kills, 11.5 torres, ...) — never to a value left over
from a previous matchup. A line the user does type replaces the default.
"""
from __future__ import annotations

import unittest

from app_core.resumo_runtime_core import RESUMO_DEFAULT_LINES, lines_or_default


class TestResumoDefaultLines(unittest.TestCase):

    def test_empty_falls_back_to_standard(self):
        self.assertEqual(lines_or_default("kills", []), [27.5])
        self.assertEqual(lines_or_default("towers", []), [11.5])
        self.assertEqual(lines_or_default("dragons", []), [4.5])
        self.assertEqual(lines_or_default("barons", []), [1.5])
        self.assertEqual(lines_or_default("inhibitors", []), [1.5])
        self.assertEqual(lines_or_default("time", []), [32.5])

    def test_custom_line_replaces_default(self):
        # User typed 25.5 → only 25.5 shows; the default 27.5 does NOT leak in.
        self.assertEqual(lines_or_default("kills", [25.5]), [25.5])

    def test_multiple_custom_lines_preserved(self):
        self.assertEqual(lines_or_default("kills", [26.5, 27.5]), [26.5, 27.5])

    def test_unknown_metric_empty_stays_empty(self):
        self.assertEqual(lines_or_default("unknown", []), [])

    def test_default_is_a_copy_not_shared_reference(self):
        # Mutating the returned list must not corrupt the module constant.
        out = lines_or_default("kills", [])
        out.append(99.0)
        self.assertEqual(RESUMO_DEFAULT_LINES["kills"], [27.5])


if __name__ == "__main__":
    unittest.main()
