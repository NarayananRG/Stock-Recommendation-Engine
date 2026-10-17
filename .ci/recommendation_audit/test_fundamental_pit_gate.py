import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/".ci/native140"))
from live_decision_v1 import interpret

class AvailabilityTests(unittest.TestCase):
 def base(self):
  return {"available":True,"point_in_time_safe":True,"filing_freshness":"CURRENT"}
 def test_valid_explicit_booleans(self):
  self.assertEqual(interpret(self.base())["fundamental_data_quality"],"AVAILABLE")
 def test_truthy_strings_cannot_bypass_gate(self):
  for field in ("available","point_in_time_safe"):
   for invalid in ("False","true",1,"yes",None):
    with self.subTest(field=field,invalid=invalid):
     p=self.base();p[field]=invalid
     self.assertEqual(interpret(p)["fundamental_data_quality"],"UNAVAILABLE")
 def test_stale_overrides_available(self):
  p=self.base();p["filing_freshness"]="STALE"
  self.assertEqual(interpret(p)["fundamental_data_quality"],"STALE")
if __name__=="__main__":unittest.main()
