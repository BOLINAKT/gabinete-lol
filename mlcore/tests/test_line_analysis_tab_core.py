"""Tests for app_core/line_analysis_tab_core.py — pure stat helpers."""
import math
import unittest

import pandas as pd

from app_core.line_analysis_tab_core import (
    _augment_with_total_columns,
    _get_metric_col,
    _safe_pct,
)


class TestSafePct(unittest.TestCase):

    def test_over_all_above_line(self):
        s = pd.Series([30.0, 35.0, 40.0])
        result = _safe_pct(s, 25.0, "Over")
        self.assertAlmostEqual(result, 100.0)

    def test_over_all_below_line(self):
        s = pd.Series([10.0, 12.0, 15.0])
        result = _safe_pct(s, 25.0, "Over")
        self.assertAlmostEqual(result, 0.0)

    def test_over_half_above_line(self):
        s = pd.Series([20.0, 30.0])
        result = _safe_pct(s, 25.0, "Over")
        self.assertAlmostEqual(result, 50.0)

    def test_under_all_below_line(self):
        s = pd.Series([10.0, 15.0, 20.0])
        result = _safe_pct(s, 25.0, "Under")
        self.assertAlmostEqual(result, 100.0)

    def test_under_all_above_line(self):
        s = pd.Series([30.0, 35.0])
        result = _safe_pct(s, 25.0, "Under")
        self.assertAlmostEqual(result, 0.0)

    def test_under_half_at_or_below_line(self):
        s = pd.Series([25.0, 30.0])
        result = _safe_pct(s, 25.0, "Under")
        self.assertAlmostEqual(result, 50.0)

    def test_empty_series_returns_nan(self):
        s = pd.Series([], dtype=float)
        result = _safe_pct(s, 25.0, "Over")
        self.assertTrue(math.isnan(result))

    def test_all_nan_returns_nan(self):
        s = pd.Series([float("nan"), float("nan")])
        result = _safe_pct(s, 25.0, "Over")
        self.assertTrue(math.isnan(result))

    def test_mixed_nan_ignored(self):
        s = pd.Series([float("nan"), 30.0, 20.0])
        result = _safe_pct(s, 25.0, "Over")
        self.assertAlmostEqual(result, 50.0)

    def test_string_series_coerced(self):
        s = pd.Series(["30.0", "20.0"])
        result = _safe_pct(s, 25.0, "Over")
        self.assertAlmostEqual(result, 50.0)

    def test_result_between_0_and_100(self):
        s = pd.Series([10.0, 20.0, 30.0, 40.0])
        result = _safe_pct(s, 25.0, "Over")
        self.assertGreaterEqual(result, 0.0)
        self.assertLessEqual(result, 100.0)


class TestGetMetricCol(unittest.TestCase):

    def test_kills_returns_col(self):
        result = _get_metric_col("Kills")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)

    def test_unknown_market_returns_none(self):
        result = _get_metric_col("NonexistentMarket")
        self.assertIsNone(result)

    def test_empty_market_returns_none(self):
        result = _get_metric_col("")
        self.assertIsNone(result)

    def test_tempo_returns_col(self):
        result = _get_metric_col("Tempo")
        self.assertIsNotNone(result)

    def test_torres_returns_col(self):
        result = _get_metric_col("Torres")
        self.assertIsNotNone(result)


class TestSafePctComplementarity(unittest.TestCase):
    """Over% e Under% devem somar 100 (partição sem gap/double-count) p/ linhas .5."""

    def test_over_under_sum_to_100(self):
        s = pd.Series([24, 27, 28, 31, 33])
        over = _safe_pct(s, 27.5, "Over")
        under = _safe_pct(s, 27.5, "Under")
        self.assertAlmostEqual(over + under, 100.0, places=6)


class TestAugmentTotalColumns(unittest.TestCase):

    def test_total_is_for_plus_against(self):
        df = pd.DataFrame({"kills_for": [10, 5], "kills_against": [8, 7]})
        out = _augment_with_total_columns(df)
        self.assertEqual(list(out["mv2_total_kills"]), [18.0, 12.0])

    def test_spread_is_for_minus_against(self):
        df = pd.DataFrame({"kills_for": [10, 5], "kills_against": [8, 7]})
        out = _augment_with_total_columns(df)
        self.assertEqual(list(out["mv2_spread_kills"]), [2.0, -2.0])

    def test_missing_columns_skipped(self):
        df = pd.DataFrame({"kills_for": [10]})  # sem kills_against
        out = _augment_with_total_columns(df)
        self.assertNotIn("mv2_total_kills", out.columns)

    def test_nan_treated_as_zero(self):
        df = pd.DataFrame({"towers_for": [11, None], "towers_against": [None, 9]})
        out = _augment_with_total_columns(df)
        self.assertEqual(list(out["mv2_total_towers"]), [11.0, 9.0])

    def test_empty_df_returned_as_is(self):
        df = pd.DataFrame()
        out = _augment_with_total_columns(df)
        self.assertTrue(out.empty)

    def test_does_not_mutate_input(self):
        df = pd.DataFrame({"kills_for": [10], "kills_against": [8]})
        _augment_with_total_columns(df)
        self.assertNotIn("mv2_total_kills", df.columns)  # original intacto


if __name__ == "__main__":
    unittest.main()
