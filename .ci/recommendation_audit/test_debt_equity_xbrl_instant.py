"""XBRL debt-to-equity ratio must use a dimensionless quarter-end instant context."""
import ast
import math
import unittest
from pathlib import Path

p=Path(__file__).resolve().parents[1]/"native150"/"build_official_safety_supplement.py"
tree=ast.parse(p.read_text(encoding="utf-8"))
names={"numeric","eligible_debt_facts"}
nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
ns={"math":math}
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(p),"exec"),ns)
eligible=ns["eligible_debt_facts"]
def doc(contexts):
 return {"contexts":contexts,"numeric_facts":[{"concept_local_name":"DebtEquityRatio","context_ref":c["context_id"],"raw_value":"0.45"} for c in contexts]}
event={"quarter_end":"2026-06-30"}
class ContextTests(unittest.TestCase):
 def test_valid_instant_accepted(self):
  c={"context_id":"i","instant":"2026-06-30","dimensions":{}}
  self.assertEqual(len(eligible(doc([c]),event)),1)
 def test_duration_ending_on_quarter_rejected(self):
  c={"context_id":"d","start_date":"2026-04-01","end_date":"2026-06-30","dimensions":{}}
  self.assertEqual(eligible(doc([c]),event),[])
 def test_unrelated_instant_rejected(self):
  c={"context_id":"old","instant":"2026-03-31","dimensions":{}}
  self.assertEqual(eligible(doc([c]),event),[])
 def test_dimensioned_instant_rejected(self):
  c={"context_id":"segment","instant":"2026-06-30","dimensions":{"SegmentAxis":"A"}}
  self.assertEqual(eligible(doc([c]),event),[])
 def test_mixed_context_picks_only_valid_instant(self):
  a={"context_id":"a","instant":"2026-06-30","dimensions":{}}
  b={"context_id":"b","end_date":"2026-06-30","start_date":"2026-04-01","dimensions":{}}
  self.assertEqual([x["context_ref"] for x in eligible(doc([a,b]),event)],["a"])
if __name__=="__main__":unittest.main()
