"""Free offline forecast outcome ledger. Standard library; never writes SRE data."""
from pathlib import Path
from datetime import date,datetime,timedelta,timezone
import argparse,collections,csv,json,sqlite3,math,hashlib
HOLIDAYS=set('2025-02-26 2025-03-14 2025-03-31 2025-04-10 2025-04-14 2025-04-18 2025-05-01 2025-08-15 2025-08-27 2025-10-02 2025-10-22 2025-11-05 2025-12-25 2026-01-15 2026-01-26 2026-03-03 2026-03-26 2026-03-31 2026-04-03 2026-04-14 2026-05-01 2026-05-28 2026-06-26 2026-09-14 2026-10-02 2026-10-20 2026-11-10 2026-11-24 2026-12-25'.split())
SPECIAL={'2025-10-21','2026-11-08'}
def scheduled(signal,horizon,observed_extra=()):
 d=date.fromisoformat(signal);out=[];extra=set(observed_extra)|SPECIAL
 while len(out)<horizon:
  d+=timedelta(days=1)
  if d.year not in(2025,2026):raise ValueError('OFFICIAL_CALENDAR_YEAR_NOT_SUPPORTED: add reviewed exchange calendar, never guess')
  if (d.weekday()<5 and d.isoformat()not in HOLIDAYS)or d.isoformat()in extra:out.append(d.isoformat())
 return out
def outcome(bars,index,signal,horizon,latest):
 window=scheduled(signal,horizon,index.keys())
 if window[-1]>latest:return None,'IMMATURE'
 if signal not in bars:return None,'MISSING_SIGNAL_BAR'
 if any(d not in bars for d in window):return None,'MISSING_FORWARD_STOCK_SESSION'
 if any(d not in index for d in window):return None,'MISSING_FORWARD_BENCHMARK_SESSION'
 entry=float(bars[window[0]]['Open']);exit=float(bars[window[-1]]['Close'])
 if entry<=0 or exit<=0:return None,'NONPOSITIVE_OFFICIAL_PRICE'
 net=round(exit*.9985,6)/round(entry*1.0015,6)-1
 return {'entry_date':window[0],'horizon_date':window[-1],'entry_official_open':entry,'exit_official_close':exit,'gross_return':exit/entry-1,'hypothetical_round_trip_net_return':net,'close_to_close_return':exit/float(bars[signal]['Close'])-1,'nifty50_gross_return':float(index[window[-1]]['Close'])/float(index[window[0]]['Open'])-1},None
def readbars(path):
 out={}
 with path.open(newline='',encoding='utf-8-sig')as f:
  for r in csv.DictReader(f):
   d=r['Date'];date.fromisoformat(d)
   if d in out:raise ValueError('DUPLICATE_OFFICIAL_SESSION:'+d)
   if any(not math.isfinite(float(r[k]))or float(r[k])<=0 for k in ['Open','Close']):raise ValueError('INVALID_OFFICIAL_PRICE:'+d)
   out[d]=r
 return out
def evaluate(database,prices,output):
 database=Path(database).resolve();prices=Path(prices).resolve();output=Path(output).resolve()
 if output.is_relative_to(database.parent)or output.is_relative_to(prices):raise ValueError('OUTPUT_MUST_BE_OUTSIDE_SRE_DATA')
 wal=Path(str(database)+'-wal')
 if wal.exists()and wal.stat().st_size:raise ValueError('CLOSE_SRE_AND_USE_A_CONSISTENT_BACKUP; nonempty WAL will not be ignored')
 before=hashlib.sha256(database.read_bytes()).hexdigest();index=readbars(prices/'INDEX_NSEI.csv');latest=max(index);cache={};seen=set();records=[];excluded=[]
 c=sqlite3.connect(database.as_uri()+'?mode=ro&immutable=1',uri=True);c.row_factory=sqlite3.Row
 try:
  query='select c.*,r.market_session,r.horizon_sessions,r.model_version,r.feature_contract_version,r.training_cutoff,r.created_at as forecast_created_utc from prediction_candidates c join prediction_runs r on r.run_id=c.run_id order by r.created_at,c.id'
  for row in c.execute(query):
   r=dict(row);symbol=r['symbol'];signal=r['market_session'];h=int(r['horizon_sessions']);key=(symbol,signal,h,r['model_version'],r['feature_contract_version'],r['training_cutoff'])
   if key in seen:continue
   seen.add(key)
   if r['expected_return']is None:continue
   item={'symbol':symbol,'signal_date':signal,'horizon_sessions':h,'forecast_return':r['expected_return'],'run_id':r['run_id'],'forecast_created_utc':r['forecast_created_utc']}
   if str(r['training_cutoff'])[:10]>signal:excluded.append({**item,'reason':'TRAINING_CUTOFF_AFTER_SIGNAL'});continue
   path=prices/(symbol+'.NS.csv')
   if not path.exists():path=prices/(symbol+'.csv')
   if not path.exists():excluded.append({**item,'reason':'MISSING_STOCK_SOURCE'});continue
   if symbol not in cache:cache[symbol]=readbars(path)
   try:value,reason=outcome(cache[symbol],index,signal,h,latest)
   except ValueError as exc:value,reason=None,str(exc)
   if reason:excluded.append({**item,'reason':reason});continue
   if abs(float(cache[symbol][signal]['Close'])-float(r['latest_close']))>1e-4:excluded.append({**item,'reason':'STORED_REFERENCE_PRICE_DIFFERS_FROM_CAPTURED_PRICE'});continue
   nextopen=datetime.fromisoformat(value['entry_date']+'T03:45:00+00:00');created=datetime.strptime(r['forecast_created_utc'],'%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
   records.append({**item,**value,'forecast_error':float(r['expected_return'])-value['gross_return'],'recorded_before_entry_open':created<=nextopen})
 finally:c.close()
 if hashlib.sha256(database.read_bytes()).hexdigest()!=before:raise RuntimeError('SOURCE_DATABASE_CHANGED_DURING_READ; discard results and capture consistent snapshot')
 folder=output/('forecast-review-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));folder.mkdir(parents=True,exist_ok=False)
 for name,rs in [('outcomes.csv',records),('exclusions.csv',excluded)]:
  if rs:
   with (folder/name).open('w',newline='',encoding='utf-8')as f:w=csv.DictWriter(f,fieldnames=list(rs[0]));w.writeheader();w.writerows(rs)
 summary={'status':'RESEARCH_MEASUREMENTS_ONLY; NOT_STRATEGY_VALIDATION','latest_captured_session':latest,'mature_evaluable':len(records),'recorded_before_entry_open':sum(r['recorded_before_entry_open']for r in records),'exclusions':dict(collections.Counter(r['reason']for r in excluded)),'source_database_sha256':before,'application_files_written':False,'slippage_bps_each_side':10,'transaction_cost_bps_each_side':5,'cost_scope':'Existing modeled assumptions; not a statement of all real broker taxes/charges','benchmark':'NIFTY50 price comparator; no NIFTY200 or total-return claim','calendar_sources':['https://nsearchives.nseindia.com/content/circulars/CMTR65587.pdf','https://niftyindices.com/resources/holiday-calendar'],'calendar_limit':'Reviewed 2025/2026 dates plus supplied index extra sessions; verify later exchange circulars before extending','does_not_trade_or_change_buy_rules':True}
 summary['by_horizon']={}
 for h in sorted({r['horizon_sessions']for r in records}):
  rs=[r for r in records if r['horizon_sessions']==h];n=len(rs)
  summary['by_horizon'][str(h)]={'n':n,'signal_dates':len({r['signal_date']for r in rs}),'recorded_before_entry_open':sum(r['recorded_before_entry_open']for r in rs),'mae':sum(abs(r['forecast_error'])for r in rs)/n,'rmse':math.sqrt(sum(r['forecast_error']**2 for r in rs)/n),'bias_forecast_minus_actual':sum(r['forecast_error']for r in rs)/n,'zero_forecast_mae':sum(abs(r['gross_return'])for r in rs)/n,'mean_hypothetical_net_return':sum(r['hypothetical_round_trip_net_return']for r in rs)/n}
 (folder/'SUMMARY.json').write_text(json.dumps(summary,indent=2));return folder
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--database',required=True);p.add_argument('--prices',required=True);p.add_argument('--output',required=True);a=p.parse_args()
 print(evaluate(a.database,a.prices,a.output))
