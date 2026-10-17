"""Static wiring checks plus end-to-end diagnostic contract from real-looking records."""
import ast, importlib.util, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
PATCH=(ROOT/".ci/native140/patch140.py").read_text()
SRC=ROOT/".ci/forecast_audit/forecast_conflict_diagnostic.py"
spec=importlib.util.spec_from_file_location("forecast_conflict",SRC)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class IntegrationTests(unittest.TestCase):
 def test_overlay_source_is_valid(self):
  ast.parse(PATCH);ast.parse(SRC.read_text())
 def test_module_is_copied_into_installed_engine(self):
  self.assertIn("root / 'stock_app/forecast_conflict_diagnostic.py'",PATCH)
 def test_materialization_adds_diagnostic_without_replacing_action(self):
  self.assertIn('"forecast_diagnostic": diagnostic',PATCH)
  self.assertIn('"live_decision": live',PATCH)
  self.assertIn('classify_forecast_conflict({**row, "live_decision": live}, run)',PATCH)
 def test_end_to_end_hindzinc_conflict(self):
  run={"run_id":"fixture","market_session":"2026-10-16","horizon_sessions":20}
  live={"final_action":"RECOVERY BUY","market_session":"2026-10-16",
        "review_after_sessions":60,"executable":True,
        "evidence":{"technical":{"historical_analogues":{"status":"READY","sample_size":20,
                  "horizon_sessions":20,"positive_rate":.25,"median_forward_return":-.047712}}}}
  row={"symbol":"HINDZINC","expected_return":.0628780144748354,"live_decision":live}
  before=repr(row)
  diag=m.classify(row,run)
  self.assertEqual(diag["conflict_severity"],"MATERIAL")
  self.assertEqual(diag["decision"],"RECOVERY BUY")
  self.assertIn("FORECAST_DIRECTION_CONFLICT",diag["flags"])
  self.assertEqual(repr(row),before)
  self.assertFalse(diag["recommendation_authority_changed"])
 def test_no_live_trading_rule_migration(self):
  self.assertNotIn('live["final_action"] = diagnostic',PATCH)
  self.assertNotIn('live["executable"] = diagnostic',PATCH)

if __name__=="__main__":unittest.main()
