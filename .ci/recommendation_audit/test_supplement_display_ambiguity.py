"""Regression tests for ambiguous official debt/equity display cells."""
from __future__ import annotations
import ast,math,unittest
from pathlib import Path

SOURCE=Path(__file__).resolve().parents[1]/"native150"/"build_official_safety_supplement.py"
TREE=ast.parse(SOURCE.read_text(encoding="utf-8"))
names={"reconcile","resolve_display_matches"}
functions=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name in names]
scope={"math":math}
exec(compile(ast.Module(body=functions,type_ignores=[]),str(SOURCE),"exec"),scope)
reconcile=scope["reconcile"];resolve=scope["resolve_display_matches"]

class DisplayPeriodSafety(unittest.TestCase):
 def test_single_exact_match(self):
  m=reconcile(1.25,1.25)
  selected=resolve([(1.25,m)])
  self.assertEqual(selected[0],1.25)
  self.assertEqual(selected[1]["normalization"],"RAW")
 def test_repeated_identical_cells_are_ok(self):
  rec=reconcile(1.25,1.25)
  self.assertIsNotNone(resolve([(1.25,rec),(1.25,rec)]))
 def test_raw_and_percentage_scaled_prior_period_values_ambiguous(self):
  raw=reconcile(1,1)
  scaled=reconcile(1,100)
  self.assertIsNotNone(raw)
  self.assertIsNotNone(scaled)
  self.assertIsNone(resolve([(1,raw),(100,scaled)]))
 def test_empty_or_no_valid_match_rejected(self):
  self.assertIsNone(resolve([]))
  self.assertIsNone(reconcile(1.3,4.7))
 def test_previous_selection_remains_deterministic(self):
  r1={"normalization":"RAW_X100","absolute_error":0.0}
  r2={"normalization":"RAW","absolute_error":0.0}
  self.assertEqual(resolve([(2.0,r1),(2.0,r2)])[1]["normalization"],"RAW")
if __name__=="__main__":unittest.main()
