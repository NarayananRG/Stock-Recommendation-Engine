import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
module_path=ROOT/"NextGen Research/fundamental_research_v2_phase2a/canonical_feature_panel.py"
sys.path.insert(0,str(ROOT/"NextGen Research"))
from fundamental_research_v2_phase2a.canonical_feature_panel import numeric_or_none

class NumericEvidenceTests(unittest.TestCase):
 def test_nonfinite_is_missing(self):
  for val in ("NaN","Infinity","-Infinity","sNaN",float("nan"),float("inf")):
   with self.subTest(val=val):self.assertIsNone(numeric_or_none(val))
 def test_real_zero_and_debt_ratio_retained(self):
  self.assertEqual(numeric_or_none(0),"0")
  self.assertEqual(numeric_or_none("0.65"),"0.65")
 def test_unparseable_is_missing(self):
  self.assertIsNone(numeric_or_none("unavailable"))
  self.assertIsNone(numeric_or_none(None))

if __name__=="__main__":unittest.main()
