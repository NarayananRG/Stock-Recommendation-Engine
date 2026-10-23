"""Bounded GUI-native recovery. No SRE imports, source edits, downloads, or paper operations."""
from pathlib import Path
import ast, collections, hashlib, json, math, os, sqlite3, sys, time, urllib.request, urllib.parse, zlib
BASE=Path(__file__).resolve().parent
DAYS=('2026-10-09','2026-10-15','2026-10-19')
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False,default=str).encode()).hexdigest()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(ok,message):
 if not ok:raise RuntimeError(message)
def dump(p,v):p.write_text(json.dumps(v,indent=2,default=str),encoding='utf-8')
def unpack(p):
 raw=Path(p).read_bytes();require(len(raw)<64*1024*1024,'Oversized cache')
 d=zlib.decompressobj();b=d.decompress(raw,64*1024*1024)
 require(d.eof and not d.unused_data and not d.unconsumed_tail,'Invalid/oversized cache envelope')
 return json.loads(b)
def db_rows(path):
 con=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True);con.execute('pragma query_only=on')
 try:
  con.execute('begin');out={}
  for (name,) in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name").fetchall():
   q='"'+name.replace('"','""')+'"'
   out[name]=collections.Counter(digest([{'blob':v.hex()} if isinstance(v,bytes) else v for v in row]) for row in con.execute('select * from '+q))
  return out
 finally:con.close()
def preserved(before,after):
 for name,rows in before.items():
  require(name in after,'Table removed: '+name)
  if name.startswith('replay_v2_'):require(not (rows-after[name]),'Prior research rows changed: '+name)
  else:require(rows==after[name],'Non-research table changed: '+name)
def validate_api_result(r,day,valid,current):
 proof=r.get('v10_acceptance',{});c=proof.get('contract',{})
 require(valid(r,c),'Native acceptance validation failed')
 require(r.get('pit_completeness')=='COMPLETE' and c.get('sessions')==[day],'Wrong/incomplete session')
 require(c.get('source')==current['source'] and c.get('market')==current['market'],'GUI identity changed')
 require(c.get('config')==wanted(day,current),'Unexpected replay assumptions/context')
def wanted(day,current):
 return dict(period='CUSTOM',start=day,end=day,starting_capital=100000.0,benchmark='NIFTY 50',slippage_bps=10.0,transaction_cost_bps=5.0,v10_market_signature=current['market'],v10_authority='RESEARCH_ONLY',v10_universe_and_sectors=current['context'])
def main():
 require(os.name=='nt','Windows required; use the running installed GUI')
 app=Path(os.environ['LOCALAPPDATA'])/'StockRecommendationEngine';engine=app/'native-engine-0.14.13'
 port=int((app/'runtime-port.txt').read_text().strip());require(1<=port<=65535,'Invalid runtime port')
 out=Path(os.environ['USERPROFILE'])/'Downloads'/('SRE-GUI-Current-Recovery-'+time.strftime('%Y%m%d-%H%M%S'))
 out.mkdir(exist_ok=False);report={'status':'BLOCKED','requests':[],'output':str(out)}
 def call(route,method='GET'):
  request=urllib.request.Request('http://127.0.0.1:'+str(port)+route,method=method,data=b'' if method=='POST' else None)
  with urllib.request.urlopen(request,timeout=600) as r:return json.load(r)
 try:
  reproduction=json.loads((BASE/'EXACT_FINGERPRINT_REPRODUCTION.json').read_text());current={**reproduction['cases']['3.14.3'],'context':'50ea935bf32af31986e7883fad64586602974940c809ae37c73e5a0d844ed3e7'}
  health=call('/api/health');dump(out/'health.json',health)
  require(Path(health['code_root']).resolve()==engine.resolve(),'Unexpected GUI source root')
  db=Path(health['database']);require(db.resolve().parent==app.resolve(),'Unexpected GUI database')
  # Verify every byte used in both reconstructed fingerprints. Extra market/source modules also stop execution.
  source=json.loads((BASE/'source-preimage.json').read_text())[2];market=json.loads((BASE/'market-preimage.json').read_text())[2]
  for name,h in list(source.items())+market:
   p=Path(name) if Path(name).is_absolute() else (engine/name if name=='modern_ui/api.py' else engine/'stock_app'/name)
   require(p.is_file() and sha(p)==h,'Input changed; no POST sent: '+str(p))
  require({p.name for p in (engine/'stock_app').glob('*.py')}=={n for n in source if '/' not in n and '\\' not in n},'Source module inventory changed')
  require({str(p.resolve()) for p in Path(market[0][0]).parent.glob('*.csv')}=={n for n,h in market},'Market file inventory changed')
  ns={'Path':Path,'json':json,'math':math,'digest':digest,'VERSION':'SRE_V10_PERFORMANCE_CORRECTION_1'}
  tree=ast.parse((engine/'stock_app/replay_v10_final.py').read_text(encoding='utf-8'))
  for node in tree.body:
   if isinstance(node,ast.FunctionDef) and node.name in ('valid_result','completed_evidence'):
    exec(compile(ast.Module(body=[node],type_ignores=[]),'verified-installed-validator','exec'),ns)
  directory=app/'historical_replay_checkpoints_v2'
  def records():
   rows=[]
   for p in directory.glob('*.complete.zlib'):
    try:
     obj=unpack(p);r=obj['value'];proof=r.get('v10_acceptance',{});c=proof.get('contract',{})
     if obj.get('schema')=='SRE_REPLAY_CHECKPOINT_V2' and obj.get('key')==p.name.split('.')[0] and ns['valid_result'](r,c):rows.append((p,r,c))
    except (ValueError,KeyError,TypeError,zlib.error):continue
   return rows
  def anchored():
   # Native endpoint confirms accepted identity, not an inspector-runtime fingerprint.
   diagnostic=call('/api/validation/gate-a-diagnostics');dump(out/'diagnostics-latest.json',diagnostic)
   # Inspect endpoint's current summaries as well as the exact locally validated contracts.
   evidence=call('/api/validation/historical-evidence')
   local=ns['completed_evidence'](directory,current['source'],current['market'],current['context'])
   require(evidence==local,'Live GUI differs from guarded current identity; STOP')
   return evidence
  before=anchored();dump(out/'evidence-before.json',before)
  require(before['invalid_replays']==0 and before['complete_replays']>=1,'Unexpected initial evidence state')
  anchor=[r for p,r,c in records() if c.get('config')==wanted(DAYS[0],current) and c.get('source')==current['source']]
  require(len(anchor)==1 and anchor[0]['pit_completeness']=='COMPLETE','Current Oct9 anchor missing/ambiguous')
  require(anchor[0]['v10_acceptance']['contract']['runtime']['python']=='3.14.3','GUI runtime changed')
  oldfiles={p.name:sha(p) for p in directory.glob('*.complete.zlib')};before_rows=db_rows(db)
  # Private consistent SQLite backup, never included in a report ZIP automatically.
  con=sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True);dest=sqlite3.connect(out/'PRIVATE-BEFORE.sqlite3')
  try:con.backup(dest)
  finally:dest.close();con.close()
  dump(out/'original-evidence-hashes.json',oldfiles)
  dump(out/'original-table-digests.json',{n:dict(v) for n,v in before_rows.items()})
  for day in DAYS[1:]:
   rows=records();present=[r for p,r,c in rows if c.get('source')==current['source'] and c.get('config')==wanted(day,current) and r.get('pit_completeness')=='COMPLETE']
   if present:report['requests'].append({'day':day,'action':'ALREADY_CURRENT_NO_POST'});continue
   # Avoid INSERT OR REPLACE collisions with ANY existing replay run row.
   old=[r for p,r,c in rows if c.get('sessions')==[day] and c.get('runtime',{}).get('python')=='3.14.2']
   require(len(old)==1,'Missing/ambiguous recovered reference for '+day)
   parts=(wanted(day,current),old[0]['coverage'])
   run_id='SREVR2_'+hashlib.sha256(json.dumps(parts,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()[:24]
   con=sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True)
   try:collision=con.execute('select 1 from replay_v2_runs where replay_id=?',(run_id,)).fetchone()
   finally:con.close()
   require(not collision,'Prospective research SQL run ID already exists; no overwrite permitted: '+run_id)
   preserved(before_rows,db_rows(db));anchored()
   query=urllib.parse.urlencode(dict(period='CUSTOM',starting_capital=100000,benchmark='NIFTY 50',start_date=day,end_date=day,slippage_bps=10,transaction_cost_bps=5))
   print('Replaying only '+day+' through running GUI; do not run other SRE operations.',flush=True)
   started=time.perf_counter();result=call('/api/validation/historical-replay?'+query,'POST');dump(out/(day+'-result.json'),result)
   validate_api_result(result,day,ns['valid_result'],current)
   require(result.get('replay_id')==run_id,'Unexpected persisted run identity')
   report['requests'].append({'day':day,'seconds':time.perf_counter()-started,'cache_status':result.get('replay_cache_status'),'replay_id':run_id})
   require(all((directory/n).is_file() and sha(directory/n)==h for n,h in oldfiles.items()),'Original evidence changed')
   preserved(before_rows,db_rows(db));dump(out/'RECOVERY_STATUS.json',report)
  after=anchored();dump(out/'evidence-after.json',after)
  dates={r['requested_range']['start'] for r in after['results'] if r['requested_range']['start']==r['requested_range']['end'] and r['pit_completeness']=='COMPLETE' and r.get('replay_integrity_checked')}
  require(set(DAYS)<=dates,'Three distinct sessions not recognized')
  require(after['stale_replays']==before['stale_replays'] and after['invalid_replays']==0,'Old stale count changed')
  preserved(before_rows,db_rows(db));require(all(sha(directory/n)==h for n,h in oldfiles.items()),'Original replay modified')
  report.update(status='PASS_THREE_CURRENT_SESSIONS',recognized_sessions=sorted(set(DAYS)&dates),old_files_preserved=len(oldfiles),nonresearch_tables_unchanged=True,old_research_rows_preserved=True,source_patch=False,gate_c='REPLAY_DISCREPANCY_RESOLVED_ONLY; OTHER_GATE_C_CHECKS_RETAIN_THEIR_EXISTING_STATUS')
 except Exception as e:
  report['error']=str(e);report['next_step']='Stop. Do not retry blindly or restore the private database over a running GUI. Preserve this directory.'
  raise
 finally:
  dump(out/'RECOVERY_STATUS.json',report);print('Report: '+str(out),flush=True)
if __name__=='__main__':main()
