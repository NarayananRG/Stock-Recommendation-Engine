import importlib.util,unittest
from pathlib import Path
p=Path(__file__).with_name("forecast_conflict_diagnostic.py")
s=importlib.util.spec_from_file_location("diagnostic",p)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def row(symbol,forecast,analogue,rate=.5,horizon=20):
 return {"symbol":symbol,"expected_return":forecast,"live_decision":{
   "market_session":"2026-10-16","final_action":"RECOVERY BUY","review_after_sessions":60,
   "evidence":{"technical":{"historical_analogues":{"status":"READY","sample_size":20,
     "positive_rate":rate,"horizon_sessions":horizon,"median_forward_return":analogue}}}}}
class Tests(unittest.TestCase):
 def test_godrej_conflict(self):
  d=m.classify(row("GODREJCP",-.0038966828,.017625),{"market_session":"2026-10-16","horizon_sessions":20})
  self.assertEqual(d["conflict_severity"],"DIRECTIONAL")
  self.assertIn("FORECAST_DIRECTION_CONFLICT",d["flags"])
 def test_hindzinc_material(self):
  d=m.classify(row("HINDZINC",.0628780144,-.047712,.25),{"market_session":"2026-10-16","horizon_sessions":20})
  self.assertEqual(d["conflict_severity"],"MATERIAL")
  self.assertIn("LOW_POSITIVE_ANALOGUE_RATE",d["flags"])
  self.assertEqual(d["recommendation_authority_changed"],False)
 def test_horizon_separation(self):
  d=m.classify(row("HINDZINC",.06,.01),{"market_session":"2026-10-16","horizon_sessions":20})
  self.assertIn("RECOMMENDATION_REVIEW_HORIZON_DIFFERS_FROM_FORECAST",d["flags"])
 def test_unknown_not_assumed(self):
  d=m.classify(row("GODREJCP",None,None),{"market_session":"2026-10-16","horizon_sessions":20})
  self.assertEqual(d["conflict_severity"],"UNKNOWN")
 def test_mismatched_session(self):
  d=m.classify(row("GODREJCP",.01,.02),{"market_session":"2026-10-15","horizon_sessions":20})
  self.assertIn("SESSION_MISMATCH",d["flags"])
 def test_no_production_promotion(self):
  data={"run":{"market_session":"2026-10-16","run_id":"synthetic"},"candidates":[row("HINDZINC",.06,-.04)]}
  self.assertFalse(m.audit(data)["ready_for_trading_rule_change"])
 def test_missing_analogue_horizon(self):
  d=m.classify(row("HINDZINC",.06,-.04,horizon=5),{"market_session":"2026-10-16","horizon_sessions":20})
  self.assertIn("ANALOGUE_HORIZON_MISMATCH",d["flags"])
if __name__=="__main__":unittest.main()
