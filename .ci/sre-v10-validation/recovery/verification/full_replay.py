import json,time,zlib,resource
from pathlib import Path
from modern_ui.api import ModernAppContext
app=Path('verification/state-V10').resolve()
class AuditContext(ModernAppContext):
 def _validation_pit_session(self,*a,**kw):
  self.n+=1
  if self.inject and self.n==10:self.inject=False;raise RuntimeError('CONTROLLED_INTERRUPTION')
  r=super()._validation_pit_session(*a,**kw)
  if self.n%25==0:print('PROGRESS',self.n,a[0],resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,flush=True)
  return r
c=AuditContext(repo_root=Path('snapshot/installed-engine').resolve(),app_data_dir=app);c.code_root=Path('v10work').resolve();c.n=0;c.inject=True
dates=c._phase81_available_sessions();t=time.perf_counter()
try:r=c.phase81_historical_replay(period='CUSTOM',start_date=dates[0],end_date=dates[-1])
except RuntimeError as e:
 if str(e)!='CONTROLLED_INTERRUPTION':raise
 p=list((app/'historical_replay_checkpoints_v2').glob('*.checkpoint.zlib'));assert len(p)==1
 state=json.loads(zlib.decompress(p[0].read_bytes()));completed=len(state['value']['completed_sessions']);assert completed==9
 print('INTERRUPTED_CHECKPOINT',completed,flush=True)
 r=c.phase81_historical_replay(period='CUSTOM',start_date=dates[0],end_date=dates[-1]);assert r['replay_cache_status']=='RESUMED'
 assert len(r['coverage'])==len(dates)==len({x['date'] for x in r['coverage']})
 Path('reports/real-recovery.json').write_text(json.dumps({'status':'PASS','completed_before_interruption':completed,'resumed':True,'final_coverage_rows':len(r['coverage']),'duplicate_coverage_rows':0},indent=2))
Path('reports/full-replay.json').write_text(json.dumps({'elapsed_seconds':time.perf_counter()-t,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'result':r},indent=2));print('FULL_FINISHED',time.perf_counter()-t,flush=True)
rows=[]
for period in ['1W','1M','3M','6M','12M','24M']:
 t=time.perf_counter();p=c.phase81_historical_replay(period=period,end_date=dates[-1]);stats=p.get('replay_input_cache_stats') or {};assert stats.get('v10_score_misses',0)==0
 rows.append({'period':period,'elapsed_seconds':time.perf_counter()-t,'cache_status':p.get('replay_cache_status'),'replayed':p['sessions_replayed'],'excluded':p['sessions_excluded'],'stats':stats})
 Path('reports/all-period-reuse.json').write_text(json.dumps(rows,indent=2));print('PERIOD',period,rows[-1]['elapsed_seconds'],flush=True)
print('ALL_REUSE_PASS',flush=True)
