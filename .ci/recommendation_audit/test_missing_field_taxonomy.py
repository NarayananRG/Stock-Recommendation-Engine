import importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location("t",Path(__file__).with_name("missing_field_taxonomy.py"))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Tests(unittest.TestCase):
 def test_selected_zero_is_valid(self):
  self.assertEqual(m.classify({"DEBT_EQUITY_RATIO__status":"SELECTED","DEBT_EQUITY_RATIO__value":"0"})["kind"],"AVAILABLE")
 def test_missing_selected_is_not_recovered(self):
  r=m.classify({"DEBT_EQUITY_RATIO__status":"SELECTED","DEBT_EQUITY_RATIO__value":None})
  self.assertEqual(r["kind"],"SELECTED_VALUE_MISSING");self.assertFalse(r["recoverable_automatically"])
 def test_source_gap_is_distinct(self):
  self.assertEqual(m.classify({"archive_gap":True})["kind"],"SOURCE_DOCUMENT_UNAVAILABLE")
 def test_ambiguous_blocks_imputation(self):
  self.assertEqual(m.classify({"DEBT_EQUITY_RATIO__status":"AMBIGUOUS_MULTIPLE_CANDIDATES"})["kind"],"AMBIGUOUS_FACTS")
 def test_unmapped_distinct(self):
  self.assertEqual(m.classify({"DEBT_EQUITY_RATIO__status":"NOT_MAPPED_FOR_DOMAIN"})["kind"],"MAPPING_NOT_AVAILABLE")
 def test_report_counts(self):
  r=m.summarize([{"DEBT_EQUITY_RATIO__status":"SELECTED","DEBT_EQUITY_RATIO__value":"1"},{"DEBT_EQUITY_RATIO__status":"MISSING"}])
  self.assertEqual(r["statuses"],{"AVAILABLE":1,"NO_ELIGIBLE_FACT":1})
if __name__=="__main__":unittest.main()
