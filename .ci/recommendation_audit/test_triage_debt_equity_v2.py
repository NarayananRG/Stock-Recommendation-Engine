import csv,importlib.util,tempfile,unittest
from pathlib import Path
p=Path(__file__).with_name("triage_debt_equity_v2.py")
spec=importlib.util.spec_from_file_location("triage_de",p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
METRICS=("DEBT_EQUITY_RATIO","TOTAL_DEBT","SHAREHOLDERS_EQUITY")
class GapTriageTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
  self.p=Path(self.t.name)/"matrix.csv"
 def write(self,states,duplicate=False):
  with self.p.open("w",newline="") as f:
   fields=["symbol","metric","after_status","domain","quarter_end","reporting_basis","publication_ts","event_id","source_url"]
   w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
   for symbol,statuses in states.items():
    for metric,status in zip(METRICS,statuses):
     w.writerow({"symbol":symbol,"metric":metric,"after_status":status,"domain":"INDUSTRIAL",
     "quarter_end":"2026-06-30","reporting_basis":"CONSOLIDATED",
     "publication_ts":"2026-08-10T09:00:00+05:30","event_id":"E1","source_url":"https://example.org/filing"})
   if duplicate:w.writerow({"symbol":next(iter(states)),"metric":"DEBT_EQUITY_RATIO",
     "after_status":"MISSING_IN_SOURCE","domain":"INDUSTRIAL"})
 def test_component_mapping_is_review_not_ratio(self):
  self.write({"AAA":("MISSING_IN_SOURCE","AVAILABLE_BUT_NOT_MAPPED","AVAILABLE_BUT_NOT_MAPPED")})
  r=m.triage(self.p,1,3)
  self.assertEqual(r["triage_counts"]["COMPONENT_MAPPING_REVIEW"],1)
  self.assertEqual(r["ratios_derived"],0)
  self.assertFalse(r["findings"][0]["safe_to_derive_debt_equity"])
 def test_verified_and_financial_inapplicable_not_missing(self):
  self.write({"AAA":("AVAILABLE_VERIFIED","MISSING_IN_SOURCE","MISSING_IN_SOURCE"),
              "BBB":("FINANCIAL_DOMAIN_NOT_APPLICABLE","MISSING_IN_SOURCE","MISSING_IN_SOURCE")})
  r=m.triage(self.p,2,3)
  self.assertEqual(r["gap_count"],0)
 def test_unverifiable_and_source_gap_are_distinct(self):
  self.write({"AAA":("UNVERIFIABLE","MISSING_IN_SOURCE","MISSING_IN_SOURCE"),
              "BBB":("SOURCE_NOT_ACQUIRED","MISSING_IN_SOURCE","MISSING_IN_SOURCE")})
  r=m.triage(self.p,2,3)
  self.assertEqual(r["triage_counts"]["OFFICIAL_VALUE_FAILED_VERIFICATION"],1)
  self.assertEqual(r["triage_counts"]["ACQUISITION_OR_PARSE_GAP"],1)
 def test_incomplete_or_duplicate_matrix_rejected(self):
  self.write({"AAA":("MISSING_IN_SOURCE","MISSING_IN_SOURCE","MISSING_IN_SOURCE")},duplicate=True)
  with self.assertRaisesRegex(ValueError,"MATRIX_CELL_COUNT_MISMATCH"):m.triage(self.p,1,3)
  with self.assertRaisesRegex(ValueError,"DUPLICATE_OR_MISSING"):m.triage(self.p,1,4)
 def test_real_matrix_required(self):
  with self.assertRaises(FileNotFoundError):m.triage(Path(self.t.name)/"missing.csv",1,3)
if __name__=="__main__":unittest.main()
