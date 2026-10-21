import importlib.util,sys,json,tempfile,sqlite3,shutil,time
from pathlib import Path
from modern_ui.api import ModernAppContext
from stock_app.replay_v10 import ReplayCacheV10,source_signature,market_signature
from stock_app.validation_v2 import ExecutionAssumptions
root=Path('snapshot/installed-engine').resolve();code=Path('v10work').resolve()
s=importlib.util.spec_from_file_location('reference_api',root/'modern_ui/api.py');original=importlib.util.module_from_spec(s);sys.modules['reference_api']=original;s.loader.exec_module(original)
ref=original.ModernAppContext(repo_root=root,app_data_dir=Path(tempfile.mkdtemp()));new=ModernAppContext(repo_root=root,app_data_dir=Path(tempfile.mkdtemp()));new.code_root=code
dates=new._phase81_available_sessions();checks=[]
with ReplayCacheV10(store_directory='verification/decision-features',source_fingerprint=source_signature(code,root),market_fingerprint=market_signature(new.prices),history_provider=new.prices.history,source_roots=[root,code]) as cache:
 for d in [dates[0],dates[250],dates[420],dates[-1]]:
  state={'cash':100000.0,'positions':{},'pending':[]};a=ref._validation_pit_session(d,state,ExecutionAssumptions());b=new._validation_pit_session(d,state,ExecutionAssumptions(),cache)
  for p in [a,b]:p.get('allocation_plan',{}).pop('generated_at',None)
  assert a==b,(d,[k for k in a if a[k]!=b.get(k)])
  checks.append({'date':d,'stocks':len(a['rows']),'status':'PASS'});cache.flush();print(checks[-1],flush=True)
Path('reports/decision-parity.json').write_text(json.dumps({'status':'PASS','checks':checks},indent=2))
# Preserve actual production/paper state on isolated copies.
import modern_ui.api as api
from fastapi.testclient import TestClient
app=Path(tempfile.mkdtemp())
for n in ['stock_recommendation_engine.sqlite3','phase81_validation.sqlite3','validation_v2.sqlite3']:shutil.copy2(Path('snapshot/application-state')/n,app/n)
def tables(p):
 with sqlite3.connect(p) as con:
  names=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
  return {n:sorted(con.execute('SELECT * FROM "'+n.replace('"','""')+'"').fetchall(),key=repr) for n in names if not n.startswith('replay_v2_')}
c=ModernAppContext(repo_root=root,app_data_dir=app);c.code_root=code;before={p.name:tables(p) for p in app.glob('*.sqlite3')}
c.phase81_historical_replay(period='CUSTOM',start_date=dates[-1],end_date=dates[-1]);after={p.name:tables(p) for p in app.glob('*.sqlite3')};assert before==after
api.ModernAppContext=lambda **kw:c
client=TestClient(api.create_app());paths=['/api/health','/api/validation/authority','/api/validation/historical-evidence/summary','/api/validation/historical-evidence','/']
for p in paths:assert client.get(p).status_code==200,p
r=client.get(paths[2]).json();assert r['complete_replays']==1 and r['affects_live_decisions'] is False and r['authority']=='RESEARCH_ONLY'
Path('reports/api-accounting.json').write_text(json.dumps({'status':'PASS','unchanged_tables':{n:list(v) for n,v in before.items()},'http_checks':paths,'shadow_evidence_count':r['complete_replays']},indent=2));print('DECISION_API_ACCOUNTING_PASS',flush=True)
