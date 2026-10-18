import importlib.util, unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location("component",Path(__file__).with_name("component_diagnostics.py"))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class ComponentTests(unittest.TestCase):
    def example(self):
        return {"run":{"run_id":"r1","market_session":"2026-10-16"},"candidates":[
          {"symbol":"AAA","live_decision":{"final_action":"RECOVERY BUY","executable":True,"earnings_direction":"STABLE","business_health":"HEALTHY","fundamental_event_state":"UNAVAILABLE","cash_flow_state":"ADEQUATE","balance_sheet_state":"HEALTHY","valuation_state":"REASONABLE","fundamental_data_quality":"AVAILABLE","evidence":{"technical":{"status":"READY","trend":{"close":100,"ema50":110,"ema50_slope_5d_pct":-1},"momentum":{"roc20_pct":-5,"macd_hist":-1},"relative_strength":{"rs20_vs_nifty":-1},"volume_flow":{"cmf20":0.1},"multi_timeframe":{"weekly_trend_confirmed":False}}}}},
          {"symbol":"BBB","live_decision":{"final_action":"WATCH - RECOVERY","executable":False,"earnings_direction":"WEAKENING","business_health":"UNAVAILABLE","fundamental_event_state":"STABLE","fundamental_data_quality":"UNAVAILABLE","evidence":{"technical":{}}}}]}
    def test_distinguish_missing_from_unfavorable(self):
        a=m.audit(self.example())
        rows={(x["component"],x["status"]):x["count"] for x in a["components"]}
        self.assertEqual(rows["business_health","MISSING_OR_STALE"],1)
        self.assertEqual(rows["earnings_direction","UNFAVORABLE"],1)
        self.assertEqual(rows["fundamental_event_state","MISSING_OR_STALE"],1)
        self.assertEqual(rows["price_above_ema50","UNFAVORABLE"],1)
        self.assertFalse(a["production_changed"])
    def test_preserves_original(self):
        p=self.example();import copy
        before=copy.deepcopy(p);m.audit(p);self.assertEqual(before,p)
    def test_duplicates_rejected(self):
        p=self.example();p["candidates"][1]["symbol"]="AAA.NS"
        with self.assertRaises(ValueError):m.audit(p)
    def test_missing_metadata_rejected(self):
        with self.assertRaises(ValueError):m.audit({"run":{},"candidates":[]})
if __name__=="__main__":unittest.main()
