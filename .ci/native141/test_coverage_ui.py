import csv
import inspect
import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(os.environ["SRE_ENGINE_ROOT"])
sys.path.insert(0, str(ROOT))

from modern_ui import api as api_module
from stock_app import fundamental_v3
from stock_app.live_decision_v1 import route


FEATURES = tuple(fundamental_v3.CORE_FEATURES) + tuple(fundamental_v3.EXTENDED_FEATURES)


def panel_row(symbol, quarter, available, domain="INDUSTRIAL", missing=()):
    values = {
        "REVENUE": 1000, "PAT": 150, "PBT": 190, "EPS": 10,
        "OPERATING_CASH_FLOW": 180, "CASH_AND_EQUIVALENTS": 250,
        "TOTAL_ASSETS": 2000, "FINANCE_COST": 20, "DEBT_EQUITY_RATIO": .5,
        "PB_RATIO": 2.0,
    }
    row = {"symbol": symbol, "quarter_end": quarter, "reporting_basis": "CONSOLIDATED",
           "submission_type": "ORIGINAL", "availability_ts": available, "domain": domain}
    for feature in FEATURES:
        value = None if feature in missing else values.get(feature)
        row[f"{feature}__status"] = "SELECTED" if value is not None else "NOT_MAPPED"
        row[f"{feature}__concept"] = feature if value is not None else ""
        row[f"{feature}__value"] = "" if value is None else value
    return row


def write_panel(root, rows):
    path = root / "NextGen Research/results/fundamental_v2_phase2a4_feature_panel/canonical_feature_panel.csv"
    path.parent.mkdir(parents=True)
    fields = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def technical():
    return {"status": "READY", "trend": {"close": 100, "ema50": 110, "ema50_slope_5d_pct": -2},
            "momentum": {"roc20_pct": -3, "macd_hist": -1, "rsi14": 35},
            "relative_strength": {"rs20_vs_nifty": -2}, "volume_flow": {"cmf20": .1},
            "multi_timeframe": {"weekly_trend_confirmed": False}, "volatility": {"atr_pct": 3},
            "market_context": {"nifty_regime": "MIXED"}}


class FundamentalCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT.parent)
        self.root = Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def rows(self, symbol="TEST", domain="INDUSTRIAL"):
        dates = [("2025-03-31", "2025-04-20"), ("2025-06-30", "2025-07-20"),
                 ("2025-09-30", "2025-10-20"), ("2025-12-31", "2026-01-20"),
                 ("2026-03-31", "2026-04-20"), ("2026-06-30", "2026-07-20")]
        return [panel_row(symbol, q, a, domain) for q, a in dates]

    def test_nonfinancial_full_and_partial_coverage(self):
        rows = self.rows()
        rows[-1]["OPERATING_CASH_FLOW__status"] = "MISSING_EXPECTED_PERIOD"
        rows[-1]["OPERATING_CASH_FLOW__value"] = ""
        write_panel(self.root, rows)
        result = fundamental_v3.analyze(self.root, "TEST", decision_timestamp="2026-10-14", latest_price=100)
        self.assertTrue(result["point_in_time_safe"])
        self.assertEqual(result["cash_flow"]["latest_operating_cash_flow"], 180)
        self.assertEqual(result["cash_flow"]["source"]["quarter_end"], "2026-03-31")
        self.assertEqual(result["feature_coverage"]["Operating Cash Flow"]["status"], "AVAILABLE")
        self.assertEqual(result["feature_coverage"]["ROIC"]["status"], "MISSING")
        self.assertNotEqual(result["balance_sheet"]["debt_equity_ratio"], 0)

    def test_missing_balance_sheet_stays_missing(self):
        rows = [panel_row("TEST", "2026-06-30", "2026-07-20", missing=("DEBT_EQUITY_RATIO",))]
        write_panel(self.root, rows)
        result = fundamental_v3.analyze(self.root, "TEST", decision_timestamp="2026-10-14", latest_price=100)
        self.assertIsNone(result["balance_sheet"]["debt_equity_ratio"])
        self.assertEqual(result["feature_coverage"]["Debt/Leverage"]["status"], "MISSING")

    def test_stale_and_future_filing_rejection(self):
        rows = [panel_row("TEST", "2025-03-31", "2025-04-20"),
                panel_row("TEST", "2026-12-31", "2026-12-31")]
        write_panel(self.root, rows)
        result = fundamental_v3.analyze(self.root, "TEST", decision_timestamp="2026-10-14", latest_price=100)
        self.assertEqual(result["quarter_end"], "2025-03-31")
        self.assertEqual(result["filing_freshness"], "STALE")
        self.assertIsNone(result["cash_flow"]["latest_operating_cash_flow"])

    def test_financial_adapter_is_explicit_and_does_not_use_industrial_rules(self):
        write_panel(self.root, self.rows("BANK", "BANK"))
        result = fundamental_v3.analyze(self.root, "BANK", decision_timestamp="2026-10-14", latest_price=100)
        adapter = result["financial_domain_adapter"]
        self.assertEqual(adapter["status"], "INSUFFICIENT_COVERAGE")
        self.assertFalse(adapter["industrial_cashflow_or_leverage_used"])
        self.assertIn("Asset quality", adapter["missing_required_groups"])
        decision = route("BANK", "2026-10-14", technical(), result,
                         price_context={"prior_support": 95, "drawdown_from_126_high_pct": -25}, official_current=True)
        self.assertEqual(decision["final_action"], "WATCH - RECOVERY")
        self.assertIn("FINANCIAL_DOMAIN_PIT_SAFETY_INCOMPLETE", decision["reason_codes"])
        self.assertIn("Asset quality", decision["missing_evidence"])

    def test_pit_relative_valuation_is_never_fabricated(self):
        write_panel(self.root, self.rows())
        result = fundamental_v3.analyze(self.root, "TEST", decision_timestamp="2026-10-14", latest_price=100)
        self.assertNotIn("pit_historical_pe_reference", result["valuation"])
        self.assertEqual(result["feature_coverage"]["PIT relative valuation reference"]["status"], "MISSING")

    def test_desired_return_5_8_10_20_does_not_change_classification(self):
        fundamental = {"available": True, "point_in_time_safe": True, "filing_freshness": "CURRENT_FOR_DECISION_TIME",
                       "sector_profile": "GENERAL_CORPORATE",
                       "growth": {"revenue_yoy_symmetric_pct": 5, "pat_yoy_symmetric_pct": 8, "eps_yoy_symmetric_pct": 8},
                       "profitability": {"pat_margin_pct": 15},
                       "cash_flow": {"latest_operating_cash_flow": 100, "ocf_yoy_symmetric_pct": 5},
                       "balance_sheet": {"debt_equity_ratio": .5},
                       "risk_event": {"available": True, "event_profile": "NO_DIRECTIONAL_EVIDENCE"},
                       "valuation": {"implied_pe_from_ttm_eps": 12, "pit_comparison_available": True,
                                     "pit_historical_pe_reference": 18}}
        actions = []
        for target in (5, 8, 10, 20):
            decision = route("TEST", "2026-10-14", technical(), fundamental,
                             price_context={"prior_support": 95, "drawdown_from_126_high_pct": -25},
                             official_current=True, legacy={"target_return": target})
            actions.append(decision["final_action"])
            self.assertFalse(decision["target_used_in_score"])
        self.assertEqual(len(set(actions)), 1)


class ApiAndUiTests(unittest.TestCase):
    def test_api_returns_all_200_and_coverage_aggregates_same_rows(self):
        original = api_module.ModernAppContext.__init__
        api_module.ModernAppContext.__init__ = lambda self, *a, **k: None
        try:
            app = api_module.create_app(ROOT, ROOT / "_test_appdata")
        finally:
            api_module.ModernAppContext.__init__ = original
        endpoint = next(r.endpoint for r in app.routes if getattr(r, "path", "") == "/api/opportunities")
        ctx = inspect.getclosurevars(endpoint).nonlocals["ctx"]
        rows = [{"symbol": f"S{i:03}", "live_decision": {"final_action": "WATCH - RECOVERY",
                 "reason_codes": ["PIT_RELATIVE_VALUATION_UNAVAILABLE"], "evidence": {"fundamental": {"available": True,
                 "feature_coverage": {"PE": {"status": "AVAILABLE"}}, "financial_domain_adapter": {"applicable": False}}},
                 "cash_flow_state": "UNAVAILABLE", "balance_sheet_state": "UNAVAILABLE"}} for i in range(200)]
        ctx.latest_prediction_rows = lambda limit=200: rows[:limit]
        ctx.ui_run_input = lambda: {"run_id": "RUN", "market_session": "2026-10-14"}
        ctx.active_target_state = lambda: {"explicit": False}
        ctx.active_prediction_run = lambda: {"run": {"lane_counts": {"watch": 200}}}
        response = endpoint(limit=200)
        self.assertEqual(response["count"], 200)
        coverage_endpoint = next(r.endpoint for r in app.routes if getattr(r, "path", "") == "/api/live/coverage")
        coverage = coverage_endpoint()
        self.assertEqual(coverage["universe_size"], 200)
        self.assertEqual(coverage["feature_coverage_counts"]["PE"]["AVAILABLE"], 200)

    def test_ui_full_dataset_table_filters_pagination_search_sort_and_details(self):
        js = (ROOT / "modern_ui/frontend/app.js").read_text(encoding="utf-8")
        html = (ROOT / "modern_ui/frontend/index.html").read_text(encoding="utf-8")
        self.assertIn("/api/opportunities?limit=200", js)
        self.assertIn("state.opportunityItems=d.items||[]", js)
        self.assertIn("state.page!=='opportunities'&&!state.opportunityItems.length", js)
        self.assertNotIn("const opps=data.opportunities||[]; state.opportunityItems=opps", js)
        self.assertNotIn("slice(0,8)", js)
        self.assertNotIn("limit=8", js)
        for token in ("opportunityCounts", "filteredOpportunityRows", "oppSearch", "oppSort", "oppPageSize", "openOpportunityDetails"):
            self.assertIn(token, js)
        for label in ("Momentum BUY", "Recovery BUY", "Both", "Watch", "Avoid", "No Opportunity", "Executable"):
            self.assertIn(label, html)
        for size in (">25<", ">50<", ">100<", ">All<"):
            self.assertIn(size, html)
        render = js[js.index("function renderOpportunityTable"):js.index("function openOpportunityDetails")]
        self.assertNotIn("x.thesis", render)
        self.assertIn("opportunity-row", render)

    def test_capital_plan_uses_live_authority_wording(self):
        api_text = (ROOT / "modern_ui/api.py").read_text(encoding="utf-8")
        self.assertIn("No executable LIVE_DECISION_V1 BUY opportunities", api_text)
        self.assertNotIn("no executable combined-decision rows", api_text)
        self.assertIn('summary["top_blockers"]', api_text)


if __name__ == "__main__":
    unittest.main()
