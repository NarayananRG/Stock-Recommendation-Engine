"""Gate C acceptance runner. Never sends POST, starts SRE, edits installation or restores live DBs."""
from pathlib import Path
import argparse,ast,collections,csv,hashlib,importlib.util,json,os,shutil,socket,sqlite3,subprocess,sys,time,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
sys.dont_write_bytecode=True
BASE=Path(__file__).resolve().parent
DAYS={'2026-10-09','2026-10-15','2026-10-19'}
class InvariantError(RuntimeError):pass
def require(ok,msg):
 if not ok:raise InvariantError(msg)
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def write(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(v,indent=2,default=str),encoding='utf-8');os.replace(tmp,p)
def readonly_db(p):
 c=sqlite3.connect(Path(p).resolve().as_uri()+'?mode=ro',uri=True,timeout=15);c.execute('pragma query_only=on');return c
def db_snapshot(p):
 c=readonly_db(p)
 try:
  c.execute('begin');out={}
  for name,sql in c.execute("select name,sql from sqlite_master where type='table' and name not like 'sqlite_%' order by name").fetchall():
   quoted='"'+name.replace('"','""')+'"';rows=[digest([{'bytes':v.hex()} if isinstance(v,bytes) else v for v in row]) for row in c.execute('select * from '+quoted)]
   out[name]={'schema':sql,'rows':len(rows),'digest':digest(sorted(rows))}
  return out
 finally:c.close()
def backup_db(src,dst):
 dst=Path(dst);require(not dst.exists(),'Backup destination already exists')
 c=readonly_db(src);d=sqlite3.connect(dst);deadline=time.monotonic()+120
 def progress(*unused):require(time.monotonic()<deadline,'SQLite backup exceeded 120-second budget')
 try:c.backup(d,pages=256,progress=progress,sleep=.05)
 finally:d.close();c.close()
 c=readonly_db(dst)
 try:require(c.execute('pragma integrity_check').fetchone()[0]=='ok','Backup integrity failed')
 finally:c.close()
 require(db_snapshot(src)==db_snapshot(dst),'Source changed during SQLite backup or backup differs')
def filemap(root,skip=()):
 out={}
 for p in Path(root).rglob('*'):
  if not p.is_file() or p.is_symlink():continue
  rel=p.relative_to(root)
  if any(x in skip or x.startswith(('.oct31-current-backups','.gatea-','native-engine-')) for x in rel.parts):continue
  out[rel.as_posix()]=sha(p)
 return out
def guarded_copy(root,dest,skip=()):
 a=filemap(root,skip);size=sum((root/n).stat().st_size for n in a)
 require(shutil.disk_usage(dest.parent).free>size*2+512*1024*1024,'Insufficient free space for backup plus restore; nothing removed')
 for n,h in a.items():
  target=dest/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/n,target);require(sha(target)==h,'Unstable copy: '+n)
 require(filemap(root,skip)==a,'Source changed while copying; preserve output and stop')
 return a
def get(port,route):
 require(route in ('/api/health','/api/data-source','/api/validation/historical-evidence'), 'Non-whitelisted read route')
 with urllib.request.urlopen('http://127.0.0.1:'+str(port)+route,timeout=60) as r:return json.load(r)
def record(report,key,status,evidence,scope='actual Windows collector'):
 report['checks'][key]={'status':status,'evidence':evidence,'scope':scope,'at_utc':datetime.now(timezone.utc).isoformat()}
def save_report(run,report):
 report['gate_c']='FAIL' if any(x['status']=='FAIL' for x in report['checks'].values()) else ('CLOSED' if all(x['status']=='PASS' for x in report['checks'].values()) else 'BLOCKED')
 write(run/'GATE_C_MACHINE_RESULTS.json',report)
 lines=['# Gate C Windows acceptance','', 'Overall: **'+report['gate_c']+'**. Strategy profitability: **NOT VALIDATED**.','', '| Condition | Status | Evidence |','|---|---|---|']
 for k,v in report['checks'].items():lines.append('| '+k+' | '+v['status']+' | '+str(v['evidence']).replace('|','/').replace('\n',' ')+' |')
 (run/'GATE_C_FINAL_ACCEPTANCE.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
def paper_summary(db):
 c=readonly_db(db)
 try:
  portfolios=[{'portfolio_id':r[0],'status':r[1],'state':json.loads(r[2])} for r in c.execute('select portfolio_id,status,state_json from paper_v2_portfolios order by portfolio_id')]
  positions=[{'position_id':r[0],'portfolio_id':r[1],'symbol':r[2],'state':r[3],'qty':r[4],'entry_price':r[5],'entry_evidence_digest':digest(json.loads(r[6]))} for r in c.execute('select position_id,portfolio_id,symbol,state,qty,entry_price,position_json from paper_v2_positions order by position_id')]
  return {'portfolios':portfolios,'positions':positions}
 finally:c.close()
def runtime_inventory(exe,engine,run):
 require(Path(exe).is_file(),'GUI runtime executable unavailable')
 code="import sys,json,importlib.metadata as m;sys.path.insert(0,sys.argv[1]);names=['numpy','pandas','polars','pyarrow','fastapi','uvicorn','pydantic'];print(json.dumps({'executable':sys.executable,'python':sys.version,'prefix':sys.prefix,'packages':{n:m.version(n) for n in names}}))"
 r=subprocess.run([exe,'-B','-c',code,str(engine/'.replay-v10-deps')],capture_output=True,text=True,timeout=60)
 require(r.returncode==0,'Runtime/dependency metadata probe failed: '+r.stderr[-400:]);meta=json.loads(r.stdout)
 binaries=[]
 for root in [engine/'.replay-v10-deps',Path(exe).parent]:
  for p in root.rglob('*'):
   if p.is_file() and p.suffix.lower() in ('.dll','.pyd','.exe'):
    binaries.append({'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)})
 meta['binaries']=binaries;meta['runtime_binaries_copied']=False;write(run/'PRIVATE_RUNTIME_INVENTORY.json',meta);return meta

def expected_from_source(engine):
 # Exact installed calendar/session methods, no AppContext construction and no clock override.
 require(not os.environ.get('SRE_EXPECTED_SESSION_NOW'),'Clock override set; refuse acceptance')
 api=ast.parse((engine/'modern_ui/api.py').read_text(encoding='utf-8'));cl=next(n for n in api.body if isinstance(n,ast.ClassDef) and n.name=='ModernAppContext')
 wanted={'_is_nse_trading_day','_previous_nse_session','expected_market_session'}
 nodes=[n for n in cl.body if isinstance(n,ast.FunctionDef) and n.name in wanted]
 ns={'datetime':datetime,'timedelta':timedelta,'os':os,'Any':object};sys.path.insert(0,str(engine))
 try:
  tree=ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name='Calendar',bases=[],keywords=[],body=nodes,decorator_list=[])],type_ignores=[]));exec(compile(tree,'installed-session-contract','exec'),ns);return ns['Calendar'].expected_market_session()
 finally:sys.path.pop(0)
def rows_by_date(root):
 out={}
 for p in root.glob('*.csv'):
  with p.open(encoding='utf-8-sig',newline='') as f:
   rows=list(csv.DictReader(f));dates=[r['Date'][:10] for r in rows];require(len(dates)==len(set(dates)),'Duplicate official stock dates: '+p.name)
   out[p.name]={r['Date'][:10]:r for r in rows}
 return out

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--stage',choices=['Initial','Stopped','AfterRestart','Offline','OnlineRestored','OfficialRefresh'],default='Initial');ap.add_argument('--run',required=True);ap.add_argument('--runtime',default='');ap.add_argument('--pid',default='');ap.add_argument('--approve-manual-lifecycle',action='store_true');ap.add_argument('--approve-manual-offline',action='store_true');ap.add_argument('--gui-reviewed',action='store_true');args=ap.parse_args()
 run=Path(args.run).resolve();run.mkdir(parents=True,exist_ok=True);app=Path(os.environ['LOCALAPPDATA'])/'StockRecommendationEngine';engine=app/'native-engine-0.14.13'
 require(not run.is_relative_to(app.resolve()),'Report/backup must be outside installation')
 report=json.loads((run/'GATE_C_MACHINE_RESULTS.json').read_text()) if (run/'GATE_C_MACHINE_RESULTS.json').exists() else json.loads((BASE/'GATE_C_MACHINE_RESULTS.json').read_text())
 report.setdefault('stage_history',[]).append({'stage':args.stage,'started_utc':datetime.now(timezone.utc).isoformat(),'scope':'actual native collector invocation'})
 try:
  guard=json.loads((BASE/'source-guard.json').read_text());require(all((engine/n).is_file() and sha(engine/n)==h for n,h in guard.items()),'Installed source differs from accepted October23 baseline')
  require({p.name for p in (engine/'stock_app').glob('*.py')}=={Path(n).name for n in guard if n.startswith('stock_app/')},'Unexpected stock_app source inventory')
  record(report,'source_identity','PASS',str(len(guard))+' installed source hashes match; LIVE_DECISION_V1 preserved')
  dbs=[p for p in app.iterdir() if p.is_file() and p.suffix.lower() in ('.sqlite3','.db','.sqlite')];require((app/'phase81_validation.sqlite3') in dbs,'Paper V2 database missing')
  state={p.name:db_snapshot(p) for p in dbs};evidence_dir=app/'historical_replay_checkpoints_v2';evidence={p.name:sha(p) for p in evidence_dir.glob('*.complete.zlib')}
  if args.stage=='Stopped':
   require(args.approve_manual_lifecycle,'Stopped observation needs explicit manual-lifecycle approval flag')
   require((run/'baseline.json').exists(),'Initial capture/backup required first')
   old=json.loads((run/'baseline.json').read_text());require(state==old['databases'] and evidence==old['evidence'],'State changed during shutdown')
   try:get(int((app/'runtime-port.txt').read_text().strip()),'/api/health')
   except (OSError,ValueError):record(report,'desktop_shutdown','PASS','Operator closed normally; backend unavailable; all DB/evidence digests preserved','operator action plus machine observation')
   else:raise InvariantError('SRE backend still responding; shutdown not complete')
   write(run/'stopped.json',{'observed_utc':datetime.now(timezone.utc).isoformat()});return
  port=int((app/'runtime-port.txt').read_text().strip());health=get(port,'/api/health');source=get(port,'/api/data-source');ev=get(port,'/api/validation/historical-evidence')
  require(Path(health['code_root']).resolve()==engine.resolve() and health['decision_authority']=='LIVE_DECISION_V1','Wrong live GUI identity/authority')
  require(Path(health['database']).resolve().parent==app.resolve(),'Unexpected production database root')
  require({r['requested_range']['start'] for r in ev['results'] if r['pit_completeness']=='COMPLETE' and r.get('replay_integrity_checked') and r['requested_range']['start']==r['requested_range']['end']}>=DAYS,'Recovered three current sessions missing; NO replay will be run')
  require(ev['complete_replays']==3 and ev['stale_replays']==15 and ev['invalid_replays']==0 and len(evidence)==18,'Current evidence no longer matches confirmed baseline; investigate, do not rerun')
  require({p.name:db_snapshot(p) for p in dbs}==state,'Read-only API navigation changed database rows')
  capture={'stage':args.stage,'health':health,'source':source,'evidence':ev,'pid':args.pid,'runtime':args.runtime,'at_utc':datetime.now(timezone.utc).isoformat()};write(run/(args.stage+'-capture.json'),capture)
  record(report,'current_replay_evidence','PASS','Three dates COMPLETE;15 STALE;0 INVALID;18 files; no replay requests')
  record(report,'readonly_navigation','PASS','Whitelisted health/data-source/evidence GETs leave all DB rows unchanged; Paper GET deliberately excluded')
  if args.stage=='Initial':
   require(not (run/'baseline.json').exists(),'Initial already captured; reuse this directory with later stages')
   summary=paper_summary(app/'phase81_validation.sqlite3');write(run/'PRIVATE_PAPER_BASELINE.json',summary)
   active=[p for p in summary['positions'] if p['state']!='CLOSED'];require({p['symbol']:p['qty'] for p in active}==report['expected_holdings'],'Unexpected existing holdings; stop without mutation')
   baseline={'databases':state,'evidence':evidence,'pid':args.pid,'source_guard':guard,'paper_digest':digest(summary)};write(run/'baseline.json',baseline)
   backup=run/'PRIVATE_BACKUP';backup.mkdir(exist_ok=False)
   for p in dbs:backup_db(p,backup/p.name)
   record(report,'sqlite_backup','PASS','SQLite online backup API from mode=ro includes committed WAL state; each backup integrity/schema/rows checked')
   # Copy source/data without dependencies or nested prior backups. All exclusions explicit.
   skip=('.git','node_modules','__pycache__','.replay-v10-deps','.venv','venv')
   source_files=guarded_copy(engine,backup/'engine',skip)
   state_skip=tuple(p.name for p in dbs)+tuple(p.name+s for p in dbs for s in ('-wal','-shm','-journal'))+skip
   app_files=guarded_copy(app,backup/'app-state',state_skip)
   write(backup/'manifest.json',{'engine':source_files,'app-state':app_files,'database_mode':'consistent SQLite backups; live WAL not mixed into restored backups','excluded':list(skip),'runtime_binaries_included':False})
   require({p.name:db_snapshot(p) for p in dbs}==state and {p.name:sha(p) for p in evidence_dir.glob('*.complete.zlib')}==evidence,'Live data changed during backup')
   record(report,'source_history_backup','PASS',str(len(source_files))+' engine source/data files hash-copied; runtime/prior backup exclusions listed')
   restored=run/'PRIVATE_RESTORE';shutil.copytree(backup,restored)
   for p in dbs:require(db_snapshot(restored/p.name)==state[p.name],'Restore accounting differs')
   require(filemap(restored/'engine')==source_files and filemap(restored/'app-state')==app_files,'Restored source/evidence differs')
   record(report,'restore_accounting','PASS','Separate restore matches all DB tables, position identities, journals, NAV, cash and captured source/state files')
   record(report,'evidence_backup','PASS','All18 current/stale completed files preserved; research/cache copied without deletion')
   record(report,'holdings_preserved','PASS','Expected holdings, identities and every database row preserved; private baseline retained')
   try:
    meta=runtime_inventory(args.runtime,engine,run);record(report,'runtime_inventory','PASS','Actual listening-process executable/version/package metadata/native DLL hashes recorded; no dependency reinstall')
   except Exception as e:record(report,'runtime_inventory','BLOCKED',str(e))
   from source_contract_checks import check
   result=check(restored/'engine/stock_app/official_daily_refresh.py');write(run/'OFFICIAL_SOURCE_CONTRACT_REPRODUCTION.json',result)
   record(report,'verified_row_preservation',result['no_silent_verified_row_replacement'],str(result['same_session_conflicts_replaced'])+' conflicting synthetic stock-session rows replaced; isolated captured-source test','isolated source module')
   record(report,'official_failure_handling',result['failure_handling'],'Synthetic unavailable response does not change rows','isolated source module')
   record(report,'official_retry','PASS' if result['identical_row_retry_idempotent'] else 'FAIL','Identical synthetic input preserves CSV rows; live retry unexecuted','isolated source module')
   record(report,'no_unapproved_fallback','PASS' if result['automatic_yfinance_fallback'] is False else 'FAIL','Official-refresh source and synthetic response forbid automatic yfinance','source contract test')
   # Missing original research artifacts are never fabricated.
   required=['DECISION_ENTRY_TIMING_AUDIT.json','P3_HARD_POISON_AUDIT.json','BENCHMARK_ALIGNMENT_REPORT.csv','FUNDAMENTAL_ASOF_ALIGNMENT_REPORT.csv','P3_HORIZON_ELIGIBILITY.json','COMBINED_MODEL_READINESS.json']
   missing=[n for n in required if not (engine/'outputs/Leg5_Official_Source_Access_Recovery'/n).exists()];record(report,'historical_report_artifacts','BLOCKED' if missing else 'BLOCKED','Missing original artifacts: '+', '.join(missing) if missing else 'Original artifacts present; semantic validators must still run')
  else:
   old=json.loads((run/'baseline.json').read_text());require(state==old['databases'] and evidence==old['evidence'],'Financial/research data changed since Initial; no automatic repair')
   if args.stage=='AfterRestart':
    require(args.approve_manual_lifecycle and (run/'stopped.json').exists(),'Need approved manual normal close and Stopped observation first')
    require(args.pid and args.pid!=old['pid'],'No independent GUI backend process restart observed')
    record(report,'desktop_launch','PASS','Operator launched normal installed shortcut; different live backend PID observed','operator action plus machine observation');record(report,'desktop_restart','PASS','Three sessions, all DB rows and evidence unchanged after stopped interval and new PID')
    record(report,'no_duplicate_activity','PASS','Every order/fill/journal/session-commit row unchanged across restart')
    if args.gui_reviewed:record(report,'gui_backend_agreement','PASS','Operator reviewed GUI holdings/recommendations/evidence; backend/financial snapshot agrees','operator-attested visual check plus machine snapshot')
   elif args.stage in ('Offline','OnlineRestored'):
    require(args.approve_manual_offline,'Network testing requires explicit manual-offline approval; script changes no adapters/firewall')
    probes={}
    for host in ('www.nseindia.com','nsearchives.nseindia.com','www.niftyindices.com'):
     try:
      with socket.create_connection((host,443),timeout=3):probes[host]=True
     except OSError:probes[host]=False
    write(run/(args.stage+'-network-probes.json'),probes)
    if args.stage=='Offline':
     require(not any(probes.values()),'External connectivity still observed; not an offline test')
     online_pid=json.loads((run/'AfterRestart-capture.json').read_text())['pid'] if (run/'AfterRestart-capture.json').exists() else old['pid']
     require(args.pid and args.pid!=online_pid,'Offline startup needs a new backend process after the latest online capture')
     record(report,'offline_backend','PASS','Loopback APIs available with operator-disconnected external access; three official hosts unreachable','operator network declaration plus probes')
     if args.gui_reviewed:record(report,'offline_gui_cached_views','PASS','Operator saw cached recommendations,holdings,research and honest freshness labels; DB/evidence unchanged','operator-attested visual check plus snapshot')
     record(report,'offline_financial_preservation','PASS','All financial/research tables and18 completed file hashes unchanged')
    else:
     require(any(probes.values()),'Connectivity not demonstrated restored');record(report,'connectivity_restored','PASS','Operator restored original connection; official-host TCP reachable','operator plus machine network probe')
   elif args.stage=='OfficialRefresh':
    require((run/'PRIVATE_RESTORE/engine').exists(),'Initial isolated restore required');require((run/'OnlineRestored-capture.json').exists(),'Restore normal connectivity before official retrieval')
    clone=run/'PRIVATE_OFFICIAL_PROBE';shutil.copytree(run/'PRIVATE_RESTORE/engine',clone)
    active=source.get('active') or {};roots=active.get('cache_roots') or [];require(len(roots)==1,'Unexpected official cache root layout')
    relative=Path(roots[0]).resolve().relative_to(engine.resolve());cache=clone/relative
    expected=expected_from_source(clone);write(run/'OFFICIAL_EXPECTED_SESSION.json',expected);session=expected['expected_market_session']
    before=rows_by_date(cache)
    spec=importlib.util.spec_from_file_location('isolated_official_refresh',clone/'stock_app/official_daily_refresh.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    start=time.monotonic();refresh=m.refresh_official_session([str(cache)],session);write(run/'OFFICIAL_REAL_RETRIEVAL.json',{'wall_seconds':time.monotonic()-start,'result':refresh,'scope':'real network; isolated cache only'})
    if refresh['status']!='REFRESHED_AND_VERIFIED':record(report,'official_real_retrieval','BLOCKED','Actual official request: '+refresh['status']+'; '+str(refresh.get('reason_detail')),'real network to isolated cache');return
    after=rows_by_date(cache);changed=[n+':'+d for n,rows in before.items() for d,row in rows.items() if after.get(n,{}).get(d)!=row]
    record(report,'official_real_retrieval','PASS','Actual NSE response persisted/reread ONLY on isolated copy','real network to isolated cache')
    record(report,'official_full_coverage','PASS' if len([n for n in after if n.endswith('.NS.csv') and session in after[n]])==200 and session in after.get('INDEX_NSEI.csv',{}) else 'FAIL','Require all200 stock rows plus index for actual expected session','real isolated retrieval')
    record(report,'verified_row_preservation','FAIL' if changed else 'FAIL','Actual revised prior rows: '+str(len(changed))+'; synthetic conflicting-response safety failure remains unresolved','real plus controlled isolated tests')
    write(run/'OFFICIAL_CHANGED_PRIOR_ROWS.json',changed)
    record(report,'official_calendar','PASS','Exact installed calendar and18:00 IST cutoff selected '+session+'; no override')
    record(report,'downstream_eligibility','BLOCKED','New data is isolated; production daily workflow intentionally not run')
  require({p.name:db_snapshot(p) for p in dbs}==state,'Acceptance mutated live database rows')
 except Exception as e:
  record(report,'execution_invariant','FAIL' if isinstance(e,InvariantError) else 'BLOCKED',str(e));report['stop_reason']=str(e);raise
 finally:save_report(run,report)
if __name__=='__main__':main()
