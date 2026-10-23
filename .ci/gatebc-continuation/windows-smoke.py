from pathlib import Path
import tempfile,shutil,subprocess,sys,sqlite3,hashlib,json,zlib
from stock_app.storage import AppDatabase
from stock_app.validation_v2 import create_portfolio
base=Path(tempfile.mkdtemp(prefix='SRE single continuation '));app=base/'app';engine=app/'native-engine-0.14.13';out=base/'output';shutil.copytree('native-fixed',engine)
AppDatabase(app/'stock_recommendation_engine.sqlite3').initialize();create_portfolio(app/'phase81_validation.sqlite3',starting_session='2026-10-22',starting_run_id='fixture',app_version='fixture',production_model_version='LIVE_DECISION_V1',evidence_pipeline_version='fixture',router_sha256='fixture')
import gc;gc.collect()
ck=app/'historical_replay_checkpoints_v2';ck.mkdir()
for i in range(12):(ck/(f'{i:064x}'+'.complete.zlib')).write_bytes(zlib.compress(json.dumps({'fixture':i}).encode()))
original={p:p.read_bytes() for p in app.rglob('*') if p.is_file()}
script=Path('continuation/CONTINUE_SRE_WINDOWS.ps1').resolve()
# Parse actual delivered script and validate mandatory path/process guards.
parser=base/"parse.ps1";parser.write_text("param([string]$File)\n$e=$null;$t=$null;[void][Management.Automation.Language.Parser]::ParseFile($File,[ref]$t,[ref]$e);if($e.Count){$e|Out-String|Write-Error;exit 1}")
probe=subprocess.run(["powershell.exe","-NoProfile","-File",str(parser),str(script)],capture_output=True,text=True)
assert probe.returncode==0,probe.stdout+probe.stderr
args=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-AppDataRoot',str(app),'-EngineRoot',str(engine),'-PythonPath',sys.executable]
r=subprocess.run(args+['-OutputDirectory',str(app/'invalid')],capture_output=True,text=True);assert r.returncode!=0 and 'outside'in (r.stdout+r.stderr).lower()
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(50)',str(engine)])
try:
 r=subprocess.run(args+['-OutputDirectory',str(out)],capture_output=True,text=True);assert r.returncode!=0 and 'running'in(r.stdout+r.stderr).lower(),r.stdout+r.stderr
finally:child.terminate();child.wait()
# Code-only fixture has no accepted real official history. Must stop with explicit acceptance error,
# retain a verified private backup, preserve every original byte, and never publish synthetic results.
r=subprocess.run(args+['-OutputDirectory',str(out)],capture_output=True,text=True,timeout=180)
assert r.returncode!=0,r.stdout+r.stderr
runs=[p for p in out.iterdir() if p.is_dir()];assert len(runs)==1
run=runs[0];assert (run/'ACCEPTANCE_ERROR.json').exists(),r.stdout+r.stderr
err=json.loads((run/'ACCEPTANCE_ERROR.json').read_text());assert err['status']=='BLOCKED';assert list(run.glob('SRE-GateBC-ReadOnly-*.zip'));assert not (run/'publication.json').exists()
assert all(p.read_bytes()==b for p,b in original.items());assert len(list(ck.glob('*.complete.zlib')))==12
assert list(out.glob('*-REPORTS.zip'))
print('PASS native PowerShell syntax/process/output guards; fresh backup; truthful missing-history refusal; all original source/portfolio/replay bytes preserved; one report artifact; no publication.')
