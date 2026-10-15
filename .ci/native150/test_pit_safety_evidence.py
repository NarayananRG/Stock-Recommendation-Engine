from pathlib import Path
from datetime import datetime, timezone
import json
import os
import sys
import unittest

ROOT=Path(os.environ["SRE_ENGINE_ROOT"])
sys.path.insert(0,str(ROOT))

from stock_app import fundamental_v3

class PitSafetyEvidenceRepairTests(unittest.TestCase):
    def setUp(self):
        self.api=(ROOT/"modern_ui"/"api.py").read_text(encoding="utf-8")
        self.fund=(ROOT/"stock_app"/"fundamental_v3.py").read_text(encoding="utf-8")
        self.router=(ROOT/"stock_app"/"live_decision_v1.py").read_text(encoding="utf-8")
        self.supp=ROOT/"NextGen Research"/"results"/"pit_safety_supplement_v1"/"pit_safety_supplement.jsonl"
        self.rows=[json.loads(x) for x in self.supp.read_text(encoding="utf-8").splitlines() if x.strip()]

    def test_release_identity_and_cache_revision(self):
        self.assertIn('APP_VERSION = "0.14.9-pit-safety-evidence-repair"',self.api)
        self.assertIn("cached_version == APP_VERSION",self.api)

    def test_supplement_is_official_display_validated_and_corporate_only(self):
        self.assertGreaterEqual(len(self.rows),50)
        for row in self.rows:
            self.assertEqual(row["source_host"],"nsearchives.nseindia.com")
            self.assertEqual(row["domain"],"IND_AS_CORPORATE")
            self.assertEqual(row["concept"],"DebtEquityRatio")
            self.assertTrue(row["display_validated"])
            self.assertTrue(row["point_in_time_safe"])
        symbols={x["symbol"] for x in self.rows}
        for symbol in ("GODREJCP","HINDZINC","OFSS"):
            self.assertIn(symbol,symbols)
        for symbol in ("BDL","BSE"):
            self.assertNotIn(symbol,symbols)

    def test_supplement_merges_pit_safely_without_zero_fill(self):
        history=[{
            "symbol":"GODREJCP","quarter_end":"2026-06-30",
            "reporting_basis":"CONSOLIDATED",
            "availability_ts":"2026-07-31T12:00:00+05:30",
            "domain":"IND_AS_CORPORATE",
        }]
        merged,meta=fundamental_v3._merge_pit_safety_supplement(
            ROOT,"GODREJCP",datetime(2026,10,15,23,59,tzinfo=timezone.utc),"CONSOLIDATED",history
        )
        self.assertTrue(meta["applied"])
        self.assertAlmostEqual(float(merged[-1]["DEBT_EQUITY_RATIO"]),0.35,places=6)
        self.assertEqual(merged[-1]["DEBT_EQUITY_RATIO__concept"],"DebtEquityRatio")

        missing=[{
            "symbol":"BDL","quarter_end":"2026-06-30",
            "reporting_basis":"STANDALONE",
            "availability_ts":"2026-07-31T12:00:00+05:30",
            "domain":"IND_AS_CORPORATE",
        }]
        merged2,meta2=fundamental_v3._merge_pit_safety_supplement(
            ROOT,"BDL",datetime(2026,10,15,23,59,tzinfo=timezone.utc),"STANDALONE",missing
        )
        self.assertFalse(meta2["applied"])
        self.assertNotIn("DEBT_EQUITY_RATIO",merged2[-1])

    def test_future_supplement_cannot_leak(self):
        history=[{
            "symbol":"GODREJCP","quarter_end":"2026-06-30",
            "reporting_basis":"CONSOLIDATED",
            "availability_ts":"2026-07-31T12:00:00+05:30",
            "domain":"IND_AS_CORPORATE",
        }]
        merged,meta=fundamental_v3._merge_pit_safety_supplement(
            ROOT,"GODREJCP",datetime(2026,6,15,23,59,tzinfo=timezone.utc),"CONSOLIDATED",history
        )
        self.assertFalse(meta["applied"])
        self.assertNotIn("DEBT_EQUITY_RATIO",merged[-1])

    def test_financial_domains_remain_fail_closed(self):
        self.assertIn('"safety_ready": False',self.fund)
        self.assertIn('"POLICY_NOT_VALIDATED"',self.fund)
        self.assertIn('"financial_domain_metrics_promoted": false',(ROOT/"phase5"/"pit_safety_evidence_policy_0149.json").read_text(encoding="utf-8"))

    def test_router_thresholds_are_not_modified_by_patch(self):
        for token in (
            "debt > 2.5",
            "debt > 1.5",
            "atr <= 6",
            "drawdown is not None and drawdown <= -15",
            "regime in (\"BULL\", \"MIXED\")",
        ):
            self.assertIn(token,self.router)

if __name__=="__main__":
    unittest.main()
