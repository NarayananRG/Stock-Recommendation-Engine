"""Isolated Windows VM staging executor. Host live/Initial data are never mapped."""
from pathlib import Path
import argparse,ast,csv,json,os,shutil,socket,sqlite3,subprocess,sys,time,urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parent));sys.dont_write_bytecode=True
from source_transaction import *
BASE=Path(__file__).resolve().parent
INPUT=Path('C:/C01Input');OUTPUT=Path('C:/C01Output');WORK=Path('C:/C01')
def record(r,k,status,evidence):r['checks'][k]={'status':status,'evidence':evidence}
def db_snapshot(p):
 c=sqlite3.connect(Path(p).resolve().as_uri()+'?mode=ro',uri=True,timeout=15);c.execute('pragma query_only=on')
 try:
  c.execute('begin');out={}
  for name,sql in c.execute("select name,sql from sqlite_master where type='table' and name not like 'sqlite_%' order by name").fetchall():
   rows=[digest([{'bytes':v.hex()}if isinstance(v,bytes)else v for v in row])for row in c.execute('select * from "'+name.replace('"','""')+'"')]
   out[name]={'schema':sql,'rows':len(rows),'digest':digest(sorted(rows))}
  return out
 finally:c.close()
def dbs(data):return{p.name:db_snapshot(p)for p in data.glob('*.sqlite3')}
def financial_equal(before,after):
 # Exact existing non-monitoring rows. Startup is documented to add only monitoring evidence.
 def financial(v):return {db:{t:h for t,h in rows.items()if t!='holdings_monitoring'}for db,rows in v.items()}
 a=financial(before);b=financial(after)
 require(a==b,'NON_MONITORING_DATABASE_CHANGED: '+','.join(db+'/'+t for db in a for t in a[db]if b.get(db,{}).get(t)!=a[db][t]))
def paper_accounting(data):
 p=data/'phase81_validation.sqlite3';c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)
 try:
  rows=c.execute('select state_json from paper_v2_portfolios').fetchall();require(bool(rows),'PAPER_BASELINE_MISSING')
  import math
  for row in rows:
   s=json.loads(row[0]);nav,cash,invested=[float(s[k])for k in ('nav','cash','invested_value')];require(all(map(math.isfinite,[nav,cash,invested]))and abs(nav-cash-invested)<=.021,'PAPER_ACCOUNTING_MISMATCH')
 finally:c.close()
def clone_engine(name,source):
 root=WORK/name;root.mkdir(exist_ok=False);shutil.copytree(source,root/'engine');write(root/'ISOLATED_WORKSPACE.json',{'purpose':'C01_STAGING_ONLY','root':str(root.resolve())});return root
def load():
 p=BASE/'review';return json.loads((p/'BASELINE_SOURCE_GUARD.json').read_text()),json.loads((p/'CHANGE_MANIFEST.json').read_text()),p/'candidate/engine'
def rehearse(source,guard,manifest,candidate,r):
 a=clone_engine('source-rehearsal',source);protected=files(INPUT/'restore/app-state');apply(a,candidate,guard,manifest);record(r,'source_apply','PASS','All six exact candidate files installed on isolated source copy; durable receipt retained')
 rollback(a,guard,manifest);require(files(INPUT/'restore/app-state')==protected,'PROTECTED_STATE_CHANGED');record(r,'source_rollback','PASS','Five originals restored, matching added guard removed,46 original hashes restored; no financial/evidence writes')
 b=clone_engine('interrupted-source',source)
 proc=subprocess.run([sys.executable,'-I','-S','-B',str(BASE/'sandbox_worker.py'),'--crash-source',str(b)],timeout=60)
 require(proc.returncode==79,'SOURCE_INTERRUPT_DID_NOT_FIRE');rollback(b,guard,manifest,recovery=True);original(b,guard,manifest);record(r,'interrupted_install_recovery','PASS','Child process exited after two source replacements; PREPARED receipt recovered all originals')
 d=clone_engine('drift-source',source);bad=child(d/'engine',manifest['files'][0]['path']);bad.write_bytes(bad.read_bytes()+b'\n# ISOLATED DRIFT\n');before=files(d/'engine')
 try:apply(d,candidate,guard,manifest);raise RuntimeError('DRIFT_NOT_REFUSED')
 except Stop:pass
 require(files(d/'engine')==before,'REFUSED_APPLY_CHANGED_SOURCE');record(r,'hash_drift_refusal','PASS','Unexpected source drift refused before publication; source bytes unchanged')
 # Rollback must refuse a modified new guard before changing any original file.
 e=clone_engine('rollback-drift',source);apply(e,candidate,guard,manifest);new=next(x for x in manifest['files']if x['before_sha256']is None);child(e/'engine',new['path']).write_bytes(b'SYNTHETIC_MODIFIED_GUARD');before=files(e/'engine')
 try:rollback(e,guard,manifest);raise RuntimeError('ROLLBACK_DRIFT_NOT_REFUSED')
 except Stop:pass
 require(files(e/'engine')==before,'REFUSED_ROLLBACK_CHANGED_SOURCE')
def stage_reference_fixtures(tests,source,guard):
 reference=tests/'reference_engine';names=[p.relative_to(reference).as_posix()for p in reference.rglob('*.py')]
 require(len(names)==7 and all(n in guard for n in names),'EXPECTED_SEVEN_PROTECTED_REFERENCE_FIXTURES')
 verify(source,{n:guard[n]for n in names})
 for n in names:
  target=child(reference,n);shutil.copy2(child(source,n),target);require(sha(target)==guard[n],'REFERENCE_FIXTURE_COPY_MISMATCH')
def verify_history_preservation(engine,before):
 after={n:h for n,h in files(engine).items()if n.startswith('data/')}
 require(all(after.get(n)==h for n,h in before.items()),'OFFICIAL_HISTORY_BYTES_CHANGED')
 added=set(after)-set(before)
 require(all(Path(n).name=='.sre_official_refresh.lock'and after[n]==__import__('hashlib').sha256(b'0').hexdigest()for n in added),'UNEXPECTED_OFFLINE_DATA_FILE')
def free_port():
 s=socket.socket();s.bind(('127.0.0.1',0));port=s.getsockname()[1];s.close();return port
def fetch(port,path):
 with urllib.request.urlopen('http://127.0.0.1:'+str(port)+path,timeout=90)as response:return response.headers,response.read()
def lifecycle(root,data,r):
 before=dbs(data);paper_accounting(data);evidence={n:h for n,h in files(data).items()if n.endswith('.complete.zlib')};history={n:h for n,h in files(root/'engine').items()if n.startswith('data/')};require(len(evidence)==18,'EXPECTED_18_ORIGINAL_REPLAY_FILES')
 states=[];browser=None
 for cycle in range(2):
  port=free_port();log=OUTPUT/('PRIVATE/backend-'+str(cycle)+'.log');log.parent.mkdir(exist_ok=True)
  startup_ok=False
  with log.open('wb')as output:
   proc=subprocess.Popen([sys.executable,'-I','-S','-B',str(BASE/'launch_backend.py'),str(root/'engine'),str(data),str(port)],stdin=subprocess.PIPE,stdout=output,stderr=subprocess.STDOUT,text=True)
   try:
    deadline=time.monotonic()+120
    while True:
     require(proc.poll()is None,'BACKEND_EXITED_DURING_STARTUP')
     try:health=json.loads(fetch(port,'/api/health')[1]);break
     except Exception:
      require(time.monotonic()<deadline,'BACKEND_STARTUP_TIMEOUT');time.sleep(.5)
    require(Path(health['code_root']).resolve()==(root/'engine').resolve()and Path(health['repo_root']).resolve()==(root/'engine').resolve()and Path(health['database']).resolve()==(data/'stock_recommendation_engine.sqlite3').resolve(),'BACKEND_PATH_ISOLATION_MISMATCH')
    require(health.get('decision_authority')=='LIVE_DECISION_V1','FROZEN_AUTHORITY_MISMATCH');startup_ok=True
    ev=json.loads(fetch(port,'/api/validation/historical-evidence')[1]);write(OUTPUT/('PRIVATE/evidence-'+str(cycle)+'.json'),ev);require(ev.get('invalid_replays')==0 and ev.get('complete_replays',0)+ev.get('stale_replays',0)==18,'EVIDENCE_DISCOVERY_COUNT_OR_INTEGRITY_CHANGED')
    states.append({'pid':proc.pid,'complete':ev['complete_replays'],'stale':ev['stale_replays'],'invalid':ev['invalid_replays']})
    html=fetch(port,'/')[1];require(b'<html'in html.lower()and b'<script'in html.lower(),'FRONTEND_SHELL_MISSING');fetch(port,'/assets/app.js');record(r,'static_gui_delivery','PASS','Real staged frontend HTML and JS served on loopback; not desktop visual acceptance')
    if cycle==0:
     # A visible browser can display the copied UI, but no visual/manual acceptance is inferred.
     edges=[Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe',Path('C:/Program Files/Microsoft/Edge/Application/msedge.exe')]
     edge=next((x for x in edges if x.is_file()),None)
     if edge:
      browser=subprocess.Popen([str(edge),'--user-data-dir='+str(WORK/'browser-profile'),'--no-first-run','--no-default-browser-check','--disable-background-networking','--new-window','http://127.0.0.1:'+str(port)]);time.sleep(8)
     record(r,'desktop_gui_acceptance','BLOCKED','Browser staging shell only. Installed native launcher/WebView startup, visible holdings/research and operator review are not proven.')
    financial_equal(before,dbs(data));paper_accounting(data)
   finally:
    if proc.poll()is None:
     proc.stdin.write('STOP\n');proc.stdin.flush()
     try:proc.wait(timeout=30)
     except subprocess.TimeoutExpired:proc.terminate();proc.wait(timeout=10);raise Stop('GRACEFUL_SHUTDOWN_FAILED')
    if startup_ok:require(proc.returncode==0,'BACKEND_SHUTDOWN_NONZERO')
  financial_equal(before,dbs(data));require({n:h for n,h in files(data).items()if n.endswith('.complete.zlib')}==evidence,'REPLAY_BYTES_CHANGED');verify_history_preservation(root/'engine',history)
 if browser and browser.poll()is None:browser.terminate()
 require(states[0]['pid']!=states[1]['pid'],'RESTART_PROCESS_NOT_DISTINCT');r['backend_cycles']=states
 record(r,'backend_lifecycle','PASS','Actual isolated Windows VM staged API started, stopped gracefully and restarted under distinct PIDs; health paths verified')
 record(r,'offline_backend','PASS','Actual staged backend lifecycle with VM network adapters disconnected; loopback available')
 record(r,'offline_gui','BLOCKED','Native desktop cached views/stale warnings require visible operator verification; served HTML is insufficient')
 record(r,'financial_preservation','PASS','Exact non-monitoring table schemas/row hashes unchanged across startup/navigation/restart; paper accounting reconciles')
 record(r,'evidence_preservation','PASS','All18 original replay payload bytes retained; source/path identity staleness reported without editing hashes or rerunning research')
 record(r,'official_history_preservation','PASS','All original staged engine data files retain their bytes; only the expected one-byte C01 reader lock may be added')
def calendar(engine):
 from datetime import datetime,timedelta
 tree=ast.parse((engine/'modern_ui/api.py').read_text(encoding='utf-8'));cl=next(n for n in tree.body if isinstance(n,ast.ClassDef)and n.name=='ModernAppContext');names={'_is_nse_trading_day','_previous_nse_session','expected_market_session'};nodes=[n for n in cl.body if isinstance(n,ast.FunctionDef)and n.name in names]
 ns={'datetime':datetime,'timedelta':timedelta,'os':os,'Any':object};exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name='Calendar',bases=[],keywords=[],body=nodes,decorator_list=[])],type_ignores=[])),'captured-session-contract','exec'),ns);return ns['Calendar'].expected_market_session()
def official(root,data,r):
 sys.path.insert(0,str(root/'engine'));from stock_app.official_daily_refresh import refresh_official_session
 # Extract exact installed official-cache root method without constructing the GUI context.
 tree=ast.parse((root/'engine/modern_ui/api.py').read_text(encoding='utf-8'));cl=next(n for n in tree.body if isinstance(n,ast.ClassDef)and n.name=='ModernAppContext');fn=next(n for n in cl.body if isinstance(n,ast.FunctionDef)and n.name=='_official_cache_roots');ns={'Path':Path};exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'captured-cache-contract','exec'),ns)
 from zoneinfo import ZoneInfo
 ZoneInfo('Asia/Kolkata') # Refuse a missing timezone database; never use guest local UTC as IST.
 expected=calendar(root/'engine')['expected_market_session'];require(not os.environ.get('SRE_EXPECTED_SESSION_NOW'),'NO_CLOCK_OVERRIDE');roots=ns['_official_cache_roots'](root/'engine');before={str(p):p.read_bytes()for cache in roots for p in cache.glob('*.csv')};dbbefore=dbs(data);evidence={n:h for n,h in files(data).items()if n.endswith('.complete.zlib')}
 result=refresh_official_session([str(p)for p in roots],expected);financial_equal(dbbefore,dbs(data));require({n:h for n,h in files(data).items()if n.endswith('.complete.zlib')}==evidence,'OFFICIAL_REFRESH_CHANGED_RESEARCH');write(OUTPUT/'PRIVATE/official-response.json',result);r['official_contract_status']=result.get('status');r['expected_session']=expected
 if result['status']not in('ALREADY_CURRENT','REFRESHED_AND_VERIFIED'):
  require(all(Path(p).read_bytes()==b for p,b in before.items()),'FAILED_OFFICIAL_REFRESH_CHANGED_ROWS');record(r,'official_network_retrieval','BLOCKED','Existing official contract returned '+str(result.get('status'))+' / '+str(result.get('reason_code'))+'; no accepted fresh session, original rows retained');return
 require(result.get('automatic_yfinance_fallback')is False,'UNAPPROVED_FALLBACK');require(result.get('stock_files_expected')==200 and result.get('stock_files_matched')==200 and result.get('equity_session')==expected and result.get('index_session')==expected,'FULL_OFFICIAL_SESSION_COVERAGE_FAILED')
 for p,b in before.items():require(Path(p).read_bytes().startswith(b),'EXISTING_OFFICIAL_BYTES_REPLACED')
 first={str(p):sha(p)for cache in roots for p in cache.glob('*.csv')};retry=refresh_official_session([str(p)for p in roots],expected);require(retry['status']=='ALREADY_CURRENT','OFFICIAL_RETRY_NOT_IDEMPOTENT');require(all(sha(p)==h for p,h in first.items()),'RETRY_CHANGED_OFFICIAL_ROWS')
 financial_equal(dbbefore,dbs(data));require({n:h for n,h in files(data).items()if n.endswith('.complete.zlib')}==evidence,'OFFICIAL_REFRESH_CHANGED_RESEARCH')
 record(r,'official_network_retrieval','PASS','Real official NSE retrieval accepted on fresh isolated copy under unchanged expected-session calendar; no production refresh')
 record(r,'official_full_coverage','PASS','200 local equities plus existing NIFTY50 index contract matched expected session; old row bytes preserved and retry idempotent')
 prov=result.get('provenance',{});published=all(v.get('source_publication_time')for v in prov.values())and len(prov)==2
 record(r,'official_publication_time','PASS'if published else'BLOCKED','Original source publication time present'if published else'Retrieval UTC/source payload hashes retained; original exchange publication timestamp unknown, not invented')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--phase',choices=['offline','official']);ap.add_argument('--crash-source');args=ap.parse_args();guard,manifest,candidate=load()
 from vm_environment import validate_context
 validate_context(args.phase)
 if args.crash_source:apply(Path(args.crash_source),candidate,guard,manifest,fault_after=2);return
 r={'checks':{},'phase':args.phase,'live_installation_modified':False,'historical_replays_run':0};OUTPUT.mkdir(exist_ok=True)
 try:
  require(os.name=='nt'and str(BASE).lower()=='c:\\c01package','VM_STAGING_PATH_REQUIRED');require(sys.version_info[:3]==(3,14,3),'EXACT_PYTHON_3_14_3_REQUIRED');require(not WORK.exists(),'CLEAN_VM_WORKSPACE_REQUIRED');WORK.mkdir()
  info=json.loads((INPUT/'input.json').read_text());verify(INPUT/'restore',info['restore_files'],exact=True);verify(INPUT/'runtime',info['runtime_files'],exact=True);verify(INPUT/'deps',info['dependency_files'],exact=True)
  source=INPUT/'restore/engine';verify(source,guard)
  if args.phase=='offline':rehearse(source,guard,manifest,candidate,r)
  root=clone_engine('application',source);data=root/'app-data';shutil.copytree(INPUT/'restore/app-state',data)
  for name,expected in info['database_snapshots'].items():
   p=child(INPUT/'restore',name);require(db_snapshot(p)==expected,'INITIAL_DB_ACCOUNTING_DIGEST_MISMATCH:'+name);shutil.copy2(p,data/name)
  # Data-side absolute old configuration remains preserved. Exact explicit app/data/env roots override discovery; no live paths exist in this VM.
  shutil.copytree(INPUT/'deps',root/'engine/.replay-v10-deps')
  sys.path[:0]=[str(root/'engine/.replay-v10-deps'),str(Path(sys.prefix)/'Lib/site-packages')]
  import importlib.metadata as metadata
  packages={name:metadata.version(name)for name in info['package_versions']}
  require(packages==info['package_versions'],'RUNTIME_PACKAGE_VERSION_MISMATCH');write(OUTPUT/'PRIVATE/runtime-closure.json',{'python':sys.version,'packages':packages,'runtime_files_verified':len(info['runtime_files']),'dependency_files_verified':len(info['dependency_files'])});record(r,'runtime_dependencies','PASS','Copied bytes match the new input snapshot; recorded native hashes and package versions match Initial inventory; no dependencies installed')
  apply(root,candidate,guard,manifest)
  if args.phase=='offline':
   tests=WORK/'regressions';shutil.copytree(BASE/'review/isolated_tests',tests);stage_reference_fixtures(tests,source,guard);env=dict(os.environ,C01_TEST_ENGINE=str(root/'engine'),PYTHONDONTWRITEBYTECODE='1');p=subprocess.run([sys.executable,'-I','-S','-B',str(tests/'run_regressions.py')],env=env,capture_output=True,text=True,timeout=600);(OUTPUT/'PRIVATE').mkdir(exist_ok=True);(OUTPUT/'PRIVATE/c01-regression.log').write_text(p.stdout+'\n'+p.stderr);require(p.returncode==0,'STAGED_C01_REGRESSION_FAILED');res=json.loads((tests/'reports/C01_REGRESSION_RESULTS.json').read_text());require(res['tests_run']==42 and res['passed']==42 and res['failures']==0 and res['errors']==0,'EXPECTED42_STAGED_TESTS');record(r,'staged_regressions','PASS','42/42 C01 integrity tests against exact staged engine in actual isolated Windows VM; synthetic test data');r['staged_test_results']=res;lifecycle(root,data,r)
  else:official(root,data,r)
  verify(INPUT/'restore',info['restore_files'],exact=True);r['execution_complete']=True
 except Exception as exc:
  r['stop_reason']=str(exc);record(r,'execution','FAIL'if isinstance(exc,Stop)and any(x in str(exc)for x in['CHANGED','MISMATCH','DRIFT_NOT_REFUSED','NOT_IDEMPOTENT','SHUTDOWN_FAILED'])else'BLOCKED',str(exc));r['execution_complete']=False
 finally:write(OUTPUT/'DONE.json',r)
if __name__=='__main__':main()
