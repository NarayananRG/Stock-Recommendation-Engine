import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/".ci/native140"))
from live_decision_v1 import number,interpret

class QuantitativeEvidenceTests(unittest.TestCase):
 def test_bool_is_not_numeric(self):
  self.assertIsNone(number(True))
  self.assertIsNone(number(False))
 def test_financial_balance_boolean_is_unavailable(self):
  base={"growth":{"revenue_yoy_symmetric_pct":9,"pat_yoy_symmetric_pct":8,"eps_yoy_symmetric_pct":8},"profitability":{"pat_margin_pct":10},"balance_sheet":{"debt_equity_ratio":True},"risk_event":{"available":True,"event_profile":"PURE_IMPROVEMENT"}}
  s=interpret(base)
  self.assertEqual(s["balance_sheet_state"],"UNAVAILABLE")
 def test_true_numeric_zero_remains_valid(self):
  self.assertEqual(number(0),0)
  self.assertEqual(number("0.75"),0.75)
if __name__=="__main__":unittest.main()
