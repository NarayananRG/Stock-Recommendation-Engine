import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/".ci/native140"))
from live_decision_v1 import monitor
class PositionMetadataTests(unittest.TestCase):
 def check(self,held,review=20,style="MOMENTUM"):
  return monitor({"primary_style":style,"sessions_held":held,"entry_thesis":{"review_after_sessions":review}},{"structural_deterioration":False,"technical_state":"STRONG","momentum_thesis":"VALID","recovery_thesis":"VALID","valuation_state":"ATTRACTIVE"})
 def test_valid_holding_period(self):
  self.assertEqual(self.check(19)[0],"HOLD")
  self.assertEqual(self.check(20)[0],"WEAKENING")
  self.assertEqual(self.check("20","20")[0],"WEAKENING")
 def test_invalid_held_counts_require_review(self):
  for held in (True,-1,1.2,"abc",float("nan"),float("inf")):
   with self.subTest(held=held):
    state,reason=self.check(held)
    self.assertEqual(state,"WEAKENING")
    self.assertIn("metadata",reason)
 def test_invalid_review_counts_require_review(self):
  for review in (True,0,-2,1.5,"unavailable",float("inf")):
   with self.subTest(review=review):
    state,reason=self.check(1,review)
    self.assertEqual(state,"WEAKENING")
    self.assertIn("metadata",reason)
 def test_material_risk_still_exits_first(self):
  p={"primary_style":"MOMENTUM","sessions_held":"bad"}
  self.assertEqual(monitor(p,{"structural_deterioration":True})[0],"EXIT")
 def test_recovery_remains_hold_when_valid(self):
  self.assertEqual(self.check(30,60,"RECOVERY")[0],"HOLD")
if __name__=="__main__":unittest.main()
