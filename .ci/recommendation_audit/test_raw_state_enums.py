import importlib.util
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location("raw",Path(__file__).with_name("raw_state_enums.py"))
raw=importlib.util.module_from_spec(spec)
spec.loader.exec_module(raw)

class RawStateTests(unittest.TestCase):
    def example(self):
        return {"run":{"run_id":"run1","market_session":"2026-10-16"},"candidates":[
            {"symbol":"AAA","live_decision":{"business_health":"MIXED","fundamental_event_state":"MIXED","financial_domain":False,"evidence":{"fundamental":{"point_in_time_safe":True,"risk_event":{"available":True,"event_profile":"MIXED_DIRECTIONAL"},"balance_sheet":{"debt_equity_ratio":0.5}}}}},
            {"symbol":"BBB.NS","live_decision":{"business_health":"UNAVAILABLE","financial_domain":True,"evidence":{"fundamental":{"risk_event":{"available":False}}}}}]}
    def test_counts(self):
        out=raw.audit(self.example())
        self.assertEqual(out["stocks"],2)
        self.assertIn({"component":"business_health","value":"MIXED","count":1},out["states"])
        self.assertIn({"component":"event_profile","value":"MIXED_DIRECTIONAL","count":1},out["evidence_presence"])
        self.assertFalse(out["promotion_authorized"])
    def test_duplicate_normalized_symbol_rejected(self):
        p=self.example();p["candidates"][1]["symbol"]="AAA.NS"
        with self.assertRaises(ValueError):raw.audit(p)
    def test_missing_run_rejected(self):
        with self.assertRaises(ValueError):raw.audit({"run":{},"candidates":[]})
    def test_does_not_mutate(self):
        import copy
        p=self.example();c=copy.deepcopy(p);raw.audit(p);self.assertEqual(p,c)

if __name__=="__main__":unittest.main()
