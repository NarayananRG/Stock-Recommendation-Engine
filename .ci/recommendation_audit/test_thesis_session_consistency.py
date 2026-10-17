"""Batch regression of weekly signal and official-session presentation consistency."""
import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/".ci/native140"))
from live_decision_v1 import route

def fundamentals():
 return {"available":True,"point_in_time_safe":True,"growth":{"revenue_yoy_symmetric_pct":12,"pat_yoy_symmetric_pct":11,"eps_yoy_symmetric_pct":10},"profitability":{"pat_margin_pct":13},"risk_event":{"available":True,"event_profile":"PURE_IMPROVEMENT"},"balance_sheet":{"debt_equity_ratio":0.2},"cash_flow":{"latest_operating_cash_flow":20,"ocf_yoy_symmetric_pct":8},"valuation":{"implied_pe_from_ttm_eps":9,"pit_historical_pe_reference":15,"pit_comparison_available":True}}
def technical():
 return {"status":"READY","trend":{"close":110,"ema50":100,"ema50_slope_5d_pct":1},"momentum":{"roc20_pct":4,"macd_hist":1},"relative_strength":{"rs20_vs_nifty":1},"volume_flow":{"cmf20":0.1},"multi_timeframe":{"weekly_trend_confirmed":True},"volatility":{"atr_pct":3},"market_context":{"nifty_regime":"BULL"}}
def check(t=None,current=True,price=None):
 return route("TEST","2026-10-16",technical() if t is None else t,fundamentals(),price_context={"prior_support":90,"drawdown_from_126_high_pct":-5} if price is None else price,official_current=current)

class Tests(unittest.TestCase):
 def test_valid_current_momentum(self):
  d=check()
  self.assertEqual(d["momentum_thesis"],"VALID")
  self.assertEqual(d["final_action"],"MOMENTUM BUY")
 def test_stale_session_blocks_valid_thesis_label(self):
  d=check(current=False)
  self.assertNotEqual(d["momentum_thesis"],"VALID")
  self.assertFalse(d["executable"])
  self.assertIn("OFFICIAL_SESSION_NOT_CURRENT",d["reason_codes"])
 def test_stale_recovery_not_valid(self):
  t=technical();t["momentum"]["roc20_pct"]=-2
  d=check(t,current=False,price={"prior_support":90,"drawdown_from_126_high_pct":-20})
  self.assertNotEqual(d["recovery_thesis"],"VALID")
  self.assertFalse(d["executable"])
 def test_truthy_weekly_not_confirmed(self):
  for flag in ("True",1,None,False):
   t=technical();t["multi_timeframe"]["weekly_trend_confirmed"]=flag
   d=check(t)
   self.assertNotEqual(d["technical_state"],"STRONG")
   self.assertIn("WEEKLY_CONFIRMATION_MISSING_OR_FALSE",d["reason_codes"])
 def test_completed_weekly_remains_strong(self):
  self.assertEqual(check()["technical_state"],"STRONG")
if __name__=="__main__":unittest.main()
