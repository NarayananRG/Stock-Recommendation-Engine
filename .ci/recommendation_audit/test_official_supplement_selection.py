"""Regression tests for latest-quarter official filing selection, no network calls."""
from __future__ import annotations
import ast
from collections import defaultdict
from pathlib import Path
import unittest

SOURCE=Path(__file__).resolve().parents[1]/"native150"/"build_official_safety_supplement.py"
TREE=ast.parse(SOURCE.read_text(encoding="utf-8"))
FN=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name=="selected_latest_symbol_events")
ns={"latest_event_groups":lambda events:events,"defaultdict":defaultdict,"sorted":sorted,"str":str,"official":lambda url:url.startswith("https://nsearchives.nseindia.com/")}
exec(compile(ast.Module(body=[FN],type_ignores=[]),str(SOURCE),"exec"),ns)
SELECT=ns["selected_latest_symbol_events"]

class LatestOfficialFilingSelection(unittest.TestCase):
    def event(self,quarter,basis,url="https://nsearchives.nseindia.com/test.xml",symbol="AAA"):
        return {"symbol":symbol,"quarter_end":quarter,"reporting_basis":basis,"xbrl_url":url}
    def test_newer_standalone_beats_older_consolidated(self):
        e=[self.event("2026-03-31","CONSOLIDATED"),self.event("2026-06-30","STANDALONE")]
        self.assertEqual(SELECT(e)[0]["quarter_end"],"2026-06-30")
    def test_same_quarter_prefers_consolidated(self):
        e=[self.event("2026-06-30","STANDALONE"),self.event("2026-06-30","CONSOLIDATED")]
        self.assertEqual(SELECT(e)[0]["reporting_basis"],"CONSOLIDATED")
    def test_ignores_unavailable_xbrl_and_selects_per_symbol(self):
        e=[self.event("2026-09-30","CONSOLIDATED",url=""),
           self.event("2026-06-30","STANDALONE"),
           self.event("2026-06-30","CONSOLIDATED",symbol="BBB")]
        out=SELECT(e)
        self.assertEqual([x["symbol"] for x in out],["AAA","BBB"])
        self.assertEqual(out[0]["quarter_end"],"2026-06-30")
    def test_nonofficial_and_incomplete_events_excluded(self):
        events=[self.event("2026-09-30","CONSOLIDATED",url="https://example.com/report.xml"),self.event("2026-06-30","STANDALONE"),self.event("2026-09-30","UNKNOWN")]
        chosen=SELECT(events)
        self.assertEqual(chosen[0]["quarter_end"],"2026-06-30")
    def test_does_not_generate_missing_filing(self):
        self.assertEqual(SELECT([self.event("2026-06-30","STANDALONE",url="")]),[])
if __name__=="__main__":unittest.main()
