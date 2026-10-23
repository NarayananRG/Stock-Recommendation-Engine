"""Native installed-source continuation. No network and no financial DB writes outside copies."""
from pathlib import Path
import argparse,json,hashlib,os,sys,time,shutil,sqlite3,socket,subprocess,zipfile,traceback,csv,gc
sys.dont_write_bytecode=True
DAYS=('2026-10-09','2026-10-15','2026-10-19')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(v,indent=2,default=str),encoding='utf-8');os.replace(tmp,p)
def safe_name(n):
 p=Path(n)
 if p.name!=n or len(n)!=78 or not n.endswith('.complete.zlib') or any(c not in '0123456789abcdef' for c in n[:64]):raise ValueError('UNSAFE_RESULT_NAME')
 return n
def publish(src,dest,receipt,candidates):
 """Only add native validated results; never overwrite an existing file."""
 dest=Path(dest);dest.mkdir(parents=True,exist_ok=True);plan=[]
 for n in candidates:
  safe_name(n);p=dest/n;h=sha(Path(src)/n)
  if p.exists():
   if sha(p)!=h:raise RuntimeError('EXISTING_RESULT_COLLISION: '+n)
   plan.append({'name':n,'sha256':h,'preexisting':True});continue
  plan.append({'name':n,'sha256':h,'preexisting':False})
 write(receipt,{'destination':str(dest.resolve()),'plan':plan,'status':'PLANNED','published':[]})
 for item in plan:
  if item['preexisting']:continue
  n=item['name'];p=dest/n
  # Exclusive create prevents race/collision. Partial writes are retained for guarded rollback.
  import uuid
  tmp=dest/('.sre-publish-'+uuid.uuid4().hex+'.tmp')
  try:
   with tmp.open('xb') as f:f.write((Path(src)/n).read_bytes());f.flush();os.fsync(f.fileno())
   os.link(tmp,p)  # Atomic exclusive publication on NTFS; never replace.
  finally:
   if tmp.exists():tmp.unlink()
  if sha(p)!=item['sha256']:raise RuntimeError('PUBLICATION_HASH_MISMATCH')
  r=json.loads(Path(receipt).read_text());r['published'].append(n);write(receipt,r)
 r=json.loads(Path(receipt).read_text());r['status']='PUBLISHED';write(receipt,r);return r

def rollback(receipt,expected_destination):
 r=json.loads(Path(receipt).read_text());dest=Path(r['destination']).resolve()
 if dest!=Path(expected_destination).resolve():raise RuntimeError('ROLLBACK_DESTINATION_MISMATCH')
 quarantine=Path(receipt).parent/'rolled-back-results';quarantine.mkdir(exist_ok=True)
 for x in r['plan']:
  safe_name(x['name'])
  if x['preexisting']:continue
  p=dest/x['name']
  if not p.exists():continue
  if sha(p)!=x['sha256']:raise RuntimeError('ROLLBACK_CONTENT_CHANGED: '+x['name'])
  target=quarantine/x['name']
  if target.exists():raise RuntimeError('ROLLBACK_QUARANTINE_COLLISION')
  p.rename(target)
 r['status']='ROLLED_BACK_NEW_RESULTS_ONLY';write(receipt,r);return r

def paper(path):
 c=sqlite3.connect('file:'+str(Path(path).resolve())+'?mode=ro&immutable=1',uri=True);d={}
 for (n,) in c.execute("select name from sqlite_master where type='table' and name like 'paper%'"):
  vals=c.execute('select * from "'+n.replace('"','""')+'"').fetchall();d[n]={'rows':len(vals),'sha256':hashlib.sha256(json.dumps(sorted(vals,key=repr),default=str).encode()).hexdigest()}
 c.close();return d

def source_guard(engine,manifest):
 for rel,h in manifest.items():
  p=engine/rel
  if not p.is_file() or sha(p)!=h:raise RuntimeError('INSTALLED_SOURCE_VERSION_MISMATCH: '+rel)

def run(a):
 engine=Path(a.engine).resolve();app=Path(a.app).resolve();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
 guard=json.loads(Path(a.guard).read_text());source_guard(engine,guard)
 if out==app or out.is_relative_to(app):raise RuntimeError('OUTPUT_MUST_BE_OUTSIDE_APPLICATION')
 if a.mode=='rollback':return rollback(out/'publication.json',app/'historical_replay_checkpoints_v2')
 if a.mode=='restart':
  state=out/'state'
 else:
  capture=Path(a.capture).resolve();state=out/'state';shutil.copytree(capture/'application-state',state)
  for l in (capture/'CAPTURE_CHECKSUMS.sha256').read_text(encoding='utf-8-sig').splitlines():
   h,n=l.split('  ',1);p=(capture/n).resolve()
   if not p.is_relative_to(capture) or sha(p)!=h:raise RuntimeError('CAPTURE_HASH_MISMATCH: '+n)
 network=[]
 def blocked(*x,**k):network.append(str(x)[:100]);raise RuntimeError('NETWORK_DISABLED')
 socket.socket.connect=blocked;socket.socket.connect_ex=blocked;socket.create_connection=blocked
 os.environ['STOCK_REAL_DATA_REPO_ROOT']=str(engine);os.environ['STOCK_APP_REPO_ROOT']=str(engine);os.environ['STOCK_APP_DATA_DIR']=str(state)
 # No overridden date/publication clock: actual eligible-session logic remains authoritative.
 os.environ.pop('SRE_EXPECTED_SESSION_NOW',None)
 sys.path.insert(0,str(engine));private=engine/'.replay-v10-deps'
 if private.exists():sys.path.insert(0,str(private))
 from modern_ui.api import ModernAppContext
 from stock_app.replay_v10 import source_signature,market_signature,digest,RUNTIME
 from stock_app.replay_v10_final import valid_result,completed_evidence,VerifiedCheckpointStore
 ctx=ModernAppContext(engine,state)
 def identity():return (source_signature(engine,ctx.data_repo_root),market_signature(ctx.prices),digest([(ctx.data_source_status().get('active') or {}).get('members'),ctx.allocator.sectors]))
 first_identity=identity()
 if a.mode=='restart':
  found=[]
  for day in DAYS:
   r=ctx.phase81_historical_replay('CUSTOM',100000.,'NIFTY 50',day,day,10.,5.)
   assert r['replay_cache_status']=='COMPLETE_RESULT_REUSED' and r['replay_request_stats']['simulation_runs']==0 and r['replay_request_stats']['scored_input_calculations']==0
   found.append({'date':day,'cache':r['replay_cache_status'],'stats':r['replay_request_stats']})
  write(out/'restart.json',{'status':'PASS','results':found,'runtime':RUNTIME});return
 before=paper(state/'phase81_validation.sqlite3');write(out/'paper-before.json',before)
 old_dir=Path(a.capture)/'application-state/historical_replay_checkpoints_v2';originals={p.name:sha(p) for p in old_dir.glob('*.complete.zlib')}
 if len(originals)<12:raise RuntimeError('EXPECTED_AT_LEAST_TWELVE_PRIOR_RESULTS')
 # Raw DB/sidecar byte hashes: no original DB is opened by SQLite.
 financial={p.name:sha(p) for p in app.iterdir() if p.is_file() and any(x in p.name.lower() for x in ('.sqlite3','.db'))}
 before_evidence=completed_evidence(app/'historical_replay_checkpoints_v2',*first_identity);write(out/'evidence-before.json',before_evidence)
 results=[];candidates=[]
 for day in DAYS:
  for kind in ['recovery','identical']:
   started=time.perf_counter();r=ctx.phase81_historical_replay('CUSTOM',100000.,'NIFTY 50',day,day,10.,5.);wall=time.perf_counter()-started
   att=r.get('v10_acceptance') or {};assert valid_result(r,att.get('contract')) and r['pit_completeness']=='COMPLETE' and r['sessions_replayed']==1
   if kind=='identical':assert r['replay_cache_status']=='COMPLETE_RESULT_REUSED' and r['replay_request_stats']['simulation_runs']==0 and r['replay_request_stats']['scored_input_calculations']==0
   write(out/(day+'-'+kind+'.json'),r);results.append({'date':day,'kind':kind,'wall_seconds':wall,'status':r['replay_cache_status'],'stats':r['replay_request_stats']})
   if kind=='recovery':candidates.append(att['key']+'.complete.zlib')
 assert identity()==first_identity
 cmd=[sys.executable,str(Path(__file__).resolve()),'--mode','restart','--engine',str(engine),'--app',str(app),'--output',str(out),'--guard',a.guard]
 restart=subprocess.run(cmd,timeout=180,capture_output=True,text=True);(out/'restart-process.log').write_text(restart.stdout+restart.stderr)
 if restart.returncode:raise RuntimeError('RESTART_REUSE_FAILED')
 # Bounded interrupted test. Only copied state is modified.
 checkpoint={'status':'BLOCKED','reason':'NOT_EXECUTED'}
 try:
  seq={}
  for kind in ['continuous','interrupted']:
   target=out/kind;shutil.copytree(state,target);tctx=ModernAppContext(engine,target)
   if kind=='interrupted':
    original=tctx._validation_pit_session;count=[0]
    def interruption(*x,**k):
     count[0]+=1
     if count[0]==3:raise RuntimeError('CONTROLLED_INTERRUPTION')
     return original(*x,**k)
    tctx._validation_pit_session=interruption
    try:tctx.phase81_historical_replay('CUSTOM',100000.,'NIFTY 50','2026-10-15','2026-10-22',10.,5.)
    except RuntimeError as e:
     if str(e)!='CONTROLLED_INTERRUPTION':raise
    else:raise RuntimeError('INTERRUPTION_NOT_EXERCISED_EXISTING_RESULT_MAY_HAVE_BEEN_REUSED')
    tctx=ModernAppContext(engine,target)
   seq[kind]=tctx.phase81_historical_replay('CUSTOM',100000.,'NIFTY 50','2026-10-15','2026-10-22',10.,5.)
   write(out/(kind+'.json'),seq[kind]);assert paper(target/'phase81_validation.sqlite3')==before
  fields=['metrics','series','trades','coverage','execution_assumptions','sessions_replayed','sessions_excluded']
  checks={f:seq['continuous'][f]==seq['interrupted'][f] for f in fields};assert all(checks.values()) and seq['interrupted']['replay_cache_status']=='RESUMED'
  checkpoint={'status':'PASS','checks':checks,'scope':'Native Windows controlled exception on isolated copies, not forced OS kill'}
 except Exception as e:checkpoint={'status':'BLOCKED' if 'INTERRUPTION_NOT_EXERCISED' in str(e) else 'FAIL','reason':str(e)}
 write(out/'checkpoint-test.json',checkpoint)
 # Restore rehearsal on a new copy. No active state restoration.
 restored=out/'restore-rehearsal';shutil.copytree(state,restored);rctx=ModernAppContext(engine,restored);assert paper(restored/'phase81_validation.sqlite3')==before
 restore={'status':'PASS','scope':'Private copy restore/application-context initialization and paper-content comparison; no GUI/installer claim'};write(out/'restore.json',restore)
 operational={}
 for name,fn in [('daily_status',ctx.post_close_daily_status),('holdings',ctx.live_today_summary),('paper',ctx.phase81_paper_status)]:
  try:operational[name]={'status':'PASS','value':fn()}
  except Exception as e:operational[name]={'status':'BLOCKED','error':str(e)}
 # Same-session processing can require fresh data. Offline refusal is not fabricated success.
 try:
  one=ctx.run_post_close_daily_flow(force=False);mid=paper(state/'phase81_validation.sqlite3');two=ctx.run_post_close_daily_flow(force=False);after=paper(state/'phase81_validation.sqlite3')
  operational['duplicate_workflow']={'status':'PASS' if mid==after else 'FAIL','first':one,'second':two,'paper_tables_same_on_repeat':mid==after}
 except Exception as e:operational['duplicate_workflow']={'status':'BLOCKED','reason':str(e)}
 write(out/'operational.json',operational)
 # Read-only metric coverage from current native context; unavailable values stay unavailable.
 metric_rows=[];profile_counts={}
 active=ctx.data_source_status().get('active') or {};members=active.get('members') or []
 for member in members:
  symbol=member['symbol'];bars=ctx.prices.history(symbol,limit=2)
  if not bars:continue
  f=ctx.fundamental_v3_context(symbol,float(bars[-1]['close']),bars[-1]['date']);status=f.get('status');profile_counts[status]=profile_counts.get(status,0)+1
  for metric,val in f.get('feature_coverage',{}).items():
   value=val.get('value');metric_rows.append({'symbol':symbol,'session':bars[-1]['date'],'metric':metric,'value':json.dumps(value),'profile_status':status,'classification':'AVAILABLE_AND_VERIFIED' if value not in (None,'',{}) else 'PIT_BLOCKED' if status=='NO_PRIOR_FUNDAMENTALS_BY_CUTOFF' else 'STALE_OR_INSUFFICIENT_EVIDENCE','scope':'Existing accepted panel; no original filing retrieval or new mapping fix'})
 if metric_rows:
  with (out/'NATIVE_FEATURE_COVERAGE.csv').open('w',newline='',encoding='utf-8') as h:w=csv.DictWriter(h,fieldnames=metric_rows[0]);w.writeheader();w.writerows(metric_rows)
 write(out/'fundamental-summary.json',{'profile_counts':profile_counts,'profile_taxonomy_not_prior_gate_a_readiness':True,'numerical_changes':0,'verified_mapping_defects_corrected':0,'new_filing_retrieval':'NOT_PERFORMED'})
 # Daily workflow may legitimately update copied state. It never writes actual app financial files.
 if paper(state/'phase81_validation.sqlite3')!=before:operational['paper_clone_changed']={'status':'BLOCKED','reason':'Daily workflow changed isolated paper state; publication withheld'}
 unchanged={n:sha(app/n)==h for n,h in financial.items()};assert all(unchanged.values())
 for n,h in originals.items():assert sha(app/'historical_replay_checkpoints_v2'/n)==h
 source_guard(engine,guard);assert identity()==first_identity
 # Only single-session results are published, after all critical recovery checks pass.
 allow=checkpoint['status']=='PASS' and paper(state/'phase81_validation.sqlite3')==before and operational.get('duplicate_workflow',{}).get('status')!='FAIL'
 publication={'status':'BLOCKED','reason':'Required clone/checkpoint/paper preservation checks did not all pass'}
 if allow:
  publication=publish(state/'historical_replay_checkpoints_v2',app/'historical_replay_checkpoints_v2',out/'publication.json',candidates)
  try:
   evidence=completed_evidence(app/'historical_replay_checkpoints_v2',*first_identity);write(out/'evidence-after.json',evidence)
   assert evidence['complete_replays']>=3
  except Exception:
   rollback(out/'publication.json',app/'historical_replay_checkpoints_v2');raise
 else:write(out/'evidence-after.json',before_evidence)
 final={'status':'PASS_NATIVE_REPLAY_RECOVERY' if publication.get('status')=='PUBLISHED' else 'BLOCKED','platform':sys.platform,'runtime':RUNTIME,'source_market_context':first_identity,'results':results,'paper_tables_compared':len(before),'original_financial_files_unchanged':unchanged,'old_results_preserved':len(originals),'checkpoint':checkpoint,'restore':restore,'publication':publication,'network_attempts_blocked':network,'gate_a':'BLOCKED_FINAL_REVIEW','gate_b_strategy':'NOT_VALIDATED','gate_c':'BLOCKED_GUI_FRESH_RETRIEVAL_AND_PORTABILITY','desktop_gui':'NOT_EXECUTED','fresh_official_fetch':'NOT_EXECUTED','actual_gui_interpreter_match':'NOT_INDEPENDENTLY_VERIFIED','live_recommendation_rules_changed':False}
 write(out/'ACCEPTANCE.json',final)
 lines=['# Windows continuation acceptance', '', 'Result: '+final['status'], '', 'Executed platform: '+sys.platform, '','- Native replay source/data/runtime identity and result reuse: see ACCEPTANCE.json and restart.json.','- Publication contains only three native validated complete files; no original research SQL or portfolio database is replaced.','- Desktop GUI startup/shutdown, fresh official retrieval and complete executable portability: BLOCKED.','- Controlled clone interruption and private copy restore: '+checkpoint['status']+' / '+restore['status']+'.','- Strategy usefulness remains NOT VALIDATED.','', 'This report is generated on the executing computer. A passing backend test is not full Gate C acceptance.']
 (out/'ACCEPTANCE.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 return final
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--mode',choices=['run','restart','rollback'],default='run');p.add_argument('--engine',required=True);p.add_argument('--app',required=True);p.add_argument('--output',required=True);p.add_argument('--guard',required=True);p.add_argument('--capture');a=p.parse_args()
 try:run(a)
 except Exception as e:
  write(Path(a.output)/'ACCEPTANCE_ERROR.json',{'status':'BLOCKED','error':str(e),'traceback':traceback.format_exc(),'not_claimed':'No full Gate C or profitability acceptance'})
  # Publication receipt is write-ahead. Do not erase partial artifacts or unconditionally roll back changed bytes.
  print(traceback.format_exc(),file=sys.stderr);sys.exit(1)
