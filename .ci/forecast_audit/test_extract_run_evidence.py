import importlib.util,json,tempfile,unittest
from pathlib import Path
p=Path(__file__).with_name("extract_run_evidence.py")
s=importlib.util.spec_from_file_location("extract_run_evidence",p)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

class EvidenceTests(unittest.TestCase):
    def sample(self):
        return {"run":{"run_id":"test-only","market_session":"2026-10-16","horizon_sessions":20,
                       "production_authority":"LIVE_DECISION_V1"},
            "candidates":[
                {"symbol":"GODREJCP","expected_return":-0.39,"latest_close":100,
                 "live_decision":{"final_action":"RECOVERY BUY","executable":True,"market_session":"2026-10-16",
                                  "evidence":{"fundamental":{"secret":"do not export"}}}},
                {"symbol":"HINDZINC.NS","expected_return":2.3,"latest_close":500,
                 "live_decision":{"final_action":"WATCH - RECOVERY","executable":False,"market_session":"2026-10-16"}},
                {"symbol":"OTHER","portfolio_account":"private","live_decision":{}}]}
    def test_selects_only_target_symbols(self):
        result=m.extract(self.sample())
        self.assertEqual(set(result["symbol_records"]),set(m.SYMBOLS))
        self.assertEqual(result["symbol_records"]["GODREJCP"]["expected_return"],-0.39)
        self.assertEqual(result["symbol_records"]["HINDZINC"]["expected_return"],2.3)
    def test_no_private_raw_evidence(self):
        text=json.dumps(m.extract(self.sample()))
        self.assertNotIn("secret",text)
        self.assertNotIn("portfolio_account",text)
        self.assertNotIn("OTHER",text)
    def test_not_calibrated_or_promoted(self):
        r=m.extract(self.sample())
        self.assertFalse(r["ready_to_promote_forecast_as_buy_gate"])
        self.assertFalse(r["symbol_records"]["GODREJCP"]["forecast_horizon_verified"])
    def test_missing_record_is_not_fabricated(self):
        p=self.sample();p["candidates"]=p["candidates"][:1]
        self.assertFalse(m.extract(p)["symbol_records"]["HINDZINC"]["found"])
    def test_stale_session_is_detected(self):
        p=self.sample();p["candidates"][0]["live_decision"]["market_session"]="2026-10-15"
        self.assertIn("GODREJCP_LIVE_DECISION_SESSION_MISMATCH",m.extract(p)["limitations"])
    def test_duplicate_symbol_fails(self):
        p=self.sample();p["candidates"].append(dict(p["candidates"][0]))
        with self.assertRaises(ValueError):m.extract(p)
    def test_nonfinite_returns_sanitized(self):
        p=self.sample();p["candidates"][0]["expected_return"]=float("nan")
        self.assertIsNone(m.extract(p)["symbol_records"]["GODREJCP"]["expected_return"])
    def test_missing_run_fails(self):
        with self.assertRaises(ValueError):m.extract({"candidates":[]})
if __name__=="__main__":unittest.main()
