import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/".ci/native140"))
from live_decision_v1 import route,interpret

def fundamentals():
 return {"available":True,"point_in_time_safe":True,"growth":{"revenue_yoy_symmetric_pct":10,"pat_yoy_symmetric_pct":10,"eps_yoy_symmetric_pct":10},"profitability":{"pat_margin_pct":12},"risk_event":{"available":True,"event_profile":"PURE_IMPROVEMENT"},"balance_sheet":{"debt_equity_ratio":0.2},"cash_flow":{"latest_operating_cash_flow":25,"ocf_yoy_symmetric_pct":12},"valuation":{"implied_pe_from_ttm_eps":10,"pit_historical_pe_reference":15,"pit_comparison_available":True}}
def technical():
 return {"status":"READY","trend":{"close":110,"ema50":100,"ema50_slope_5d_pct":1},"momentum":{"roc20_pct":5,"macd_hist":1},"relative_strength":{"rs20_vs_nifty":2},"volume_flow":{"cmf20":0.2},"volatility":{"atr_pct":3},"multi_timeframe":{"weekly_trend_confirmed":True},"market_context":{"nifty_regime":"BULL"}}
def evaluate(t=None,p=None,current=True,f=None):
 return route("TEST","2026-10-16",t if t is not None else technical(),f if f is not None else fundamentals(),price_context=p if p is not None else {"prior_support":90,"drawdown_from_126_high_pct":-5},official_current=current)
class BatchTests(unittest.TestCase):
 def test_valid_buy_unchanged(self):
  self.assertEqual(evaluate()["final_action"],"MOMENTUM BUY")
  self.assertTrue(evaluate()["executable"])
 def test_truthy_current_flags_cannot_buy(self):
  for flag in ("False","True",1,None):
   with self.subTest(flag=flag):
    r=evaluate(current=flag)
    self.assertFalse(r["executable"])
    self.assertNotIn(r["final_action"],("MOMENTUM BUY","RECOVERY BUY","MOMENTUM + RECOVERY BUY"))
 def test_strong_event_string_not_deterioration(self):
  f=fundamentals();f["risk_event"]["strong_deterioration_transition"]="False"
  self.assertFalse(interpret(f)["structural_deterioration"])
 def test_event_availability_string_not_accepted(self):
  f=fundamentals();f["risk_event"]["available"]="False"
  self.assertEqual(interpret(f)["fundamental_event_state"],"UNAVAILABLE")
 def test_negative_atr_blocks_buy(self):
  t=technical();t["volatility"]["atr_pct"]=-2
  self.assertNotIn(evaluate(t=t)["final_action"],("MOMENTUM BUY","RECOVERY BUY","MOMENTUM + RECOVERY BUY"))
 def test_impossible_drawdown_does_not_trigger_recovery(self):
  t=technical();t["momentum"]["roc20_pct"]=-2
  r=evaluate(t=t,p={"prior_support":90,"drawdown_from_126_high_pct":-150})
  self.assertNotEqual(r["price_condition"],"DEPRESSED")
 def test_negative_close_not_stabilising(self):
  t=technical();t["trend"]["close"]=-1;t["momentum"]["roc20_pct"]=0
  self.assertNotEqual(evaluate(t=t)["technical_state"],"STABILISING")
 def test_zero_ema_not_extended(self):
  t=technical();t["trend"]["ema50"]=0
  self.assertNotEqual(evaluate(t=t)["price_condition"],"EXTENDED")
if __name__=="__main__":unittest.main()
