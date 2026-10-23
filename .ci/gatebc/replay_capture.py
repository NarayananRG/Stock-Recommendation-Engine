"""Read-only analysis of private snapshot copies. No app context, network or trades."""
from pathlib import Path
from types import SimpleNamespace
import json,hashlib,zlib,csv,sys,datetime,importlib.metadata as metadata
MAX_JSON=64*1024*1024

def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False,default=str).encode()).hexdigest()
def file_hash(p):
 h=hashlib.sha256()
 with Path(p).open('rb')as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def unpack(p):
 d=zlib.decompressobj();raw=d.decompress(p.read_bytes(),MAX_JSON+1)
 if len(raw)>MAX_JSON or d.unconsumed_tail or not d.eof or d.unused_data:raise ValueError('BOUNDED_ZLIB_VALIDATION_FAILED')
 return json.loads(raw)
def inspect_replays(root):
 records=[];errors=[]
 for p in sorted((root/'application-state/historical_replay_checkpoints_v2').glob('*.complete.zlib')):
  base={'file':p.relative_to(root).as_posix(),'file_sha256':file_hash(p),'bytes':p.stat().st_size}
  try:
   obj=unpack(p);r=obj['value'];proof=r.get('v10_acceptance')or{};c=proof.get('contract')or{};config=c.get('config')or{};coverage=r.get('coverage')or[]
   wrapper=obj.get('schema')=='SRE_REPLAY_CHECKPOINT_V2'and obj.get('key')==p.name.split('.')[0]
   payload={k:v for k,v in r.items()if k not in ('v10_acceptance','replay_cache_status','replay_request_stats','replay_input_cache_stats')}
   proof_ok=bool(proof)and proof.get('key')==digest(c)and proof.get('payload_sha256')==digest(payload)
   sessions=c.get('sessions')or[x.get('date')for x in coverage];span=r.get('requested_range')or{}
   records.append({**base,'wrapper_valid':wrapper,'attestation_present':bool(proof),'self_integrity_match':proof_ok,'historical_flag':r.get('pit_completeness'),'period':r.get('requested_period'),'range':span,'original_sessions':sessions,'replayed_sessions':r.get('sessions_replayed'),'source_fingerprint':r.get('replay_fundamental_source_fingerprint'),'market_fingerprint':r.get('replay_market_content_signature'),'context_fingerprint':r.get('replay_context_signature'),'runtime':c.get('runtime'),'config':config,'execution_assumptions':r.get('execution_assumptions'),'metrics':r.get('metrics'),'old_contract':c,'current_validation_status':'NOT_REVALIDATED; old COMPLETE flag alone is insufficient'})
  except Exception as e:errors.append({**base,'error':type(e).__name__+': '+str(e)[:250]})
 return {'records':records,'errors':errors,'complete_files':len(records)+len(errors),'attested_self_integrity_matches':sum(x['self_integrity_match']for x in records),'distinct_historically_complete_single_sessions':sorted({x['range'].get('start')for x in records if x['historical_flag']=='COMPLETE'and x['range'].get('start')and x['range'].get('start')==x['range'].get('end')}),'never_current_validated_by_this_inventory':True}

def native_fingerprints(original,manifest):
 # Import only hash-verified pure replay/feature modules, never ModernAppContext.
 # No class instances/cache construction. Prevent bytecode writes into originals.
 sys.dont_write_bytecode=True
 expected={**manifest['guard_files'],**{n:v['new_sha256']for n,v in manifest['files'].items()if n.endswith(('.py','.js','.json','.html','.css'))}}
 known={n:h for n,h in expected.items()if n.endswith('.py')and n.startswith(('stock_app/','modern_ui/'))}
 unknown=[p.relative_to(original).as_posix()for d in ['stock_app','modern_ui']for p in(original/d).glob('*.py')if p.relative_to(original).as_posix()not in known]
 bad=[n for n,h in known.items()if not(original/n).is_file()or file_hash(original/n)!=h]
 if bad or unknown:return {'status':'BLOCKED_UNRECOGNIZED_SOURCE','mismatches':bad,'unknown_modules':unknown}
 sys.path.insert(0,str(original))
 try:
  from stock_app.replay_v10 import source_signature,market_signature,RUNTIME
  source=source_signature(original,original)
  candidates=[]
  for parent in [original/'data/normalized/nse_official',original/'data/market_data']:
   if parent.is_dir():
    for folder in sorted({p.parent for p in parent.rglob('*.csv')}):
     candidates.append({'root':str(folder),'fingerprint':market_signature(SimpleNamespace(cache_roots=[folder]))})
  return {'status':'VERIFIED_PURE_MODULE_FINGERPRINTS','source_fingerprint':source,'runtime':RUNTIME,'market_root_candidates':candidates,'active_market_root_and_context_status':'Determine actual configured root/context from returned source/config; no app context was instantiated','originals_written':False}
 except Exception as e:return {'status':'BLOCKED_EXISTING_RUNTIME_IMPORT','error':type(e).__name__+': '+str(e)[:250]}

def audit_capture(root,original,manifest,compute_native=True):
 root=Path(root);original=Path(original);out=root/'gatebc-evidence';out.mkdir()
 inventory=inspect_replays(root);(out/'REPLAYS.json').write_text(json.dumps(inventory,indent=2))
 with(out/'REPLAYS.csv').open('w',newline='')as f:
  fields=['file','file_sha256','historical_flag','period','range','original_sessions','attestation_present','self_integrity_match','source_fingerprint','market_fingerprint','context_fingerprint']
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:json.dumps(r.get(k))if isinstance(r.get(k),(dict,list))else r.get(k)for k in fields}for r in inventory['records'])
 deltas=[]
 for n,v in manifest['files'].items():
  p=root/'engine'/n;actual=file_hash(p)if p.is_file()else None
  deltas.append({'file':n,'pre_correction_sha256':v['old_sha256'],'correction_sha256':v['new_sha256'],'captured_sha256':actual,'correction_match':actual==v['new_sha256'],'classification':'KNOWN_CORRECTION_EXACT'if actual==v['new_sha256']else'CURRENT_DIFF_REQUIRES_REVIEW'})
 (out/'CORRECTION_DEPENDENCIES.json').write_text(json.dumps(deltas,indent=2))
 fingerprints=native_fingerprints(original,manifest)if compute_native else{'status':'NOT_COMPUTED_IN_OFFLINE_FIXTURE'}
 for r in inventory['records']:
  r['source_matches_native']=r['source_fingerprint']==fingerprints.get('source_fingerprint')if fingerprints.get('source_fingerprint')else None
  r['matching_market_candidates']=[x['root']for x in fingerprints.get('market_root_candidates',[])if x['fingerprint']==r['market_fingerprint']]
  r['runtime_matches_native']=r.get('runtime')==fingerprints.get('runtime')if fingerprints.get('runtime')else None
 (out/'NATIVE_FINGERPRINTS.json').write_text(json.dumps(fingerprints,indent=2));(out/'REPLAYS.json').write_text(json.dumps(inventory,indent=2))
 # Copies are private; readonly immutable SQL inventory never opens live DBs.
 import sqlite3
 dbs=[]
 for p in (root/'application-state').glob('*.sqlite3'):
  with sqlite3.connect(p.resolve().as_uri()+'?mode=ro&immutable=1',uri=True)as c:
   ts=[x[0]for x in c.execute("select name from sqlite_master where type='table'")];dbs.append({'file':p.name,'tables':ts,'integrity':c.execute('pragma quick_check').fetchone()[0]})
 (out/'SQLITE_TABLES.json').write_text(json.dumps(dbs,indent=2))
 # Inventory binaries/versions/licenses only. Binary copies are deliberately not redistributed.
 binary=[];licenses=[];seen=set();count=0
 for p in original.rglob('*'):
  if not p.is_file()or any(x.startswith(('.oct31-','.gatea-','.replay-v10-backup','.replay-v10-final-backup'))for x in p.relative_to(original).parts):continue
  if p.suffix.lower()in('.exe','.dll','.pyd','.whl'):
   binary.append({'path':str(p),'bytes':p.stat().st_size,'sha256':file_hash(p)})
  if p.name.lower().startswith(('license','licence','copying','notice'))and p.stat().st_size<1024*1024:licenses.append({'path':str(p),'sha256':file_hash(p)})
 versions=[]
 for runtime in [original/'.replay-v10-deps',original/'.replay-v10-final-deps']:
  for d in metadata.distributions(path=[str(runtime)]):versions.append({'runtime':str(runtime),'name':d.metadata.get('Name'),'version':d.version})
 versions += [{'runtime':'collector_interpreter_visible_distribution','name':d.metadata.get('Name'),'version':d.version}for d in metadata.distributions()]
 (out/'RUNTIME_PORTABILITY.json').write_text(json.dumps({'python_executable':sys.executable,'python_version':sys.version,'binary_files':binary,'license_files':licenses,'distributions':versions,'binary_payload_included':False,'blocker':'Actual launcher/complete runtime binaries and redistribution permissions require separate verification; inventory is not portable-release acceptance'},indent=2))
 summary={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'snapshot_only':True,'no_replay_executed':True,'no_network':True,'no_app_context_or_api_called':True,'original_databases_opened_by_sqlite':False,'records_observed':inventory['complete_files'],'distinct_historically_complete_single_sessions':inventory['distinct_historically_complete_single_sessions'],'native_fingerprint_status':fingerprints['status'],'gate_b_recovery':'BLOCKED_PENDING_CURRENT_CAPTURE_REVIEW_AND_GUARDED_THREE_SESSION_EXECUTION','gate_c':'BLOCKED_ACTUAL_MACHINE_ACCEPTANCE_NOT_EXECUTED'}
 (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2));return summary
