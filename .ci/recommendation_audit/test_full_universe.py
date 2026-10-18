import importlib.util
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location("full_universe",Path(__file__).with_name("full_universe.py"))
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class FullUniverseTests(unittest.TestCase):
    def base(self):
        return {"run":{"run_id":"r1","market_session":"2026-10-16","model_version":"frozen"},"candidates":[
            {"symbol":"AAA.NS","live_decision":{"final_action":"WATCH","executable":False,"market_session":"2026-10-16","fundamental_data_quality":"UNAVAILABLE","reason_codes":["MISSING_FILING","TECHNICAL_WEAK"]}},
            {"symbol":"BBB.NS","live_decision":{"final_action":"MOMENTUM BUY","executable":True,"market_session":"2026-10-16","fundamental_data_quality":"AVAILABLE","reason_codes":[]}}]}
    def test_counts_and_missing_quality_distinction(self):
        r=m.audit(self.base())
        self.assertEqual(r["universe_count"],2)
        self.assertEqual(r["action_and_execution_counts"]["WATCH"],1)
        self.assertEqual(r["action_and_execution_counts"]["EXECUTABLE"],1)
        self.assertEqual(r["fundamental_evidence_quality"]["UNAVAILABLE"],1)
        self.assertEqual(r["reason_code_counts"]["MISSING_FILING"],1)
        self.assertTrue(r["session_consistency_pass"])
        self.assertFalse(r["promotion_authorized"])
    def test_session_mismatch_is_not_hidden(self):
        p=self.base();p["candidates"][0]["live_decision"]["market_session"]="2026-10-15"
        self.assertFalse(m.audit(p)["session_consistency_pass"])
    def test_duplicate_symbol_fails_closed(self):
        p=self.base();p["candidates"][1]["symbol"]="AAA"
        with self.assertRaises(ValueError):m.audit(p)
    def test_missing_snapshot_fails_closed(self):
        with self.assertRaises(ValueError):m.audit({"run":{},"candidates":[]})
    def test_missing_evidence_is_not_assumed_negative(self):
        p=self.base();p["candidates"][0]["live_decision"]["reason_codes"]=[]
        r=m.audit(p)
        self.assertEqual(r["fundamental_evidence_quality"]["UNAVAILABLE"],1)
        self.assertNotIn("MISSING_FILING",r["reason_code_counts"])

if __name__=="__main__":unittest.main()
