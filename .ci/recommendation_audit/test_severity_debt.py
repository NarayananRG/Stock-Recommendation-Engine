import importlib.util, unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location("sd",Path(__file__).with_name("severity_debt.py"))
sd=importlib.util.module_from_spec(spec);spec.loader.exec_module(sd)
class Tests(unittest.TestCase):
 def sample(self):
  return {"run":{"run_id":"r1","market_session":"2026-10-16"},"candidates":[
   {"symbol":"AAA","live_decision":{"financial_domain":False,"balance_sheet_state":"UNAVAILABLE","evidence":{"fundamental":{"balance_sheet":{},"risk_event":{"event_profile":"MIXED_DIRECTIONAL","strong_deterioration_transition":False,"improvement_evidence_count":4}}}}},
   {"symbol":"BBB.NS","live_decision":{"financial_domain":True,"balance_sheet_state":"UNAVAILABLE","evidence":{"fundamental":{"balance_sheet":{"debt_equity_ratio":2.0},"risk_event":{"event_profile":"MIXED_DIRECTIONAL","strong_deterioration_transition":True,"deterioration_evidence_count":1}}}}}]}
 def test_severity_and_missing_are_distinct(self):
  r=sd.audit(self.sample());m={(x["dimension"],x["value"]):x["count"] for x in r["counts"]}
  self.assertEqual(m["mixed_strong_deterioration","False"],1)
  self.assertEqual(m["mixed_strong_deterioration","True"],1)
  self.assertEqual(m["mixed_improvement_evidence_count","ABSENT"],1)
  self.assertEqual(m["debt_ratio_presence","OTHER_OR_UNKNOWN:ABSENT"],1)
  self.assertFalse(r["production_changed"])
 def test_duplicates_fail(self):
  d=self.sample();d["candidates"][1]["symbol"]="AAA.NS"
  with self.assertRaises(ValueError):sd.audit(d)
 def test_missing_run_fails(self):
  with self.assertRaises(ValueError):sd.audit({"run":{},"candidates":[]})
if __name__=="__main__":unittest.main()
