"""Gate A: exercise injected run restoration logic against controlled files.

Runs without market access, installed app, or changes to any trading ledger.
"""
import ast
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

PATCH = Path(__file__).with_name("patch_run_selection_01413.py")
tree=ast.parse(PATCH.read_text(encoding="utf-8"))
replacement=next(node.value.value for node in tree.body
                 if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id=="replacement" for t in node.targets))
namespace={"Any":object, "APP_VERSION":"0.14.13-paper-trading-repair"}
exec("class Recovered:\n"+replacement,namespace)
Recovered=namespace["Recovered"]

OLD="old-run"
NEW="new-run"

class Harness(Recovered):
    def __init__(self,folder, old_session="2026-10-15", new_session="2026-10-16", explicit=False, compatible=True):
        self.folder=Path(folder)
        self.active_analysis_file=self.folder/"active_analysis_run.json"
        self._phase6_run_selected_in_session=explicit
        self.state={"last_successful_run":{"run_id":NEW,"market_session":new_session,
            "model_version":"0.14.13-paper-trading-repair" if compatible else "unknown-version"}}
        self.selection=OLD
        self._write(OLD, old_session)
        self._write(NEW, new_session)
    def _write(self, id,session):
        (self.folder/(id+".json")).write_text(json.dumps({"run":{"run_id":id,"market_session":session},"candidates":[]}),encoding="utf-8")
    def _live_file(self,id):
        return self.folder/(id+".json")
    def _saved_active_run_id(self):
        if self.active_analysis_file.exists():
            return json.loads(self.active_analysis_file.read_text(encoding="utf-8"))["run_id"]
        return self.selection
    def _read_daily_state(self):
        return self.state

class GateARunRestoration(unittest.TestCase):
    def test_newer_official_restored(self):
        with tempfile.TemporaryDirectory() as d:
            h=Harness(d)
            self.assertEqual(h.active_prediction_run()["run"]["run_id"],NEW)
            self.assertEqual(json.loads(h.active_analysis_file.read_text())["run_id"],NEW)
    def test_manual_selection_not_overridden(self):
        with tempfile.TemporaryDirectory() as d:
            h=Harness(d,explicit=True)
            self.assertEqual(h.active_prediction_run()["run"]["run_id"],OLD)
            self.assertFalse(h.active_analysis_file.exists())
    def test_different_model_not_promoted(self):
        with tempfile.TemporaryDirectory() as d:
            h=Harness(d,compatible=False)
            self.assertEqual(h.active_prediction_run()["run"]["run_id"],OLD)
    def test_missing_latest_run_not_promoted(self):
        with tempfile.TemporaryDirectory() as d:
            h=Harness(d)
            h._live_file(NEW).unlink()
            self.assertEqual(h.active_prediction_run()["run"]["run_id"],OLD)
    def test_same_session_keeps_old(self):
        with tempfile.TemporaryDirectory() as d:
            h=Harness(d,new_session="2026-10-15")
            self.assertEqual(h.active_prediction_run()["run"]["run_id"],OLD)
    def test_no_ledger_mutations(self):
        self.assertNotIn("paper_",replacement)
        self.assertNotIn("DELETE FROM",replacement)
        self.assertNotIn("UPDATE ",replacement)

if __name__=="__main__":
    unittest.main()
