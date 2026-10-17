import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/".ci/native140"))
from live_decision_v1 import paper_entry_rows,rank_candidates

def row(symbol,action="MOMENTUM BUY",executable=True,thesis="VALID",confidence="MEDIUM"):
 return {"symbol":symbol,"live_decision":{"final_action":action,"executable":executable,"momentum_thesis":thesis,"recovery_thesis":"WATCH","confidence":confidence,"business_health":"HEALTHY","evidence":{"technical":{"volatility":{"atr_pct":3},"relative_strength":{"rs20_vs_nifty":2},"momentum":{"adx14":30}}}}}
class BatchTests(unittest.TestCase):
 def test_bad_plan_shape_fails_closed(self):
  for plan in ({"new_buys":None},{"new_buys":"bad"},{"new_buys":{}}):
   self.assertFalse(paper_entry_rows([row("X")],plan)[0]["executable"])
 def test_nonstring_symbol_order_ignored(self):
  self.assertFalse(paper_entry_rows([row("X")],{"new_buys":[{"symbol":True,"shares":2}]})[0]["executable"])
 def test_rank_valid_buy_first(self):
  ranked=rank_candidates([row("WATCH","WATCH - MOMENTUM",False,"VALID","HIGH"),row("BUY")])
  self.assertEqual(ranked[0]["symbol"],"BUY")
  self.assertEqual(ranked[0]["live_decision"]["lane_ranks"]["MOMENTUM"],1)
  self.assertEqual(ranked[1]["live_decision"]["lane_ranks"],{})
 def test_unknown_confidence_does_not_crash(self):
  ranked=rank_candidates([row("A",confidence="UNKNOWN"),row("B")])
  self.assertEqual(ranked[0]["symbol"],"B")
 def test_missing_business_state_does_not_crash(self):
  x=row("A");x["live_decision"].pop("business_health")
  self.assertEqual(rank_candidates([x])[0]["rank"],1)
if __name__=="__main__":unittest.main()
