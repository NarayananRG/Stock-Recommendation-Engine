"""Gate A: assert existing checked-in LIVE_DECISION_V1 wiring; not a packaged-runtime test."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2]
class TestExistingLiveWiring(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.patch=(ROOT/".ci/native140/patch140.py").read_text(encoding="utf-8")
  cls.router=(ROOT/".ci/native140/live_decision_v1.py").read_text(encoding="utf-8")
  cls.status=(ROOT/".ci/native148/patch148_analysis_refresh.py").read_text(encoding="utf-8")
 def test_fundamental_v3_live(self):
  self.assertIn("('fundamental_v3.py','LIVE_EVIDENCE')",self.patch)
 def test_technical_v2_live(self):
  self.assertIn("('technical_v2.py','LIVE_EVIDENCE')",self.patch)
 def test_v3_context_to_router(self):
  self.assertIn("self.fundamental_v3_context(symbol, price, session)",self.patch)
  self.assertIn("live = route(symbol, session, technical, fundamental, price_context=context,",self.patch)
 def test_allocation_live_decision(self):
  self.assertIn('(row.get("live_decision") or {}).get("final_action")',self.patch)
 def test_official_gate(self):
  self.assertIn("official_current is True and momentum_valid",self.router)
 def test_fundamental_gate(self):
  self.assertIn("strong and safety and fundamental_ready",self.router)
 def test_daily_status_source(self):
  self.assertIn('(row.get("live_decision") or {}).get("executable") is True',self.status)
if __name__=="__main__":unittest.main()
