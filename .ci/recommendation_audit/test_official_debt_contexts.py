"""Validate official debt-ratio context ambiguity without fetching market data."""
import ast,math,unittest
from pathlib import Path
p=Path(__file__).resolve().parents[1]/"native150"/"build_official_safety_supplement.py"
tree=ast.parse(p.read_text(encoding="utf-8"))
functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ("numeric","eligible_debt_facts")]
ns={"math":math}
exec(compile(ast.Module(body=functions,type_ignores=[]),str(p),"exec"),ns)
eligible=ns["eligible_debt_facts"]

def fact(value,context):
 return {"concept_local_name":"DebtEquityRatio","raw_value":value,"context_ref":context,"scale":0,"decimals":2}
def ctx(id,instant,dimensions=None):
 return {"context_id":id,"instant":instant,"dimensions":dimensions or {}}
class DebtContextTests(unittest.TestCase):
 def test_ignores_segment_facts(self):
  doc={"contexts":[ctx("whole","2026-06-30"),ctx("segment","2026-06-30",{"Segment":"A"})],"numeric_facts":[fact("0.4","whole"),fact("3.0","segment")]}
  self.assertEqual([x["raw_value"] for x in eligible(doc,{"quarter_end":"2026-06-30"})],[0.4])
 def test_ignores_other_period(self):
  doc={"contexts":[ctx("old","2026-03-31")],"numeric_facts":[fact("0.4","old")]}
  self.assertEqual(eligible(doc,{"quarter_end":"2026-06-30"}),[])
 def test_duplicate_current_contexts_must_not_hide_conflict(self):
  doc={"contexts":[ctx("one","2026-06-30"),ctx("two","2026-06-30")],"numeric_facts":[fact("0.4","one"),fact("0.7","two")]}
  self.assertEqual(len({x["raw_value"] for x in eligible(doc,{"quarter_end":"2026-06-30"})}),2)
 def test_boolean_and_nonfinite_not_market_values(self):
  doc={"contexts":[ctx("one","2026-06-30")],"numeric_facts":[fact("nan","one"),fact("inf","one")]}
  self.assertEqual(eligible(doc,{"quarter_end":"2026-06-30"}),[])
if __name__=="__main__":unittest.main()
