"""GET-only GUI identity inspection. Does not import SRE or run replay/portfolio code."""
from pathlib import Path
import json,hashlib,zlib,urllib.request,urllib.parse,argparse,zipfile,csv,sys
LIMIT=64*1024*1024
DAYS=('2026-10-09','2026-10-15','2026-10-19')
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False,default=str).encode()).hexdigest()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def unpack(p):
 data=Path(p).read_bytes()
 if len(data)>LIMIT:raise ValueError('COMPRESSED_OBJECT_TOO_LARGE')
 d=zlib.decompressobj();raw=d.decompress(data,LIMIT+1)
 if len(raw)>LIMIT or not d.eof or d.unconsumed_tail or d.unused_data:raise ValueError('UNSAFE_OR_INCOMPLETE_ZLIB')
 return json.loads(raw)
def inspect_file(p):
 row={'file':p.name,'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size}
 try:
  obj=unpack(p);r=obj['value'];proof=r.get('v10_acceptance') or {};c=proof.get('contract') or {}
  row.update(range=r.get('requested_range'),period=r.get('requested_period'),replay_id=r.get('replay_id'),pit=r.get('pit_completeness'),source=r.get('replay_fundamental_source_fingerprint'),market=r.get('replay_market_content_signature'),context=r.get('replay_context_signature'),runtime=c.get('runtime'),config=c.get('config'),sessions=c.get('sessions'),contract=c,proof_key=proof.get('key'),proof_present=bool(proof),wrapper_key_matches=obj.get('key')==p.name.split('.')[0],schema=obj.get('schema'))
  payload={k:v for k,v in r.items() if k not in ('v10_acceptance','replay_cache_status','replay_request_stats','replay_input_cache_stats')}
  row['self_digest_matches']=bool(proof) and proof.get('key')==digest(c) and proof.get('payload_sha256')==digest(payload)
 except Exception as e:row['read_error']=str(e)
 return row
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**k):raise RuntimeError('HTTP_REDIRECT_REFUSED')
def get(base,route):
 url=base+route;p=urllib.parse.urlparse(url)
 if p.scheme!='http' or p.hostname not in ('127.0.0.1','localhost','::1') or p.username or p.password:raise ValueError('LOOPBACK_HTTP_ONLY')
 op=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
 with op.open(urllib.request.Request(url,method='GET'),timeout=30) as f:
  raw=f.read(LIMIT+1)
  if len(raw)>LIMIT:raise ValueError('API_RESPONSE_TOO_LARGE')
  return json.loads(raw.decode('utf-8-sig'))
def identity(r):return {k:r.get(k) for k in ['source','market','context']}
def analyze(rows,diag,prior):
 anchors=diag.get('examples',{}).get('CURRENT_INTEGRITY_CHECKED',[]);found=[r for r in rows if r['file'] in anchors]
 current=None
 if found and len({digest(identity(r)) for r in found})==1:current=found[0]
 result={'current_anchor_files':[r['file'] for r in found],'current_identity':identity(current) if current else None,'current_runtime_from_gui_accepted_attestation':current.get('runtime') if current else None,'comparisons':[]}
 for date,p in prior.items():
  old=(p.get('v10_acceptance') or {});key=old.get('key');match=next((r for r in rows if r['file']==str(key)+'.complete.zlib'),None)
  item={'date':date,'recovered_key':key,'original_replay_id':p.get('replay_id'),'present_in_gui_evidence_directory':bool(match)}
  if match:
   item.update(file=match['file'],self_digest_matches=match.get('self_digest_matches'),range=match.get('range'),replay_id=match.get('replay_id'),recovered_runtime=match.get('runtime'),config=match.get('config'))
   if current:
    item['fingerprint_match']={k:match.get(k)==current.get(k) for k in ['source','market','context']}
    item['runtime_match']=match.get('runtime')==current.get('runtime')
    item['classification']='SAME_CURRENT_GLOBAL_IDENTITY_REQUIRES_NATIVE_VALIDATION_REVIEW' if all(item['fingerprint_match'].values()) else 'PRESENT_BUT_STALE_GLOBAL_IDENTITY_MISMATCH'
  else:item['classification']='NOT_IN_GUI_EVIDENCE_DIRECTORY_CHECK_PUBLISHED_DESTINATION'
  result['comparisons'].append(item)
 return result

def run(a):
 out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
 def save(n,v):(out/n).write_text(json.dumps(v,indent=2,default=str),encoding='utf-8')
 routes={'health':'/api/health','data-source':'/api/data-source','evidence-before':'/api/validation/historical-evidence','diagnostics':'/api/validation/gate-a-diagnostics'};api={}
 for name,route in routes.items():
  api[name]=get(a.base,route);save(name+'.json',api[name])
 health=api['health'];app=Path(health['database']).parent.resolve();code=Path(health['code_root']).resolve();directory=app/'historical_replay_checkpoints_v2'
 if out==app or out.is_relative_to(app):raise ValueError('OUTPUT_MUST_BE_OUTSIDE_APPLICATION_DATA')
 prior_dir=Path(a.recovery).resolve();prior={d:json.loads((prior_dir/(d+'-recovery.json')).read_text(encoding='utf-8-sig')) for d in DAYS}
 receipt=json.loads((prior_dir/'publication.json').read_text(encoding='utf-8-sig'));save('original-publication-receipt.json',receipt)
 rows=[inspect_file(p) for p in sorted(directory.glob('*.complete.zlib'))];save('all-replay-identities.json',rows)
 comparison=analyze(rows,api['diagnostics'],prior);comparison.update(gui_code_root=str(code),gui_data_root=health.get('repo_root'),gui_database=str(health['database']),gui_evidence_directory=str(directory),published_directory=receipt.get('destination'),publication_destination_matches_gui=Path(receipt['destination']).resolve()==directory.resolve(),current_endpoint_counts={k:api['evidence-before'].get(k) for k in ['complete_replays','stale_replays','partial_replays','invalid_replays']},endpoint_current_ranges=[r.get('requested_range') for r in api['evidence-before'].get('results',[])])
 guard=json.loads((prior_dir/'source-guard.json').read_text(encoding='utf-8-sig'));modules=[]
 for rel,expected in guard.items():
  p=code/rel;actual=sha(p) if p.is_file() else None;modules.append({'file':rel,'recovery_sha256':expected,'gui_disk_sha256':actual,'same':actual==expected})
 save('source-module-comparison.json',modules)
 # Compare current disk to the original recovery's verified input snapshot, if retained.
 changes=[];manifest=None;backups=sorted(prior_dir.glob('SRE-GateBC-ReadOnly-*.zip'))
 if len(backups)==1:
  with zipfile.ZipFile(backups[0]) as z:
   info=z.getinfo('snapshot-manifest.json')
   if info.file_size>LIMIT:raise ValueError('BACKUP_MANIFEST_TOO_LARGE')
   manifest=json.loads(z.read(info).decode('utf-8-sig'))
  comparison['original_engine_root']=manifest.get('source_engine')
  for r in manifest.get('source_files',[]):
   n=r['path']
   if not n.startswith('engine/'):continue
   rel=n[len('engine/'):];p=code/rel
   if any(x.startswith('.') for x in Path(rel).parts):continue
   if not (rel.startswith(('stock_app/','modern_ui/','data/','NextGen Research/','outputs/Leg5_Official_Source_Access_Recovery/'))):continue
   expected=r.get('source_sha256');actual=sha(p) if p.is_file() else None
   if expected!=actual:changes.append({'file':rel,'recovery_sha256':expected,'current_sha256':actual})
 comparison['original_input_manifest_available']=manifest is not None;comparison['changed_disk_input_files']=changes;comparison['source_guard_all_same']=all(r['same'] for r in modules)
 if manifest:
  original_records=[r for r in manifest.get('source_files',[]) if r['path'].startswith('application-state/historical_replay_checkpoints_v2/') and r['path'].endswith('.complete.zlib')]
  comparison['original_capture_records_preserved']={Path(r['path']).name:sha(directory/Path(r['path']).name)==r['source_sha256'] if (directory/Path(r['path']).name).is_file() else False for r in original_records}

 # Exact original publication bytes must remain untouched. This does not replace native full validity.
 comparison['published_file_hash_matches']={r['name']:sha(directory/r['name'])==r['sha256'] if (directory/r['name']).is_file() else False for r in receipt['plan']}
 before_hashes={r['file']:r['sha256'] for r in rows};end=get(a.base,'/api/validation/historical-evidence');save('evidence-after.json',end)
 comparison['endpoint_stable_during_capture']=api['evidence-before']==end
 comparison['replay_files_stable_during_capture']=all((directory/n).is_file() and sha(directory/n)==h for n,h in before_hashes.items()) and set(before_hashes)=={p.name for p in directory.glob('*.complete.zlib')}
 comparison['gate_c']='BLOCKED_PENDING_IDENTITY_RECONCILIATION_AND_THREE_SESSION_GUI_ACCEPTANCE';comparison['no_replay_or_post_or_application_import']=True
 save('COMPARISON.json',comparison)
 (out/'READ_ME.md').write_text('# GUI replay recognition inspection\n\nGET-only capture. No replay, POST, application import, database access or validation relaxation.\n\nRead COMPARISON.json for current GUI-accepted identity and each recovered record. Gate C remains BLOCKED. self_digest_matches is not a replacement for native semantic/provenance validity.\n',encoding='utf-8')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--base',required=True);p.add_argument('--recovery',required=True);p.add_argument('--output',required=True);a=p.parse_args()
 try:run(a)
 except Exception as e:
  out=Path(a.output);out.mkdir(parents=True,exist_ok=True);(out/'ERROR.txt').write_text(str(e),encoding='utf-8');raise
