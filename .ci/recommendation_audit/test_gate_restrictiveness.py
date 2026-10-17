import importlib.util
import unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location("gate",Path(__file__).with_name("gate_restrictiveness.py"))
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
class AuditTests(unittest.TestCase):
    def payload(self):
        return {"run":{"run_id":"r","market_session":"2026-10-16"},"candidates":[
            {"symbol":"AAA.NS","live_decision":{"market_session":"2026-10-16","final_action":"WATCH","fundamental_data_quality":"AVAILABLE","reason_codes":["A_OR_UNAVAILABLE","B","B"]}},
            {"symbol":"BBB","live_decision":{"market_session":"2026-10-15","final_action":"BUY","executable":True,"reason_codes":["B"]}}]}
    def test_reason_overlap_and_sessions(self):
        result=gate.audit(self.payload())
        self.assertEqual(result["reason_counts"]["B"],2)
        self.assertEqual(result["overlapping_reason_pairs"][0]["count"],1)
        self.assertEqual(result["session_mismatches"],1)
        self.assertEqual(result["mixed_reason_codes"],["A_OR_UNAVAILABLE"])
        self.assertFalse(result["promotion_authorized"])
    def test_duplicate_symbol_fails(self):
        p=self.payload();p["candidates"][1]["symbol"]="AAA"
        with self.assertRaises(ValueError):gate.audit(p)
    def test_missing_decision_fails(self):
        p=self.payload();del p["candidates"][0]["live_decision"]
        with self.assertRaises(ValueError):gate.audit(p)
    def test_empty_reasons_not_implicitly_negative(self):
        p=self.payload();p["candidates"][0]["live_decision"]["reason_codes"]=[]
        self.assertNotIn("A_OR_UNAVAILABLE",gate.audit(p)["reason_counts"])
if __name__=="__main__":unittest.main()
