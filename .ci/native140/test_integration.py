import os
from pathlib import Path
import sys
import tempfile
import unittest
import json
import importlib.util

sys.path.insert(0, os.environ['SRE_ENGINE_ROOT'])
spec=importlib.util.spec_from_file_location('fixtures',Path(__file__).with_name('test_live_decision_v1.py'))
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
from stock_app.live_decision_v1 import route,rank_candidates
from stock_app.allocation import PortfolioAllocator,AllocationRequest,is_executable_decision
from stock_app.phase81_validation import create_portfolio,record_daily_observation,apply_open_fills,load_portfolio,mark_daily_hold_exit


def row(symbol,strong,depressed):
    t,f=fixtures.evidence(strong)
    live=route(symbol,'2026-10-13',t,f,price_context=dict(prior_support=98,drawdown_from_126_high_pct=-25 if depressed else -5),official_current=True)
    return dict(symbol=symbol,rank=1,latest_close=100,opportunity_status=live['final_action'],expected_return=.10,
                confidence_label=live['confidence'],executable=live['executable'],live_decision=live,**{k:live[k] for k in ('strategy_style','primary_style','momentum_thesis','recovery_thesis','business_health','technical_state')})


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(os.environ['SRE_ENGINE_ROOT']).parent)
        self.root=Path(self.temp.name)
        self.allocator=PortfolioAllocator(self.root,portfolio=None)
        self.rows=[row('M',True,False),row('R',False,True),row('B',True,True)]
        for n,r in enumerate(self.rows,1):r['rank']=n

    def tearDown(self):self.temp.cleanup()

    def test_capital_consumes_all_lanes(self):
        inputs=self.allocator.candidates_from_latest_run(dict(candidates=self.rows))
        plan=self.allocator.allocate(AllocationRequest(100000,20,None),inputs,[])
        self.assertEqual({b['symbol'] for b in plan['new_buys']},{'M','R','B'})
        self.assertEqual(len(plan['new_buys']),3)
        self.assertLessEqual(plan['capital_summary']['estimated_spend'],100000)
        self.assertFalse(is_executable_decision('WATCH - RECOVERY'))

    def test_lane_ranking_and_symbol_deduplication(self):
        ranked=rank_candidates(self.rows)
        both=next(r for r in ranked if r['symbol']=='B')['live_decision']
        self.assertEqual(set(both['lane_ranks']),{'MOMENTUM','RECOVERY'})
        inputs=self.allocator.candidates_from_latest_run(dict(candidates=self.rows+[self.rows[-1]]))
        self.assertEqual(len(inputs),3)

    def test_paper_both_lanes_idempotent_next_open(self):
        db=self.root/'paper.sqlite3'
        state=create_portfolio(db,starting_session='2026-10-13',starting_capital=100000)
        plan=dict(new_buys=[dict(symbol=r['symbol'],estimated_cost=20000) for r in self.rows])
        args=dict(portfolio_id=state['portfolio_id'],market_session='2026-10-13',production_run_id='RUN',recommendations=self.rows,capital_plan=plan)
        first=record_daily_observation(db,**args)
        again=record_daily_observation(db,**args)
        self.assertEqual(len(first['orders']),3)
        self.assertTrue(again['duplicate'])
        self.assertEqual(apply_open_fills(db,portfolio_id=state['portfolio_id'],fill_session='2026-10-13',open_prices=dict(M=100,R=100,B=100)),[])
        fills=apply_open_fills(db,portfolio_id=state['portfolio_id'],fill_session='2026-10-14',open_prices=dict(M=100,R=100,B=100))
        self.assertEqual(len(fills),3)
        self.assertEqual(apply_open_fills(db,portfolio_id=state['portfolio_id'],fill_session='2026-10-14',open_prices=dict(M=100,R=100,B=100)),[])
        result=load_portfolio(db,state['portfolio_id'])
        self.assertEqual(len(result['positions']),3)
        self.assertEqual({p['strategy_style'] for p in result['positions']},{'MOMENTUM BUY','RECOVERY BUY','MOMENTUM + RECOVERY BUY'})
        self.assertGreaterEqual(result['cash'],0)
        events=mark_daily_hold_exit(db,portfolio_id=state['portfolio_id'],market_session='2026-10-14',production_run_id='RUN2',recommendations=self.rows)
        self.assertEqual({e['event_type'] for e in events},{'HELD'})

    def test_paper_watch_never_bought(self):
        db=self.root/'paper.sqlite3'
        state=create_portfolio(db,starting_session='2026-10-13',starting_capital=100000)
        candidate=dict(symbol='W',opportunity_status='WATCH - RECOVERY',executable=False)
        event=record_daily_observation(db,portfolio_id=state['portfolio_id'],market_session='2026-10-13',production_run_id='RUN',recommendations=[candidate],capital_plan=dict(new_buys=[dict(symbol='W',estimated_cost=20000)]))
        self.assertEqual(event['orders'],[])

    def test_materialized_run_is_immutable(self):
        from modern_ui.api import ModernAppContext
        from types import SimpleNamespace
        ctx=ModernAppContext.__new__(ModernAppContext)
        ctx.config=SimpleNamespace(app_data_dir=self.root)
        bars=[dict(date='2026-10-13',close=100,high=130,low=98,open=100,volume=1000)]*126
        ctx.prices=SimpleNamespace(history=lambda *a,**k:bars)
        ctx._daily_data_gate=lambda:dict(ready=True,target_session='2026-10-13')
        t,f=fixtures.evidence(True)
        ctx.technical_v2_context=lambda *a:t
        ctx.fundamental_v3_context=lambda *a:dict(f)
        data=dict(run=dict(run_id='IMMUTABLE',market_session='2026-10-13'),candidates=[dict(self.rows[0])])
        first=ctx._materialize_live_run(data)
        t['trend']['close']=1
        second=ctx._materialize_live_run(data)
        self.assertEqual(first,second)
        self.assertEqual(len(second['candidates']),1)


if __name__=='__main__':unittest.main()
