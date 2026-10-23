"""Native Windows safety test; all installations and portfolios are synthetic."""
from pathlib import Path
import tempfile,shutil,subprocess,sys,json,sqlite3,hashlib,zipfile,gc
from stock_app.storage import AppDatabase
from stock_app.validation_v2 import create_portfolio
root=Path(tempfile.mkdtemp(prefix='SRE continuity safe '));app=root/'app';engine=app/'native-engine-0.14.13';out=root/'output';shutil.copytree('native-fixed',engine)
AppDatabase(app/'stock_recommendation_engine.sqlite3').initialize();create_portfolio(app/'phase81_validation.sqlite3',starting_session='2026-10-22',starting_run_id='fixture',app_version='test',production_model_version='LIVE_DECISION_V1',evidence_pipeline_version='test',router_sha256='test')
gc.collect()  # AppDatabase's context manager commits; release synthetic idle handles.
(engine/'scripts').mkdir(exist_ok=True);(engine/'scripts/keep.ps1').write_text("Write-Host 'source retained'")
meta=engine/'.replay-v10-deps/fake.dist-info';meta.mkdir(parents=True);(meta/'METADATA').write_text('Name: test-runtime\nVersion: 1.0\n')
(app/'config.json').write_text('{"api_key":"SYNTHETIC_TEST_ONLY","preserve":true}')
# All replay objects are synthetic. Preserve 12 old records across 3 sessions.
import zlib
sys.path.insert(0,str(Path('capture-suite').resolve()))
from replay_capture import digest
rd=app/'historical_replay_checkpoints_v2';rd.mkdir()
for i in range(12):
 day=['2026-10-09','2026-10-15','2026-10-19'][i%3]
 identity={'sessions':[day],'config':{'fixture_identity':i}}
 value={'requested_period':'CUSTOM','requested_range':{'start':day,'end':day},'sessions_replayed':1,'pit_completeness':'COMPLETE','coverage':[{'date':day}],'metrics':{'closed_trades':0}}
 key=digest(identity)
 if i<3:value['v10_acceptance']={'key':key,'contract':identity,'payload_sha256':digest(value)}
 (rd/(key+'.complete.zlib')).write_bytes(zlib.compress(json.dumps({'schema':'SRE_REPLAY_CHECKPOINT_V2','key':key,'value':value}).encode()))
original={p:p.read_bytes()for p in app.rglob('*')if p.is_file()}
script=Path('COLLECT_SRE_GATE_BC.ps1').resolve()
def run(output):return subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-AppDataRoot',str(app),'-OutputDirectory',str(output),'-SkipOfficialDownloads'],text=True,capture_output=True)
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(50)',str(engine)])
try:
 probe=subprocess.run(['powershell.exe','-NoProfile','-Command',f'Get-CimInstance Win32_Process | Where-Object {{$_.ProcessId -eq {child.pid}}} | Select-Object Name,CommandLine,ExecutablePath | ConvertTo-Json'],text=True,capture_output=True)
 print('Synthetic process guard probe:',probe.stdout,flush=True)
 r=run(out);assert r.returncode!=0 and 'running'in (r.stdout+r.stderr).lower(),r.stdout+r.stderr
finally:child.terminate();child.wait()
r=run(app/'not-allowed');assert r.returncode!=0 and 'outside'in r.stderr,r.stdout+r.stderr
r=run(out);assert r.returncode==0,r.stdout+r.stderr
zs=list(out.glob('SRE-GateBC-ReadOnly-*.zip'));assert len(zs)==1
with zipfile.ZipFile(zs[0])as z:
 names=z.namelist();assert 'engine/scripts/keep.ps1'in names;assert not any('/.replay-v10-deps/'in n for n in names)
 assert json.loads(z.read('application-state/config.json'))['api_key']=='[REDACTED]'
 m=json.loads(z.read('snapshot-manifest.json'));assert m['original_files_written']is False and m['original_databases_opened_by_sqlite']is False;assert len(m['databases'])==2
 contract=json.loads(z.read('continuity-evidence/installed-contract.json'));assert not contract['guard_mismatches'],contract
 assert all(x['state']=='LATEST_CANDIDATE_MATCH'for x in contract['files']if x['file'].endswith('.py')),contract
 ev=json.loads(z.read('continuity-evidence/official-evidence-report.json'));assert ev['requested']==0 and ev['bytes_saved']==0 and all(r['status']=='SKIPPED_BY_EXPLICIT_OFFLINE_OPTION'for r in ev['records'])
 replay=json.loads(z.read('gatebc-evidence/REPLAYS.json'));assert replay['complete_files']==12 and replay['attested_self_integrity_matches']==3
 assert replay['distinct_historically_complete_single_sessions']==['2026-10-09','2026-10-15','2026-10-19']
 fingerprint=json.loads(z.read('gatebc-evidence/NATIVE_FINGERPRINTS.json'));assert fingerprint['status']=='VERIFIED_PURE_MODULE_FINGERPRINTS',fingerprint
 assert json.loads(z.read('gatebc-evidence/SUMMARY.json'))['no_replay_executed']
 for line in z.read('CAPTURE_CHECKSUMS.sha256').decode('utf-8-sig').splitlines():
  h,n=line.split('  ',1);assert hashlib.sha256(z.read(n)).hexdigest()==h,n
 for d in m['databases']:
  p=root/Path(d['path']).name;p.write_bytes(z.read(d['path']))
  with sqlite3.connect(p)as c:assert c.execute('pragma integrity_check').fetchone()[0]=='ok'
assert all(p.read_bytes()==b for p,b in original.items())
print('PASS: native collector syntax, source capture, Scripts retention, runtime inventory/exclusion, original database/config byte preservation, SQLite backup integrity, ZIP checksums, installed contract detection, zero-network mode, 12-record inventory, pure-module native fingerprints, no app context/replay, running-process refusal, invalid-output refusal, synthetic secret redaction.')

