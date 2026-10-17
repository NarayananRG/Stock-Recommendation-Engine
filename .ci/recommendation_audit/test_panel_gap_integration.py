import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"NextGen Research"))
from fundamental_research_v2_phase2a.canonical_feature_panel import build_panel_rows,continuity_audit

def row(status,value,domain="IND_AS_CORPORATE",gap=False):
 return {"symbol":"TEST","reporting_basis":"CONSOLIDATED","quarter_end":"2026-06-30","archive_gap":gap,"domain":domain,
         "DEBT_EQUITY_RATIO__status":status,"DEBT_EQUITY_RATIO__value":value}
class Tests(unittest.TestCase):
 def test_statuses(self):
  # Separate histories to avoid duplicate per-quarter keys in historical summary.
  rs=[dict(row("SELECTED","0"),symbol="A"),dict(row("SELECTED","NaN"),symbol="B"),
      dict(row("NOT_MAPPED_FOR_DOMAIN",None),symbol="C"),dict(row("MISSING",None),symbol="D"),
      dict(row("AMBIGUOUS_MULTIPLE_CANDIDATES",None),symbol="E"),dict(row("SOURCE_DOCUMENT_UNAVAILABLE",None,gap=True),symbol="F")]
  o=continuity_audit(rs)["debt_equity_source_gap_counts"]
  for k in ("AVAILABLE","SELECTED_VALUE_MISSING","MAPPING_NOT_AVAILABLE","NO_ELIGIBLE_FACT","AMBIGUOUS_FACTS","SOURCE_DOCUMENT_UNAVAILABLE"):
   self.assertEqual(o[k],1)
 def test_domain_breakdown(self):
  rs=[dict(row("NOT_MAPPED_FOR_DOMAIN",None,domain="UNKNOWN"),symbol="A")]
  output=continuity_audit(rs)
  self.assertEqual(output["debt_equity_domain_gap_counts"][0]["domain"],"UNKNOWN")
  self.assertFalse(output["production_model_changed"])
 def test_unsupported_official_domain_is_preserved_fail_closed(self):
  event={"event_id":"insurance","symbol":"LIFE","quarter_end":"2026-06-30","reporting_basis":"STANDALONE","submission_type":"ORIGINAL","availability_ts":"2026-07-20T10:00:00+05:30"}
  document={"source_event_id":"insurance","domain":"LIFE_INSURANCE","source_document_kind":"XBRL","retrieval_representation":"XBRL_PRIMARY","source_content_sha256":"a"*64,"hard_failures":[{"code":"NO_FROZEN_MAPPING_FOR_DOMAIN","domain":"LIFE_INSURANCE"}],"features":{}}
  rows=build_panel_rows([event],[document],set())
  self.assertEqual(rows[0]["domain"],"LIFE_INSURANCE")
  self.assertEqual(rows[0]["DEBT_EQUITY_RATIO__status"],"NOT_MAPPED_FOR_DOMAIN")
  self.assertFalse(rows[0]["archive_gap"])
if __name__=="__main__":unittest.main()
