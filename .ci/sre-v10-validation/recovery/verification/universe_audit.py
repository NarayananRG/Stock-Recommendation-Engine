import importlib.util,sys,json,tempfile,time
from pathlib import Path
import numpy as np,pandas as pd
from pandas.testing import assert_frame_equal
from modern_ui.api import ModernAppContext
from stock_app import technical_v2 as t,fundamental_v3 as f
from stock_app.replay_v10 import ReplayCacheV10,numpy_supertrend,source_signature
root=Path('snapshot/installed-engine').resolve();code=Path('v10work').resolve()
def original(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m
ot=original('reference_technical',root/'stock_app/technical_v2.py');of=original('reference_fundamental',root/'stock_app/fundamental_v3.py')
c=ModernAppContext(repo_root=root,app_data_dir=Path(tempfile.mkdtemp()));c.code_root=code
symbols=[x['symbol'].replace('.NS','') for x in c.data_source_status()['active']['members']];dates=c._phase81_available_sessions();cuts=[dates[int(i)] for i in np.linspace(0,len(dates)-1,12,dtype=int)]
bench=c.prices.history('INDEX_NSEI',5000);counts={'technical_full_frames':0,'technical_prefixes':0,'technical_outputs':0,'fundamental_outputs':0,'filing_selections':0,'leakage_queries':0,'selected_rows_checked':0,'future_data_violations':0};started=time.perf_counter()
paths={k:p for k,p in f.discover_sources(root).items() if p and k!='independent_validation'}
with ReplayCacheV10(store_directory='verification/audit-features',source_fingerprint=source_signature(code,root),market_fingerprint='snapshot',history_provider=c.prices.history,source_roots=[root]) as cache:
 for i,symbol in enumerate(symbols):
  bars=c.prices.history(symbol,5000);frame=pd.DataFrame(bars)
  ref=ot.compute_features(frame,pd.DataFrame(bench));fast=t.compute_features(frame,pd.DataFrame(bench),_supertrend_fn=numpy_supertrend);assert_frame_equal(ref,fast,check_exact=True);counts['technical_full_frames']+=1
  for d in cuts:
   prefix=[r for r in bars if r['date']<=d];bp=[r for r in bench if r['date']<=d]
   if prefix:
    a=ot.compute_features(pd.DataFrame(prefix),pd.DataFrame(bp));b=fast.loc[:pd.Timestamp(d)];assert_frame_equal(a,b,check_exact=True);counts['technical_prefixes']+=1
    expected=ot.analyze(pd.DataFrame(prefix),pd.DataFrame(bp) if bp else None)
    actual=cache.technical_timeline(symbol,20,prefix,bench,[]);assert expected==actual,(symbol,d,'technical output');counts['technical_outputs']+=1
   assert of.analyze(root,symbol,decision_timestamp=d,latest_price=100)==f.analyze(root,symbol,decision_timestamp=d,latest_price=100),(symbol,d,'fundamental');counts['fundamental_outputs']+=1
   for p in paths.values():
    for key in ['availability_ts','effective_availability_ts']:
     assert of._timeline_rows(p,symbol,of._cutoff(d),key)==cache.fundamental_index.timeline_rows(p,symbol,f._cutoff(d),key);counts['filing_selections']+=1
  for d in dates:
   cutoff=f._cutoff(d)
   for p in paths.values():
    rows=cache.fundamental_index.timeline_rows(p,symbol,cutoff,'availability_ts');counts['leakage_queries']+=1
    for r in rows:
     assert f._dt(r.get('availability_ts') or r.get('effective_availability_ts'))<=cutoff
     counts['selected_rows_checked']+=1
  cache.flush()
  if i%20==0:print(i+1,'/',len(symbols),counts,round(time.perf_counter()-started,2),flush=True)
Path('reports/universe-parity.json').write_text(json.dumps({'status':'PASS','universe':len(symbols),'available_sessions':len(dates),'counts':counts,'elapsed_seconds':time.perf_counter()-started,'source_signature':source_signature(code,root)},indent=2));print('UNIVERSE_PARITY_AND_LEAKAGE_PASS',flush=True)
