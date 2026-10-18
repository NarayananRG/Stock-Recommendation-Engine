import csv,importlib.util,tempfile,unittest
from pathlib import Path
s=Path(__file__).with_name("ingest_v2_local_comparison.py")
spec=importlib.util.spec_from_file_location("evidence_ingest",s)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class EvidenceTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
  self.p=Path(self.t.name)/"real_report.csv"
 def write(self,rows):
  with self.p.open("w",newline="") as h:
   w=csv.DictWriter(h,fieldnames=["symbol","before_action","after_action"]);w.writeheader();w.writerows(rows)
 def test_measured_delta(self):
  self.write([{"symbol":"AAA.NS","before_action":"WATCH - RECOVERY","after_action":"NO OPPORTUNITY"},
              {"symbol":"BBB","before_action":"RECOVERY BUY","after_action":"RECOVERY BUY"}])
  r=m.ingest(self.p,2)
  self.assertEqual(r["changed_action_count"],1)
  self.assertEqual(r["action_label_buy_counts"],{"before":1,"after":1})
  self.assertIsNone(r["verified_executable_buy_count"])
  self.assertFalse(r["historical_forward_returns_validated"])
  self.assertEqual(len(r["source_sha256"]),64)
 def test_duplicate_normalized_symbols_rejected(self):
  self.write([{"symbol":"AAA.NS","before_action":"WATCH","after_action":"WATCH"},
              {"symbol":"AAA","before_action":"WATCH","after_action":"WATCH"}])
  with self.assertRaisesRegex(ValueError,"DUPLICATE"):m.ingest(self.p,2)
 def test_missing_values_rejected(self):
  self.write([{"symbol":"AAA","before_action":"","after_action":"WATCH"}])
  with self.assertRaisesRegex(ValueError,"MISSING_ACTION"):m.ingest(self.p,1)
 def test_incomplete_universe_rejected(self):
  self.write([{"symbol":"AAA","before_action":"WATCH","after_action":"WATCH"}])
  with self.assertRaisesRegex(ValueError,"UNEXPECTED_UNIVERSE"):m.ingest(self.p)
 def test_missing_source_is_error(self):
  with self.assertRaises(FileNotFoundError):m.ingest(Path(self.t.name)/"missing.csv")
if __name__=="__main__":unittest.main()
