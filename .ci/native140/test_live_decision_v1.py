import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('live', Path(__file__).with_name('live_decision_v1.py'))
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


def evidence(strong=False):
    f = dict(available=True, point_in_time_safe=True, filing_freshness='CURRENT_FOR_DECISION_TIME',
             growth=dict(revenue_yoy_symmetric_pct=3, pat_yoy_symmetric_pct=6, eps_yoy_symmetric_pct=6),
             profitability=dict(pat_margin_pct=15), cash_flow=dict(latest_operating_cash_flow=100, ocf_yoy_symmetric_pct=10),
             balance_sheet=dict(debt_equity_ratio=.5), risk_event=dict(available=True, event_profile='NO_DIRECTIONAL_EVIDENCE'),
             valuation=dict(implied_pe_from_ttm_eps=16, pit_comparison_available=True, pit_historical_pe_reference=24))
    t = dict(status='READY', trend=dict(close=100, ema50=90 if strong else 110, ema50_slope_5d_pct=2 if strong else -2),
             momentum=dict(roc20_pct=10 if strong else -8, macd_hist=1 if strong else -1, rsi14=55 if strong else 35),
             relative_strength=dict(rs20_vs_nifty=3 if strong else -3), volume_flow=dict(cmf20=.1),
             multi_timeframe=dict(weekly_trend_confirmed=strong), volatility=dict(atr_pct=3),
             market_context=dict(nifty_regime='BULL'))
    return t, f


def run(t, f, depressed=False, current=True):
    return live.route('TEST', '2026-10-13', t, f, price_context=dict(prior_support=98,
                       drawdown_from_126_high_pct=-25 if depressed else -5), official_current=current)


class RouterTests(unittest.TestCase):
    def test_momentum(self):
        t,f = evidence(True)
        self.assertEqual(run(t,f)['final_action'], 'MOMENTUM BUY')

    def test_severe_deterioration_veto(self):
        t,f = evidence(True)
        f['growth'].update(revenue_yoy_symmetric_pct=-30,pat_yoy_symmetric_pct=-40)
        row = run(t,f)
        self.assertEqual(row['final_action'], 'AVOID - FUNDAMENTAL DETERIORATION')
        self.assertFalse(row['executable'])

    def test_recovery_with_weak_trend(self):
        t,f = evidence()
        row = run(t,f,True)
        self.assertEqual(row['final_action'], 'RECOVERY BUY')
        self.assertEqual(row['technical_state'], 'WEAK')
        self.assertTrue(row['executable'])

    def test_falling_knife(self):
        t,f = evidence()
        f['growth'].update(revenue_yoy_symmetric_pct=-30,pat_yoy_symmetric_pct=-40)
        f['cash_flow']['latest_operating_cash_flow']=-100
        self.assertEqual(run(t,f,True)['final_action'], 'AVOID - VALUE TRAP RISK')

    def test_both_once(self):
        t,f = evidence(True)
        row = run(t,f,True)
        self.assertEqual(row['final_action'], 'MOMENTUM + RECOVERY BUY')
        self.assertEqual(live.lane_counts([row])['both'],1)

    def test_missing_fundamentals(self):
        t,_ = evidence()
        row = run(t,{},True)
        self.assertEqual(row['final_action'],'WATCH - RECOVERY')
        self.assertFalse(row['executable'])
        self.assertEqual(row['business_health'],'UNAVAILABLE')

    def test_target_not_an_input(self):
        t,f = evidence()
        rows=[]
        for target in (5,10,20):
            legacy = dict(target_return=target)
            row=live.route('TEST','2026-10-13',t,f,price_context=dict(prior_support=98,drawdown_from_126_high_pct=-25),official_current=True,legacy=legacy)
            rows.append(row['final_action'])
            self.assertFalse(row['target_used_in_score'])
        self.assertEqual(len(set(rows)),1)

    def test_stale_official_blocks(self):
        t,f=evidence(True)
        self.assertFalse(run(t,f,current=False)['executable'])

    def test_stale_filings_block(self):
        t,f=evidence()
        f['filing_freshness']='STALE'
        self.assertEqual(run(t,f,True)['final_action'],'WATCH - RECOVERY')

    def test_bank_semantics(self):
        t,f=evidence()
        f['sector_profile']='FINANCIAL_DOMAIN_CONSERVATIVE'
        f['balance_sheet']['debt_equity_ratio']=10
        f['cash_flow']['latest_operating_cash_flow']=-100
        row=run(t,f,True)
        self.assertEqual(row['balance_sheet_state'],'UNAVAILABLE')
        self.assertEqual(row['final_action'],'WATCH - RECOVERY')

    def test_no_unsupported_valuation(self):
        t,f=evidence()
        f['valuation']['pit_comparison_available']=False
        self.assertEqual(run(t,f,True)['valuation_state'],'UNAVAILABLE')
        self.assertFalse(run(t,f,True)['executable'])

    def test_breakdown_is_distinct_from_weak(self):
        t,f=evidence()
        t['trend']['close']=80
        t['momentum']['roc20_pct']=-20
        self.assertEqual(run(t,f,True)['final_action'],'AVOID - TECHNICAL BREAKDOWN')

    def test_recovery_monitor_preserves_style(self):
        t,f=evidence()
        row=run(t,f,True)
        self.assertEqual(live.monitor(dict(primary_style='RECOVERY'),row)[0],'HOLD')
        row['structural_deterioration']=True
        self.assertEqual(live.monitor(dict(primary_style='RECOVERY'),row)[0],'EXIT')

    def test_no_price_decline_only_buy(self):
        t,f=evidence()
        f['growth']['pat_yoy_symmetric_pct']=-15
        self.assertFalse(run(t,f,True)['executable'])


if __name__ == '__main__': unittest.main()
