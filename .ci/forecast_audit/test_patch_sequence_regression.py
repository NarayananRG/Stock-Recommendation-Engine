"""Check exact 0.14.11 patch anchor after the 0.14.0 forecast overlay.

This test reproduces the failing code shape and checks a real minimal
Python source transformation, before the expensive Windows packaging gate.
"""
import ast, unittest
from pathlib import Path

root=Path(__file__).resolve().parents[2]
patch152=(root/".ci/native152/patch152_missing_evidence.py").read_text()
patch140=(root/".ci/native140/patch140.py").read_text()
ROUTE='''            live = route(symbol, session, technical, fundamental, price_context=context,
                         official_current=current and bool(bars) and str(bars[-1].get("date"))[:10] == session, legacy=dict(row))
'''
OLD=ROUTE+'''            rows.append({**row, "legacy_opportunity_status": row.get("opportunity_status"), "live_decision": live,
'''
NEW=ROUTE+'''            from stock_app.forecast_conflict_diagnostic import classify as classify_forecast_conflict
            diagnostic = classify_forecast_conflict({**row, "live_decision": live}, run)
            rows.append({**row, "forecast_diagnostic": diagnostic, "legacy_opportunity_status": row.get("opportunity_status"), "live_decision": live,
'''
ANNOTATED=ROUTE+'''            # Diagnostic annotation only; the router action remains unchanged.
            live["evidence_classification"] = classify_live_decision(live)
'''
class PatchSequenceTests(unittest.TestCase):
    def test_original_case(self):
        self.assertEqual(OLD.count(ROUTE),1)
        self.assertIn(ANNOTATED,OLD.replace(ROUTE,ANNOTATED,1))
    def test_diagnostic_overlay_case(self):
        self.assertIn("from stock_app.forecast_conflict_diagnostic",NEW)
        self.assertNotIn(OLD,NEW)
        fixed=NEW.replace(ROUTE,ANNOTATED,1)
        self.assertIn(ANNOTATED,fixed)
        self.assertIn('"forecast_diagnostic": diagnostic',fixed)
        self.assertIn('classify_forecast_conflict({**row, "live_decision": live}, run)',fixed)
    def test_exact_patch_anchor_present_in_source(self):
        self.assertIn('''replace_once(api,
''' + "'''" + ROUTE,patch152)
        self.assertIn('''            live["evidence_classification"] = classify_live_decision(live)''',patch152)
        self.assertIn('''            diagnostic = classify_forecast_conflict({**row, "live_decision": live}, run)''',patch140)
    def test_no_production_decision_mutation(self):
        self.assertNotIn('live["final_action"] =',patch152)
        self.assertNotIn('live["executable"] =',patch152)
        ast.parse(patch152)
        ast.parse(patch140)
if __name__=="__main__":unittest.main()
