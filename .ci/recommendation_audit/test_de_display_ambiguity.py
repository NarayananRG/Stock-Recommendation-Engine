import ast,math,types,unittest
from pathlib import Path
from urllib.parse import urlparse
source=Path(__file__).resolve().parents[1]/"native150"/"build_official_safety_supplement.py"
tree=ast.parse(source.read_text(encoding="utf-8"))
names={"numeric","eligible_debt_facts","reconcile","valid_corporate_debt_equity","process"}
nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
class Requests: HTTPError=type("HTTPError",(Exception,),{})
ns={"math":math,"requests":Requests,"OFFICIAL_HOST":"nsearchives.nseindia.com",
    "official":lambda url:urlparse(str(url)).hostname=="nsearchives.nseindia.com",
    "fetch":lambda url:b"test","parse_xbrl_document":lambda body,**kwargs:{
      "domain_source_url":"https://nsearchives.nseindia.com/filing.xml",
      "contexts":[{"context_id":"c","instant":"2026-06-30","dimensions":[]}],
      "numeric_facts":[{"concept_local_name":"DebtEquityRatio","context_ref":"c","raw_value":"1.2"}]},
    "classify_domain":lambda url:"IND_AS_CORPORATE",
    "effective_availability_ts":lambda event:"2026-08-01T09:00:00+05:30",
    "human_debt_ratio":lambda body:[1.2,120.0]}
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),"exec"),ns)
E={"symbol":"TEST","quarter_end":"2026-06-30","reporting_basis":"CONSOLIDATED",
   "xbrl_url":"https://nsearchives.nseindia.com/filing.xml",
   "ixbrl_url":"https://nsearchives.nseindia.com/display.html"}
class DisplayAmbiguity(unittest.TestCase):
 def test_current_prior_or_scale_ambiguity_fails_closed(self):
  result=ns["process"](E)
  self.assertEqual(result["status"],"AMBIGUOUS_DISPLAY_PERIOD_OR_SCALE")
  self.assertEqual(result["displayed_candidates"],[1.2,120.0])
 def test_unambiguous_display_preserves_verified_ratio(self):
  original=ns["human_debt_ratio"]
  try:
   ns["human_debt_ratio"]=lambda body:[1.2,1.2]
   result=ns["process"](E)
   self.assertEqual(result["status"],"VALIDATED")
   self.assertEqual(result["value"],1.2)
  finally:ns["human_debt_ratio"]=original
 def test_no_display_match_still_fails_closed(self):
  original=ns["human_debt_ratio"]
  try:
   ns["human_debt_ratio"]=lambda body:[9.7]
   self.assertEqual(ns["process"](E)["status"],"DISPLAY_XBRL_MISMATCH")
  finally:ns["human_debt_ratio"]=original
if __name__=="__main__":unittest.main()
