import importlib.util
from pathlib import Path
import pytest
p=Path(__file__).resolve().parents[1]/'FOLLOW_UP_FORECASTS.py';s=importlib.util.spec_from_file_location('followup',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def test_announced_muhurat_counts_toward_twenty_sessions():
 ds=m.scheduled('2026-10-16',20);assert ds[-1]=='2026-11-16' and '2026-11-08'in ds and '2026-11-10'not in ds and '2026-10-20'not in ds
def test_correct_capital_market_calendar_not_settlement_only():
 for d in ['2026-02-19','2026-03-19','2026-04-01','2026-08-26']:assert d not in m.HOLIDAYS
def test_no_forecast_before_maturity():assert m.outcome({}, {},'2026-10-16',20,'2026-10-31')==(None,'IMMATURE')
def test_missing_session_never_shortens_horizon():
 ds=m.scheduled('2026-10-16',20);idx={d:{'Open':100,'Close':100}for d in ds};bs={**idx,'2026-10-16':{'Open':100,'Close':100}};del bs['2026-10-21']
 assert m.outcome(bs,idx,'2026-10-16',20,'2026-11-16')==(None,'MISSING_FORWARD_STOCK_SESSION')
def test_costs_entry_and_terminal_definition():
 ds=m.scheduled('2026-10-16',20);idx={d:{'Open':100,'Close':110}for d in ds};bs={**idx,'2026-10-16':{'Open':100,'Close':105}}
 r,e=m.outcome(bs,idx,'2026-10-16',20,'2026-11-16');assert not e
 assert r['gross_return']==pytest.approx(.1);assert r['hypothetical_round_trip_net_return']==pytest.approx(109.835/100.15-1);assert r['close_to_close_return']==pytest.approx(110/105-1)
def test_no_unknown_calendar_year_fabrication():
 with pytest.raises(ValueError,match='CALENDAR_YEAR_NOT_SUPPORTED'):m.scheduled('2026-12-31',20)
def test_end_to_end_is_read_only_and_reports_mature_forecast(tmp_path):
 import sqlite3,hashlib,json,csv
 app=tmp_path/'app';app.mkdir();prices=app/'prices';prices.mkdir();db=app/'observations.sqlite3'
 with sqlite3.connect(db)as c:
  c.executescript('create table prediction_runs(run_id text,market_session text,horizon_sessions int,model_version text,feature_contract_version text,training_cutoff text,created_at text);create table prediction_candidates(id int,run_id text,symbol text,expected_return real,latest_close real);')
  c.execute("insert into prediction_runs values('r','2026-01-02',5,'m','f','2026-01-02','2026-01-02 18:00:00')");c.execute("insert into prediction_candidates values(1,'r','AAA',.05,100)")
 dates=['2026-01-02']+m.scheduled('2026-01-02',5)
 for name in ['AAA.NS.csv','INDEX_NSEI.csv']:
  with (prices/name).open('w',newline='')as h:
   w=csv.writer(h);w.writerow(['Date','Open','Close']);w.writerows([[d,100,100 if d==dates[0]else 110]for d in dates])
 before=hashlib.sha256(db.read_bytes()).hexdigest();folder=m.evaluate(db,prices,tmp_path/'output');r=json.loads((folder/'SUMMARY.json').read_text())
 assert r['mature_evaluable']==1 and r['recorded_before_entry_open']==1 and r['by_horizon']['5']['mae']==pytest.approx(.05)
 assert hashlib.sha256(db.read_bytes()).hexdigest()==before
 with pytest.raises(ValueError,match='OUTSIDE_SRE'):m.evaluate(db,prices,app/'bad-output')
 (app/'observations.sqlite3-wal').write_bytes(b'nonempty')
 with pytest.raises(ValueError,match='CONSISTENT_BACKUP'):m.evaluate(db,prices,tmp_path/'elsewhere')
def test_duplicate_session_rejected(tmp_path):
 p=tmp_path/'p.csv';p.write_text('Date,Open,Close\n2026-01-02,100,100\n2026-01-02,100,110\n')
 with pytest.raises(ValueError,match='DUPLICATE'):m.readbars(p)
def test_nonfinite_price_rejected(tmp_path):
 p=tmp_path/'p.csv';p.write_text('Date,Open,Close\n2026-01-02,100,nan\n')
 with pytest.raises(ValueError,match='INVALID'):m.readbars(p)
