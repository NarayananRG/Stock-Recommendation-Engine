import importlib.util,unittest
from pathlib import Path
p=Path(__file__).with_name("sector_evidence_readiness.py")
spec=importlib.util.spec_from_file_location("readiness",p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def profile(fin=False):
 return {"sector_profile":"FINANCIAL_DOMAIN_CONSERVATIVE" if fin else "INDUSTRIAL",
 "available":True,"point_in_time_safe":True,"filing_freshness":"CURRENT_FOR_DECISION_TIME",
 "growth":{"revenue_yoy_symmetric_pct":6,"pat_yoy_symmetric_pct":8,"eps_yoy_symmetric_pct":9},
 "balance_sheet":{"debt_equity_ratio":0.5},"cash_flow":{"latest_operating_cash_flow":12},
 "valuation":{"pit_comparison_available":True},"risk_event":{"strong_deterioration_transition":False}}
def tech():return {"status":"READY","multi_timeframe":{"weekly_trend_confirmed":True}}
class Readiness(unittest.TestCase):
 def test_industrial(self):
  d=m.assess(profile(),tech());self.assertTrue(d["momentum_evidence_ready"]);self.assertTrue(d["recovery_evidence_ready"])
 def test_sector_specific_not_fake_debt(self):
  d=m.assess(profile(True),tech());self.assertFalse(d["recovery_evidence_ready"]);self.assertIn("debt_equity",d["inapplicable_industrial_metrics"])
 def test_missing_distinct_from_negative(self):
  f=profile();f["balance_sheet"]["debt_equity_ratio"]=None
  d=m.assess(f,tech());self.assertIn("debt_equity",d["missing_recovery_evidence"]);self.assertTrue(d["momentum_evidence_ready"])
  f["balance_sheet"]["debt_equity_ratio"]=-0.5
  self.assertNotIn("debt_equity",m.assess(f,tech())["missing_recovery_evidence"])
 def test_fails_closed_for_stale_and_adverse(self):
  f=profile();f["point_in_time_safe"]=False
  self.assertFalse(m.assess(f,tech())["momentum_evidence_ready"])
  f=profile();f["risk_event"]["strong_deterioration_transition"]=True
  self.assertFalse(m.assess(f,tech())["recovery_evidence_ready"])
 def test_invalid_numbers_missing(self):
  f=profile();f["growth"]["eps_yoy_symmetric_pct"]=float("nan");f["balance_sheet"]["debt_equity_ratio"]=True
  d=m.assess(f,tech());self.assertIn("eps_yoy_symmetric_pct",d["missing_growth_metrics"]);self.assertIn("debt_equity",d["missing_recovery_evidence"])
 def test_requires_real_200_stock_export(self):
  with self.assertRaisesRegex(ValueError,"ACTUAL_200"):m.inventory({"candidates":[]})
 def test_complete_inventory_no_promotion(self):
  items=[{"symbol":f"T{i:03d}.NS","live_decision":{"evidence":{"fundamental":profile(),"technical":tech()}}} for i in range(200)]
  report=m.inventory({"candidates":items})
  self.assertEqual(report["ready_counts"]["recovery_evidence_ready"],200)
  self.assertFalse(report["promotion_allowed"])
  items[1]["symbol"]="T000"
  with self.assertRaisesRegex(ValueError,"DUPLICATE"):m.inventory({"candidates":items})
if __name__=="__main__":unittest.main()
