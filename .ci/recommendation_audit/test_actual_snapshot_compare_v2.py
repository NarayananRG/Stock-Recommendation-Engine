from __future__ import annotations
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

PATH=Path(__file__).with_name("actual_snapshot_compare_v2.py")
SPEC=importlib.util.spec_from_file_location("snapshot_compare",PATH)
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)

class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.a=Path(self.tmp.name)/"a.json"
        self.b=Path(self.tmp.name)/"b.json"
    def write(self,path,action="WATCH",executable=False,session="2026-10-16",symbol="AAA.NS",run_id="r1"):
        obj={"run":{"market_session":session,"run_id":run_id},"candidates":[{"symbol":symbol,"live_decision":{"market_session":session,"final_action":action,"executable":executable}}]}
        path.write_text(json.dumps(obj),encoding="utf-8")
    def test_same_universe_action_change(self):
        self.write(self.a)
        self.write(self.b,"RECOVERY BUY",True,run_id="r2")
        result=m.compare(self.a,self.b,1)
        self.assertEqual(result["changed_decision_count"],1)
        self.assertEqual(result["after_executable_buys"],1)
        self.assertFalse(result["historical_forward_outcomes_validated"])
        self.assertFalse(result["production_changes"])
        self.assertEqual(len(result["before_sha256"]),64)
    def test_identical_snapshots_still_do_not_claim_performance(self):
        self.write(self.a);self.write(self.b)
        result=m.compare(self.a,self.b,1)
        self.assertEqual(result["changed_decision_count"],0)
        self.assertFalse(result["investment_performance_claim_allowed"])
    def test_cross_session_rejected(self):
        self.write(self.a);self.write(self.b,session="2026-10-17")
        with self.assertRaisesRegex(ValueError,"DIFFERENT_MARKET_SESSIONS"):m.compare(self.a,self.b,1)
    def test_missing_symbol_rejected(self):
        self.write(self.a);self.write(self.b,symbol="BBB")
        with self.assertRaisesRegex(ValueError,"UNIVERSE_MISMATCH"):m.compare(self.a,self.b,1)
    def test_executable_non_buy_rejected(self):
        self.write(self.a,executable=True);self.write(self.b)
        with self.assertRaisesRegex(ValueError,"EXECUTABLE_NON_BUY"):m.compare(self.a,self.b,1)
    def test_invalid_flag_rejected(self):
        self.write(self.a);self.write(self.b)
        d=json.loads(self.a.read_text());d["candidates"][0]["live_decision"]["executable"]="False"
        self.a.write_text(json.dumps(d))
        with self.assertRaisesRegex(ValueError,"INVALID_EXECUTION_FLAG"):m.compare(self.a,self.b,1)
    def test_expected_count_rejected(self):
        self.write(self.a);self.write(self.b)
        with self.assertRaisesRegex(ValueError,"UNEXPECTED_UNIVERSE_COUNT"):m.compare(self.a,self.b)
    def test_duplicate_normalized_symbol_rejected(self):
        self.write(self.a);self.write(self.b)
        d=json.loads(self.a.read_text());extra=json.loads(json.dumps(d["candidates"][0]))
        extra["symbol"]="AAA";d["candidates"].append(extra);self.a.write_text(json.dumps(d))
        with self.assertRaisesRegex(ValueError,"DUPLICATE_SYMBOL"):m.compare(self.a,self.b,2)
if __name__=="__main__":unittest.main()
