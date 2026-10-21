import json,time,sys
from pathlib import Path
from datetime import date,timedelta
from modern_ui.api import ModernAppContext
version=sys.argv[1];app=Path('verification/state-'+version).resolve();app.mkdir(exist_ok=True)
c=ModernAppContext(repo_root=Path('snapshot/installed-engine').resolve(),app_data_dir=app)
if version=='V10':c.code_root=Path('v10work').resolve()
sessions=c._phase81_available_sessions();rows=[]
for case,period,start,end in [('cold_one_session','CUSTOM',sessions[-1],sessions[-1]),('warm_identical_result','CUSTOM',sessions[-1],sessions[-1]),('overlap_plus_uncomputed_date','CUSTOM',sessions[-2],sessions[-1]),('1W_overlapping','1W',None,sessions[-1])]:
 if version=='V9' and period=='1W':period='CUSTOM';start=(date.fromisoformat(end)-timedelta(days=7)).isoformat()
 t=time.perf_counter();r=c.phase81_historical_replay(period=period,start_date=start,end_date=end)
 rows.append({'version':version,'case':case,'elapsed_seconds':time.perf_counter()-t,'replayed_sessions':r['sessions_replayed'],'cache_status':r.get('replay_cache_status'),'stats':r.get('replay_input_cache_stats')})
 if case=='cold_one_session':Path('reports/'+version+'-single.json').write_text(json.dumps(r,indent=2))
 print(rows[-1]['case'],rows[-1]['elapsed_seconds'],flush=True)
Path('reports/'+version+'-benchmark.json').write_text(json.dumps({'runs':rows,'state_directory':str(app)},indent=2))
