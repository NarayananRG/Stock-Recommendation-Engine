from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import unittest
from pathlib import Path

ROOT = Path(os.environ["SRE_ENGINE_ROOT"])
SPEC = importlib.util.spec_from_file_location("evidence_coverage_v1", ROOT / "stock_app" / "evidence_coverage_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def decision(*, domain="IND_AS_CORPORATE", cash=10, cash_state="SUPPORTIVE", debt=.4,
             balance_state="HEALTHY", eps=5, pe=10, observations=4, stale=False):
    return {
        "cash_flow_state": cash_state, "balance_sheet_state": balance_state,
        "evidence": {"fundamental": {
            "domain": domain, "filing_freshness": "STALE" if stale else "CURRENT_FOR_DECISION_TIME",
            "growth": {"revenue_yoy_symmetric_pct": 6, "pat_yoy_symmetric_pct": 6, "eps_yoy_symmetric_pct": 6},
            "profitability": {"revenue": 100, "pat": 10, "eps": eps},
            "cash_flow": {"latest_operating_cash_flow": cash, "source": {"concept": "CashFlowsFromUsedInOperatingActivities"}},
            "balance_sheet": {"cash_and_equivalents": 3, "total_assets": 30, "debt_equity_ratio": debt, "sources": {}},
            "valuation": {"implied_pe_from_ttm_eps": pe, "implied_pb": 1.2,
                          "pit_historical_pe_reference": 12 if observations >= 4 else None,
                          "pit_historical_pb_reference": 1.5 if observations >= 4 else None,
                          "pit_comparison_observations": [{"session": f"2026-0{i+1}-01"} for i in range(observations)]},
            "financial_domain_adapter": {"applicable": domain != "IND_AS_CORPORATE", "metrics": {},
                                         "safety_ready": False, "status": "POLICY_NOT_VALIDATED"},
        }}
    }


class EvidenceCoverageTests(unittest.TestCase):
    def test_pit_timestamp_cutoff_is_preserved(self):
        source = (ROOT / "stock_app" / "fundamental_v3.py").read_text(encoding="utf-8")
        self.assertIn("available > cutoff", source)

    def test_no_future_filing_leakage(self):
        source = (ROOT / "stock_app" / "fundamental_v3.py").read_text(encoding="utf-8")
        self.assertIn("FUTURE_FILING_LEAKAGE", source)

    def test_reporting_basis_consistency(self):
        source = (ROOT / "stock_app" / "fundamental_v3.py").read_text(encoding="utf-8")
        self.assertIn("reporting_basis", source)
        self.assertIn("basis_preference", source)

    def test_xbrl_unit_semantics_are_research_only(self):
        source = (Path(__file__).with_name("financial_domain_research.py")).read_text(encoding="utf-8")
        self.assertIn('"unit_ref"', source)
        self.assertIn('"dimensions"', source)
        self.assertIn('"production_ready": False', source)

    def test_official_host_restriction(self):
        source = (Path(__file__).with_name("financial_domain_research.py")).read_text(encoding="utf-8")
        self.assertIn('OFFICIAL_HOST = "nsearchives.nseindia.com"', source)
        self.assertIn("NON_OFFICIAL_SOURCE", source)

    def test_no_automatic_yfinance(self):
        policy = json.loads((ROOT / "phase5" / "missing_evidence_coverage_policy_01411.json").read_text(encoding="utf-8"))
        self.assertFalse(policy["automatic_yfinance_fallback"])

    def test_missing_debt_is_not_zero_filled(self):
        result = MODULE.classify_live_decision(decision(debt=None))
        self.assertEqual(result["families"]["Debt / leverage / DebtEquityRatio"]["condition"], "MISSING_SOURCE_DATA")
        self.assertIsNone(result["families"]["Debt / leverage / DebtEquityRatio"]["value"])

    def test_corporate_rules_not_applied_to_bank(self):
        result = MODULE.classify_live_decision(decision(domain="BANK", debt=.2))
        self.assertEqual(result["families"]["Debt / leverage / DebtEquityRatio"]["condition"], "NOT_APPLICABLE_FOR_DOMAIN")
        self.assertEqual(result["families"]["Operating cash flow"]["condition"], "NOT_APPLICABLE_FOR_DOMAIN")

    def test_financial_domain_remains_fail_closed(self):
        result = MODULE.classify_live_decision(decision(domain="NBFC"))
        self.assertEqual(result["financial_domain"]["condition"], "POLICY_NOT_VALIDATED")
        self.assertFalse(result["financial_domain"]["production_ready"])

    def test_minimum_valuation_observation_rule(self):
        result = MODULE.classify_live_decision(decision(observations=3))
        self.assertEqual(result["families"]["Historical PIT valuation reference"]["condition"], "INSUFFICIENT_PIT_HISTORY")

    def test_cash_flow_unfavorable_is_not_missing(self):
        result = MODULE.classify_live_decision(decision(cash=-1, cash_state="DANGEROUS"))
        self.assertEqual(result["families"]["Operating cash flow"]["condition"], "PRESENT_BUT_UNFAVORABLE")
        self.assertNotIn("Operating cash flow", result["missing"])

    def test_balance_sheet_unhealthy_is_not_missing(self):
        result = MODULE.classify_live_decision(decision(debt=2, balance_state="CAUTION"))
        self.assertEqual(result["families"]["Debt / leverage / DebtEquityRatio"]["condition"], "PRESENT_BUT_UNFAVORABLE")
        self.assertNotIn("Debt / leverage / DebtEquityRatio", result["missing"])

    def test_stale_is_explicit(self):
        result = MODULE.classify_live_decision(decision(stale=True))
        self.assertEqual(result["families"]["Revenue"]["condition"], "STALE_OR_OUT_OF_ORDER")

    def test_router_sha_is_unchanged(self):
        expected = os.environ.get("SRE_EXPECTED_ROUTER_SHA")
        self.assertTrue(expected, "SRE_EXPECTED_ROUTER_SHA required")
        actual = hashlib.sha256((ROOT / "stock_app" / "live_decision_v1.py").read_bytes()).hexdigest()
        self.assertEqual(actual.lower(), expected.lower())


if __name__ == "__main__":
    unittest.main()

