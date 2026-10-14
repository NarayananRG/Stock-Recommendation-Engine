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
        replanned=record_daily_observation(db,**{**args,'recommendations':[{**r,'executable':False} for r in self.rows],'capital_plan':dict(new_buys=[])})
        self.assertTrue(replanned['duplicate'])
        self.assertEqual(replanned['event_id'],first['event_id'])
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
        marked=load_portfolio(db,state['portfolio_id'])
        self.assertEqual(marked['valuation_quality'],'CURRENT_OFFICIAL_MARKS')
        self.assertLess(marked['nav'],100000)  # slippage and transaction costs remain real simulation costs

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
        ctx.data_source_status=lambda:dict(mode='REAL_OFFICIAL_DATA',active=dict(members=[dict(symbol='M')]))
        t,f=fixtures.evidence(True)
        ctx.technical_v2_context=lambda *a:t
        ctx.fundamental_v3_context=lambda *a:dict(f)
        data=dict(run=dict(run_id='IMMUTABLE',market_session='2026-10-13'),candidates=[dict(self.rows[0])])
        first=ctx._materialize_live_run(data)
        t['trend']['close']=1
        second=ctx._materialize_live_run(data)
        self.assertEqual(first,second)
        self.assertEqual(len(second['candidates']),1)
        t['trend']['close']=100
        data['run']['run_id']='NO_LEGACY_ANALOGUES'
        data['candidates']=[]
        independent=ctx._materialize_live_run(data)
        self.assertEqual(independent['candidates'][0]['live_decision']['final_action'],'MOMENTUM + RECOVERY BUY')
        from modern_ui.api import APP_VERSION
        ctx._active_run_metadata=lambda:dict(app_version=APP_VERSION)
        ctx._saved_active_run_id=lambda:'UNFINISHED_RUN'
        self.assertIsNone(ctx.active_prediction_run())

    def test_upgrade_recomputes_once_then_daily_run_is_idempotent(self):
        from modern_ui.api import ModernAppContext,APP_VERSION
        from types import SimpleNamespace
        ctx=ModernAppContext.__new__(ModernAppContext)
        saved=dict(last_successful_run=dict(market_session='2026-10-13',model_version='0.13.5-phase8-paper-journal-hotfix'))
        calls=[]
        ctx._daily_data_gate=lambda:dict(ready=True,target_session='2026-10-13',latest_official_session='2026-10-13',source=dict(mode='REAL_OFFICIAL_DATA'))
        ctx._read_daily_state=lambda:saved
        ctx._write_daily_state=lambda data:saved.update(data)
        ctx.post_close_daily_status=lambda:{}
        ctx.active_target_state=lambda:dict(explicit=False)
        def ensure(*args):
            calls.append(args)
            return dict(run=dict(run_id='NEW')),False
        ctx.ensure_analysis_run=ensure
        ctx.latest_prediction_rows=lambda **kw:self.rows
        ctx.ui_run_input=lambda:dict(run_id='NEW')
        ctx.prices=SimpleNamespace(history=lambda *a,**kw:[])
        ctx.technical_v2_context=lambda *a:{}
        ctx.fundamental_v3_context=lambda *a:{}
        ctx.combined_v2_context=lambda *a:{}
        ctx.monitoring=SimpleNamespace(run_daily_monitoring=lambda *a:None)
        ctx.phase81_paper_status=lambda:dict(active=False)
        first=ctx.run_post_close_daily_flow()
        self.assertFalse(first['duplicate'])
        self.assertEqual(saved['last_successful_run']['model_version'],APP_VERSION)
        self.assertTrue(ctx.run_post_close_daily_flow()['duplicate'])
        self.assertEqual(len(calls),1)

    def test_today_uses_current_original_thesis_and_blocks_stale_hold(self):
        import sqlite3
        from types import SimpleNamespace
        from modern_ui.api import ModernAppContext
        from stock_app.phase81_validation import _ClosingConnection
        db=self.root/'today.sqlite3'
        original=self.rows[1]['live_decision']
        with sqlite3.connect(db,factory=_ClosingConnection) as con:
            con.execute('create table live_position_theses (position_id integer primary key, thesis_json text not null)')
            con.execute('insert into live_position_theses values (?,?)',(1,json.dumps(original)))
        ctx=ModernAppContext.__new__(ModernAppContext)
        ctx.db=SimpleNamespace(connect=lambda:sqlite3.connect(db,factory=_ClosingConnection))
        ctx.monitoring=SimpleNamespace(summary=lambda:dict(actions=[dict(position_id=1,symbol='R',action='EXIT')]))
        ctx.portfolio=SimpleNamespace(list_positions=lambda:[dict(id=1,symbol='R',buy_date='2026-10-12')])
        ctx.prices=SimpleNamespace(history=lambda *a,**kw:[dict(date='2026-10-13')])
        ctx.phase81_paper_status=lambda:dict(positions=[])
        ctx.latest_prediction_rows=lambda *a:self.rows
        ctx.active_prediction_run=lambda:dict(run=dict(market_session='2026-10-13'))
        ctx._daily_data_gate=lambda:dict(ready=True,target_session='2026-10-14')
        ctx.expected_market_session=lambda:dict(expected_market_session='2026-10-14')
        ctx.data_source_status=lambda:dict(mode='REAL_OFFICIAL_DATA',active=dict(latest_session='2026-10-14'))
        summary=ctx.live_today_summary()
        self.assertEqual(summary['actions'][0]['action'],'WEAKENING')
        self.assertEqual(summary['health_counts']['WEAKENING'],1)
        ctx._daily_data_gate=lambda:dict(ready=True,target_session='2026-10-13')
        ctx.expected_market_session=lambda:dict(expected_market_session='2026-10-13')
        ctx.data_source_status=lambda:dict(mode='REAL_OFFICIAL_DATA',active=dict(latest_session='2026-10-13'))
        self.assertEqual(ctx.live_today_summary()['actions'][0]['action'],'HOLD')


if __name__=='__main__':unittest.main()
