from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_complete_financial_coverage_v2.py"
SPEC = importlib.util.spec_from_file_location("coverage_v2", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class CoverageV2Tests(unittest.TestCase):
    def test_panel_statuses_are_fail_closed(self):
        self.assertEqual(MODULE.panel_class("SELECTED"), "AVAILABLE_VERIFIED")
        self.assertEqual(MODULE.panel_class("NOT_MAPPED_FOR_DOMAIN"), "AVAILABLE_BUT_NOT_MAPPED")
        self.assertEqual(MODULE.panel_class("DOCUMENT_PARSE_FAILURE"), "SOURCE_PARSE_FAILURE")
        self.assertEqual(MODULE.panel_class("NO_ALIGNED_CONTEXT"), "PERIOD_MISMATCH")
        self.assertEqual(MODULE.panel_class(None), "MISSING_IN_SOURCE")

    def test_boolean_is_not_usable_financial_evidence(self):
        self.assertFalse(MODULE.usable(True))
        self.assertFalse(MODULE.usable(False))
        self.assertFalse(MODULE.usable(None))
        self.assertTrue(MODULE.usable(0))

    def test_metric_contract_is_complete_and_unique(self):
        metrics = set(MODULE.RAW_METRICS) | set(MODULE.DERIVED_PATHS) | set(MODULE.EXTENDED_METRICS)
        self.assertEqual(len(metrics), 34)
        self.assertTrue(MODULE.INDUSTRIAL_ONLY <= metrics)
        self.assertTrue(set(MODULE.CONSUMERS) <= metrics)


if __name__ == "__main__":
    unittest.main()
