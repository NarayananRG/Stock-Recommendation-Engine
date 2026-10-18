import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/".ci/native140"))
from live_decision_v1 import paper_entry_rows,monitor,rank_candidates

class SafetyBatchTests(unittest.TestCase):
 def entry(self,shares):
  rows=[{"symbol":"TEST","live_decision":{"executable":True,"final_action":"MOMENTUM BUY"}}]
  return paper_entry_rows(rows,{"new_buys":[{"symbol":"TEST","shares":shares}]})[0]["executable"]
 def test_valid_whole_quantities(self):
  self.assertTrue(self.entry(5))
  self.assertTrue(self.entry("5"))
 def test_invalid_quantities_not_executable(self):
  for x in (True,False,-1,0,0.1,1.5,"1.2","bad",None,float("nan"),float("inf")):
   with self.subTest(x=x):self.assertFalse(self.entry(x))
 def test_false_string_not_deterioration_exit(self):
  position={"primary_style":"MOMENTUM","sessions_held":0}
  decision={"structural_deterioration":"False","technical_state":"STRONG","momentum_thesis":"VALID"}
  self.assertEqual(monitor(position,decision)[0],"HOLD")
 def test_true_deterioration_exits(self):
  self.assertEqual(monitor({"primary_style":"MOMENTUM"},{"structural_deterioration":True})[0],"EXIT")
 def test_nonbuy_row_not_executable_despite_allocation(self):
  rows=[{"symbol":"T","live_decision":{"executable":True,"final_action":"WATCH - MOMENTUM"}}]
  self.assertFalse(paper_entry_rows(rows,{"new_buys":[{"symbol":"T","shares":2}]})[0]["executable"])
if __name__=="__main__":unittest.main()
