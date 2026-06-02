"""Tests for competition-phase annotation (EWC qualify vs main, etc.)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app_core.competition_phases_core import (
    apply_phase_overrides,
    load_phase_rules,
    apply_competition_phases,
)


def _df():
    return pd.DataFrame([
        {"league": "EWC", "year": 2026, "date": "2026-04-20", "split": "", "playoffs": 0},
        {"league": "EWC", "year": 2026, "date": "2026-05-20", "split": "", "playoffs": 0},
        {"league": "LPL", "year": 2026, "date": "2026-05-20", "split": "Split 2", "playoffs": 0},
    ])


class TestApplyPhaseOverrides(unittest.TestCase):

    def test_noop_when_no_rules(self):
        df = _df()
        out = apply_phase_overrides(df, [])
        pd.testing.assert_frame_equal(out, df)

    def test_splits_ewc_by_date(self):
        rules = [
            {"league": "EWC", "year": 2026, "date_from": "2026-04-14", "date_to": "2026-05-01", "split": "Qualify"},
            {"league": "EWC", "year": 2026, "date_from": "2026-05-02", "date_to": "2026-05-26", "split": "Main"},
        ]
        out = apply_phase_overrides(_df(), rules)
        ewc = out[out["league"] == "EWC"].sort_values("date")
        self.assertEqual(list(ewc["split"]), ["Qualify", "Main"])
        # LPL untouched.
        self.assertEqual(out[out["league"] == "LPL"]["split"].iloc[0], "Split 2")

    def test_year_filter_respected(self):
        rules = [{"league": "EWC", "year": 2025, "date_from": "2026-04-14",
                  "date_to": "2026-05-26", "split": "X"}]
        out = apply_phase_overrides(_df(), rules)
        # Year 2025 rule must not touch 2026 rows.
        self.assertTrue((out[out["league"] == "EWC"]["split"] == "").all())

    def test_playoffs_override(self):
        rules = [{"league": "EWC", "date_from": "2026-05-02", "date_to": "2026-05-26",
                  "split": "Main", "playoffs": True}]
        out = apply_phase_overrides(_df(), rules)
        main = out[(out["league"] == "EWC") & (out["split"] == "Main")]
        self.assertTrue(bool(main["playoffs"].iloc[0]))


class TestLoadPhaseRules(unittest.TestCase):

    def test_missing_file_returns_empty(self):
        self.assertEqual(load_phase_rules("/nonexistent/path.json"), [])

    def test_incomplete_rules_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "phases.json"
            p.write_text(json.dumps({"rules": [
                {"league": "EWC"},  # incomplete → skip
                {"league": "EWC", "date_from": "2026-04-14", "date_to": "2026-05-01", "split": "Qualify"},
            ]}), encoding="utf-8")
            rules = load_phase_rules(p)
            self.assertEqual(len(rules), 1)
            self.assertEqual(rules[0]["split"], "Qualify")

    def test_template_file_is_noop(self):
        # The shipped template must have empty rules (no surprise overrides).
        template = Path(__file__).resolve().parents[2] / "competition_phases.json"
        if template.exists():
            self.assertEqual(load_phase_rules(template), [])

    def test_apply_competition_phases_noop_missing(self):
        df = _df()
        out = apply_competition_phases(df, path="/nonexistent.json")
        pd.testing.assert_frame_equal(out, df)


if __name__ == "__main__":
    unittest.main()
