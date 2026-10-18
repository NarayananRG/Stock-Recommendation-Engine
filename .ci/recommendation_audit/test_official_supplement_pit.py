"""Check official filing point-in-time timestamp policy without running network jobs."""
from __future__ import annotations
import ast
from datetime import date,datetime
from pathlib import Path
import unittest

FILE=Path(__file__).resolve().parents[1]/"native150"/"build_official_safety_supplement.py"
tree=ast.parse(FILE.read_text(encoding="utf-8"))
fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="pit_availability_is_valid")
ns={"date":date,"datetime":datetime}
exec(compile(ast.Module(body=[fn],type_ignores=[]),str(FILE),"exec"),ns)
VALID=ns["pit_availability_is_valid"]

class FilingPublicationSafetyTests(unittest.TestCase):
    def test_valid_timestamp_with_timezone(self):
        self.assertTrue(VALID("2026-08-10T09:10:00+05:30","2026-06-30"))
        self.assertTrue(VALID("2026-08-10T03:40:00Z","2026-06-30"))
    def test_missing_naive_and_invalid_not_point_in_time_safe(self):
        for bad in (None,"", "2026-08-10T09:10:00","not-a-date",True):
            with self.subTest(bad=bad):
                self.assertFalse(VALID(bad,"2026-06-30"))
    def test_pre_reporting_period_rejected(self):
        self.assertFalse(VALID("2026-03-01T09:10:00+05:30","2026-06-30"))
    def test_invalid_quarter_rejected(self):
        self.assertFalse(VALID("2026-08-10T09:10:00+05:30","not-a-quarter"))
    def test_no_pit_bypass_in_supplement_builder(self):
        body=FILE.read_text(encoding="utf-8")
        self.assertIn('if not pit_availability_is_valid(availability, event.get("quarter_end")):',body)
        self.assertIn('UNVERIFIABLE_PIT_PUBLICATION_TIMESTAMP',body)

if __name__=="__main__":
    unittest.main()
