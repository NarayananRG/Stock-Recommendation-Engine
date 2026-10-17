import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/".ci/native140"))
from live_decision_v1 import route
def f():
 return {"available":True,"point_in_time_safe":True,"growth":{"revenue_yoy_symmetric_pct":10,"pat_yoy_symmetric_pct":10,"eps_yoy_symmetric_pct":10},"profitability":{"pat_margin_pct":12},"risk_event":{"available":True,"event_profile":"PURE_IMPROVEMENT"},"cash_flow":{"latest_operating_cash_flow":25,"ocf_yoy_symmetric_pct":12},"balance_sheet":{"debt_equity_ratio":0.2}}
def t():
 return {"status":"READY","trend":{"close":110,"ema50":100,"ema50_slope_5d_pct":1},"momentum":{"roc20_pct":5,"macd_hist":1},"relative_strength":{"rs20_vs_nifty":2},"volume_flow":{"cmf20":0.2},"multi_timeframe":{"weekly_trend_confirmed":True},"volatility":{"atr_pct":3},"market_context":{"nifty_regime":"BULL"}}
def r(data):
 return route("X","2026-10-16",data,f(),price_context={"prior_support":90,"drawdown_from_126_high_pct":-5},official_current=True)
class Tests(unittest.TestCase):
 def test_baseline_still_momentum_buy(self):
  self.assertEqual(r(t())["final_action"],"MOMENTUM BUY")
 def test_weekly_absent_explained(self):
  d=t();d["multi_timeframe"].pop("weekly_trend_confirmed")
  out=r(d);self.assertIn("WEEKLY_CONFIRMATION_MISSING_OR_FALSE",out["reason_codes"]);self.assertNotEqual(out["final_action"],"MOMENTUM BUY")
 def test_not_ready_explained(self):
  d=t();d["status"]="INSUFFICIENT_DATA"
  out=r(d);self.assertIn("TECHNICAL_DATA_NOT_READY",out["reason_codes"])
 def test_invalid_cmf_rejected(self):
  d=t();d["volume_flow"]["cmf20"]=1.5
  out=r(d);self.assertIn("CMF_MISSING_OR_INVALID",out["reason_codes"]);self.assertNotEqual(out["technical_state"],"STRONG")
 def test_invalid_roc_rejected(self):
  d=t();d["momentum"]["roc20_pct"]=-200
  out=r(d);self.assertIn("ROC_MISSING_OR_INVALID",out["reason_codes"])
 def test_cmf_negative_one_valid(self):
  d=t();d["volume_flow"]["cmf20"]=-1
  self.assertNotIn("CMF_MISSING_OR_INVALID",r(d)["reason_codes"])
if __name__=="__main__":unittest.main()
