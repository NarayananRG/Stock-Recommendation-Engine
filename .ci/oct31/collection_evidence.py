"""Embedded by build_collector.py. Standard library only; no app imports."""
from pathlib import Path
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.parse import urlsplit
import json,hashlib,sys,base64,concurrent.futures,threading,datetime
REQUESTS_B64='__REQUESTS_B64__'
MANIFEST_B64='__MANIFEST_B64__'
MAX_FILE=8*1024*1024;MAX_TOTAL=192*1024*1024
def allowed(url):
 try:
  u=urlsplit(url)
  return u.scheme=='https'and u.hostname=='nsearchives.nseindia.com'and not u.username and not u.password and u.port in (None,443)and any(u.path.startswith(p)for p in ['/corporate/','/content/cm/','/content/indices/','/content/circulars/'])
 except ValueError:return False
class NoRedirect(HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):raise ValueError('REDIRECT_REFUSED')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def inspect_contract(root):
 m=json.loads(base64.b64decode(MANIFEST_B64));rows=[]
 for n,v in m['files'].items():
  p=root/'engine'/n;actual=sha(p)if p.is_file()else None
  rows.append({'file':n,'sha256':actual,'state':'LATEST_CANDIDATE_MATCH'if actual==v['new_sha256']else 'PRIOR_CAPTURE_MATCH'if actual==v['old_sha256']else 'MISSING_OR_DIFFERENT_CURRENT_SOURCE'})
 guards=[n for n,h in m['guard_files'].items()if not(root/'engine'/n).is_file()or sha(root/'engine'/n)!=h]
 expected=set(m['guard_files'])|set(m['files'])
 extra=[p.relative_to(root/'engine').as_posix()for folder in ['stock_app','modern_ui']for p in (root/'engine'/folder).glob('*.py')if p.relative_to(root/'engine').as_posix()not in expected]
 guards+=['UNRECOGNIZED_MODULE:'+n for n in extra]
 return {'files':rows,'guard_mismatches':guards,'status':'LATEST_PATCH_SOURCE_MATCH'if not guards and all(r['state']=='LATEST_CANDIDATE_MATCH'for r in rows)else 'PRIOR_BASELINE_MATCH'if not guards and all(r['state']=='PRIOR_CAPTURE_MATCH'for r in rows)else 'CURRENT_SOURCE_REQUIRES_DELTA_REVIEW','note':'No source was overwritten and no patch was applied.'}
def main():
 root=Path(sys.argv[1]);skip=len(sys.argv)>2 and sys.argv[2]=='SKIP_NETWORK';out=root/'continuity-evidence';out.mkdir();(out/'installed-contract.json').write_text(json.dumps(inspect_contract(root),indent=2))
 requests=json.loads(base64.b64decode(REQUESTS_B64));total=0;lock=threading.Lock();records=[]
 def retrieve(r):
  nonlocal total
  rec=dict(r)
  if skip:return {**rec,'status':'SKIPPED_BY_EXPLICIT_OFFLINE_OPTION'}
  if not allowed(r['url']):return {**rec,'status':'BLOCKED_NOT_OFFICIAL_ALLOWLIST'}
  try:
   with build_opener(NoRedirect()).open(Request(r['url'],headers={'User-Agent':'Mozilla/5.0','Accept':'application/xml,text/xml,text/csv,application/zip,*/*'}),timeout=12)as response:
    if not allowed(response.url):raise ValueError('RESPONSE_URL_OUTSIDE_ALLOWLIST')
    data=response.read(MAX_FILE+1)
    if len(data)>MAX_FILE:return {**rec,'status':'PER_FILE_LIMIT'}
   actual=hashlib.sha256(data).hexdigest()
   with lock:
    if total+len(data)>MAX_TOTAL:return {**rec,'status':'TOTAL_LIMIT'}
    total+=len(data)
   path=out/'official-downloads'/r['filename'];path.parent.mkdir(exist_ok=True);path.write_bytes(data)
   expected=r.get('expected_sha256');status='EXACT_REQUESTED_HASH_MATCH'if expected and actual==expected else 'HASH_MISMATCH_REVIEW_REQUIRED'if expected else 'CAPTURED_UNVALIDATED_ORIGINAL'
   return {**rec,'status':status,'sha256':actual,'bytes':len(data),'path':path.relative_to(root).as_posix()}
  except Exception as e:return {**rec,'status':'FETCH_FAILED','error_type':type(e).__name__,'detail':str(e)[:250]}
 with concurrent.futures.ThreadPoolExecutor(max_workers=4)as pool:
  for rec in pool.map(retrieve,requests):
   records.append(rec)
   if len(records)%25==0:print('Official evidence requests processed:',len(records),'/',len(requests),flush=True)
 report={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'requested':len(requests),'bytes_saved':total,'records':records,'source_application_files_written':False,'network_mode':'EXPLICIT_OFFLINE'if skip else 'OFFICIAL_NSE_ONLY','status':'CAPTURE_COMPLETE_WITH_PER_REQUEST_RESULTS','all_results_are_evidence_only':True,'financial_ingestion_performed':False}
 (out/'official-evidence-report.json').write_text(json.dumps(report,indent=2));print('Official evidence saved:',sum('path'in r for r in records),'of',len(records),flush=True)
if __name__=='__main__':main()
