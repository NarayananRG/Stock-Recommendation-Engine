"""Validate a research-only global-event register; never treat hypotheses as trades."""
import json, unittest
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parent
class GlobalRegisterTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.data=json.loads((ROOT/"observations_2026-10-18.json").read_text(encoding="utf-8"))
 def test_shadow_only(self):
  self.assertEqual(self.data["authority"],"SHADOW_ONLY")
  self.assertIs(self.data["production_decision_eligible"],False)
 def test_source_publication_not_after_research_cutoff(self):
  cutoff=date.fromisoformat(self.data["as_of"])
  for o in self.data["observations"]:
   self.assertLessEqual(date.fromisoformat(o["published_on"]),cutoff)
   self.assertEqual(urlparse(o["url"]).scheme,"https")
   self.assertTrue(urlparse(o["url"]).netloc)
 def test_no_asserted_causality(self):
  for o in self.data["observations"]:
   self.assertEqual(o["causality_status"],"NOT_ESTABLISHED")
   self.assertNotIn("recommended_action",o)
   self.assertNotIn("stock_signal",o)
 def test_unique_observations(self):
  ids=[o["id"] for o in self.data["observations"]]
  self.assertEqual(len(ids),len(set(ids)))
  self.assertGreater(len(ids),0)
if __name__=="__main__":unittest.main()
