from pathlib import Path
import json,tempfile
from modern_ui.api import ModernAppContext
from stock_app import fundamental_v3 as f
from stock_app.replay_v10 import ReplayCacheV10
root=Path('snapshot/installed-engine').resolve();c=ModernAppContext(repo_root=root,app_data_dir=Path(tempfile.mkdtemp()))
symbols=[r['symbol'].replace('.NS','') for r in c.data_source_status()['active']['members']];dates=c._phase81_available_sessions()
paths=[p for k,p in f.discover_sources(root).items() if p and k!='independent_validation'];queries=rows=0
with ReplayCacheV10(store_directory='verification/effective-leakage',source_fingerprint='availability-audit',market_fingerprint='snapshot',history_provider=c.prices.history,source_roots=[root]) as cache:
 for symbol in symbols:
  for d in dates:
   cutoff=f._cutoff(d)
   for p in paths:
    selected=cache.fundamental_index.timeline_rows(p,symbol,cutoff,'effective_availability_ts');queries+=1
    for r in selected:
     assert f._dt(r.get('effective_availability_ts'))<=cutoff
     rows+=1
Path('reports/leakage-effective.json').write_text(json.dumps({'status':'PASS','timestamp':'effective_availability_ts','queries':queries,'selected_rows_checked':rows,'future_data_violations':0},indent=2));print('EFFECTIVE_LEAKAGE_PASS',queries,rows,flush=True)
