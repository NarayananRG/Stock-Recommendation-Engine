import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"NextGen Research"))
from fundamental_research_v2_phase2a.xbrl_extraction import _numeric

class ExtractionNumericTests(unittest.TestCase):
 def test_invalid_nonfinite(self):
  for value in ("NaN","Infinity","-Infinity","sNaN","—","-",""):
   with self.subTest(value=value):self.assertFalse(_numeric(value))
 def test_finite_real_facts(self):
  for value in ("0","-0.25","1,234.50","+3.9","1E-3"):
   with self.subTest(value=value):self.assertTrue(_numeric(value))
if __name__=="__main__":unittest.main()
