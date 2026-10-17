import importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location("trace",Path(__file__).with_name("evidence_trace.py"))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class T(unittest.TestCase):
 def sample(self):
  return {"run":{"run_id":"r","market_session":"2026-10-16"},"candidates":[{"symbol":"ABC.NS","live_decision":{"financial_domain":False,"evidence":{"fundamental":{"available":True,"point_in_time_safe":True,"balance_sheet":{},"risk_event":{"event_profile":"MIXED_DIRECTIONAL","strong_deterioration_transition":False,"deterioration_evidence":[{"feature":"PAT","symmetric_change":"-0.03"},{"feature":"EPS","symmetric_change":"-0.25"}],"improvement_evidence":[{"feature":"REVENUE","symmetric_change":"0.11"}]}}}}}]}
 def test_magnitude_and_presence(self):
  out=m.inspect(self.sample());counts={(x["dimension"],x["value"]):x["count"] for x in out["counts"]}
  self.assertEqual(counts["deterioration_evidence_abs_symmetric_change_band","LT_0_05"],1)
  self.assertEqual(counts["deterioration_evidence_abs_symmetric_change_band","GTE_0_20"],1)
  self.assertEqual(counts["debt_ratio","OTHER_OR_UNKNOWN:ABSENT"],1)
  self.assertFalse(out["production_changed"])
 def test_absent_evidence_is_explicit(self):
  p=self.sample();p["candidates"][0]["live_decision"]["evidence"]["fundamental"]["risk_event"].pop("deterioration_evidence")
  out=m.inspect(p)
  self.assertIn({"dimension":"deterioration_evidence_details","value":"ABSENT","count":1},out["counts"])
 def test_duplicate_rejected(self):
  p=self.sample();p["candidates"].append(p["candidates"][0].copy())
  with self.assertRaises(ValueError):m.inspect(p)
if __name__=="__main__":unittest.main()
