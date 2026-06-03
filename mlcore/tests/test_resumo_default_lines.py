"""Resumo default-lines behavior (kills the 'ghost 25.5' leak).

When the user types no custom line for a metric, the Resumo must fall back to a
FIXED standard line (27.5 kills, 11.5 torres, ...) — never to a value left over
from a previous matchup. A line the user does type replaces the default.
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

    def test_custom_line_is_added_to_default_and_sorted(self):
        # User typed towers 5.5 → both the default 11.5 AND 5.5 are analyzed,
        # sorted ascending (smaller line to the left).
        self.assertEqual(merge_with_default_lines("towers", [5.5]), [5.5, 11.5])
        # A larger custom line sits to the right of the default.
        self.assertEqual(merge_with_default_lines("towers", [12.5]), [11.5, 12.5])
        # Kills custom 25.5 keeps the standard 27.5 too (sorted).
        self.assertEqual(merge_with_default_lines("kills", [25.5]), [25.5, 27.5])

    def test_multiple_custom_lines_merged_sorted(self):
        self.assertEqual(merge_with_default_lines("kills", [30.5, 26.5]), [26.5, 27.5, 30.5])

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
