"""Native Windows safety test; all installations and portfolios are synthetic."""
from pathlib import Path
import tempfile,shutil,subprocess,sys,json,sqlite3,hashlib,zipfile,gc
from stock_app.storage import AppDatabase
from stock_app.validation_v2 import create_portfolio
root=Path(tempfile.mkdtemp(prefix='SRE continuity safe '));app=root/'app';engine=app/'native-engine-0.14.13';out=root/'output';shutil.copytree('gatea-fixed',engine)
AppDatabase(app/'stock_recommendation_engine.sqlite3').initialize();create_portfolio(app/'phase81_validation.sqlite3',starting_session='2026-10-22',starting_run_id='fixture',app_version='test',production_model_version='LIVE_DECISION_V1',evidence_pipeline_version='test',router_sha256='test')
gc.collect()  # AppDatabase's context manager commits; release synthetic idle handles.
(engine/'scripts').mkdir(exist_ok=True);(engine/'scripts/keep.ps1').write_text("Write-Host 'source retained'")
meta=engine/'.replay-v10-deps/fake.dist-info';meta.mkdir(parents=True);(meta/'METADATA').write_text('Name: test-runtime\nVersion: 1.0\n')
(app/'config.json').write_text('{"api_key":"SYNTHETIC_TEST_ONLY","preserve":true}')
original={p:p.read_bytes()for p in app.rglob('*')if p.is_file()}
script=Path('COLLECT_SRE_OCT31.ps1').resolve()
def run(output):return subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-AppDataRoot',str(app),'-OutputDirectory',str(output),'-SkipOfficialDownloads'],text=True,capture_output=True)
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(50)',str(engine)])
try:
 r=run(out);assert r.returncode!=0 and 'running'in (r.stdout+r.stderr).lower(),r.stdout+r.stderr
finally:child.terminate();child.wait()
r=run(app/'not-allowed');assert r.returncode!=0 and 'outside'in r.stderr,r.stdout+r.stderr
r=run(out);assert r.returncode==0,r.stdout+r.stderr
zs=list(out.glob('SRE-Oct31-Current-Snapshot-*.zip'));assert len(zs)==1
with zipfile.ZipFile(zs[0])as z:
 names=z.namelist();assert 'engine/scripts/keep.ps1'in names;assert not any('/.replay-v10-deps/'in n for n in names)
 assert json.loads(z.read('application-state/config.json'))['api_key']=='[REDACTED]'
 m=json.loads(z.read('snapshot-manifest.json'));assert m['original_files_written']is False and m['original_databases_opened_by_sqlite']is False;assert len(m['databases'])==2
 contract=json.loads(z.read('continuity-evidence/installed-contract.json'));assert contract['status']=='LATEST_PATCH_SOURCE_MATCH',contract
 ev=json.loads(z.read('continuity-evidence/official-evidence-report.json'));assert ev['requested']==568 and ev['bytes_saved']==0 and all(r['status']=='SKIPPED_BY_EXPLICIT_OFFLINE_OPTION'for r in ev['records'])
 for line in z.read('CAPTURE_CHECKSUMS.sha256').decode('utf-8-sig').splitlines():
  h,n=line.split('  ',1);assert hashlib.sha256(z.read(n)).hexdigest()==h,n
 for d in m['databases']:
  p=root/Path(d['path']).name;p.write_bytes(z.read(d['path']))
  with sqlite3.connect(p)as c:assert c.execute('pragma integrity_check').fetchone()[0]=='ok'
assert all(p.read_bytes()==b for p,b in original.items())
print('PASS: native collector syntax, source capture, Scripts retention, runtime inventory/exclusion, original database/config byte preservation, SQLite backup integrity, ZIP checksums, installed contract detection, official-only offline mode, running-process refusal, invalid-output refusal, synthetic secret redaction.')
