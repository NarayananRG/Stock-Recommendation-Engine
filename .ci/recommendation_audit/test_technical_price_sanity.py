import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/".ci/native140"))
from live_decision_v1 import route

def tech(close,ema=100):
 return {"status":"READY","trend":{"close":close,"ema50":ema,"ema50_slope_5d_pct":1},"momentum":{"roc20_pct":-11,"macd_hist":1},"relative_strength":{"rs20_vs_nifty":1},"volume_flow":{"cmf20":0.1},"multi_timeframe":{"weekly_trend_confirmed":True},"volatility":{"atr_pct":3},"market_context":{"nifty_regime":"BULL"}}
def fundamental():
 return {"available":True,"point_in_time_safe":True,"growth":{"revenue_yoy_symmetric_pct":10,"pat_yoy_symmetric_pct":10,"eps_yoy_symmetric_pct":10},"profitability":{"pat_margin_pct":10},"risk_event":{"available":True,"event_profile":"PURE_IMPROVEMENT"},"cash_flow":{"latest_operating_cash_flow":10,"ocf_yoy_symmetric_pct":5},"balance_sheet":{"debt_equity_ratio":0.3}}
class T(unittest.TestCase):
 def call(self,close,ema,support):
  return route("SAMPLE","2026-10-16",tech(close,ema),fundamental(),price_context={"prior_support":support,"drawdown_from_126_high_pct":-18},official_current=True)
 def test_zero_price_not_breakdown(self):
  r=self.call(0,100,100)
  self.assertNotEqual(r["technical_state"],"BREAKDOWN")
  self.assertFalse(r["executable"])
 def test_negative_price_not_breakdown(self):
  r=self.call(-5,100,100)
  self.assertNotEqual(r["technical_state"],"BREAKDOWN")
  self.assertFalse(r["executable"])
 def test_genuine_breakdown_still_detected(self):
  self.assertEqual(self.call(90,100,100)["technical_state"],"BREAKDOWN")
 def test_nonpositive_ema_not_strong(self):
  r=self.call(110,0,100)
  self.assertNotEqual(r["technical_state"],"STRONG")
 def test_zero_support_not_breakdown(self):
  self.assertNotEqual(self.call(90,100,0)["technical_state"],"BREAKDOWN")
if __name__=="__main__":unittest.main()
