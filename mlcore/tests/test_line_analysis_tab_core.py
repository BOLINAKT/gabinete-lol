"""Tests for app_core/line_analysis_tab_core.py — pure stat helpers."""
import math
import unittest

import pandas as pd

from app_core.line_analysis_tab_core import _get_metric_col, _safe_pct


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


if __name__ == "__main__":
    unittest.main()
