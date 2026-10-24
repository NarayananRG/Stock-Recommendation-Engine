"""Read/copy an existing verified restore; never execute the host SRE application."""
from pathlib import Path
import argparse,collections,ctypes,json,os,shutil,subprocess,sys,time,uuid,zipfile
from xml.sax.saxutils import escape
sys.path.insert(0,str(Path(__file__).resolve().parent))
from vm_environment import probe as machine_probe, identity as machine_identity
from source_transaction import Stop,require,sha,digest,write,check_path,child,files,verify
BASE=Path(__file__).resolve().parent
CHECKS=['original_restore','source_guard_46','runtime_identity','runtime_dependencies','vm_isolation','source_apply','source_rollback','interrupted_install_recovery','hash_drift_refusal','staged_regressions','backend_lifecycle','static_gui_delivery','desktop_gui_acceptance','offline_backend','offline_gui','financial_preservation','evidence_preservation','official_history_preservation','official_network_retrieval','official_full_coverage','official_publication_time','clean_machine_portability','live_deployment_preparation']
def report():return {'schema':'SRE_C01_VM_STAGING_V1','checks':{k:{'status':'BLOCKED','evidence':'Isolated Windows VM staging not yet executed'}for k in CHECKS},'live_installation_modified':False,'historical_replays_run':0,'live_apply_authorized':False,'gate_c':'BLOCKED','strategy_profitability':'NOT_VALIDATED'}
def mark(r,k,s,e):r['checks'][k]={'status':s,'evidence':e}
def save(out,r):
 out.mkdir(parents=True,exist_ok=True);r['gate_c']='FAIL'if any(c['status']=='FAIL'for c in r['checks'].values())else'BLOCKED'
 write(out/'C01_WINDOWS_STAGING_RESULTS.json',r)
 lines=['# C01 Windows staging acceptance','','Overall: **'+r['gate_c']+'**. Live application unchanged. Strategy profitability NOT VALIDATED.','','| Check | Status | Evidence |','|---|---|---|']
 for k,v in r['checks'].items():lines.append('| '+k+' | '+v['status']+' | '+str(v['evidence']).replace('|','/').replace('\n',' ')+' |')
 (out/'C01_STAGING_ACCEPTANCE.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
def copy_tree(src,dst):
 src=check_path(src);dst=check_path(dst);require(not dst.is_relative_to(src)and not src.is_relative_to(dst),'COPY_PATH_OVERLAP');expected=files(src);require(not dst.exists(),'NEW_COPY_REQUIRED');dst.mkdir(parents=True)
 for n,h in expected.items():
  s=child(src,n);d=child(dst,n);d.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(s,d);require(sha(d)==h,'UNSTABLE_COPY:'+n)
 require(files(src)==expected,'SOURCE_CHANGED_DURING_COPY');verify(dst,expected,exact=True);return expected
def package_verify():
 expected=json.loads((BASE/'PACKAGE_HASHES.json').read_text());verify(BASE,expected)
def safe_extract(src,dst):
 require(not dst.exists(),'EXTRACT_DESTINATION_EXISTS');dst.mkdir()
 with zipfile.ZipFile(src)as z:
  for item in z.infolist():
   p=child(dst,item.filename.rstrip('/'));require((item.external_attr>>16)&0o170000!=0o120000,'ZIP_SYMLINK')
   if item.is_dir():p.mkdir(parents=True,exist_ok=True)
   else:p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(item))
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--initial',required=True);ap.add_argument('--workspace-parent',required=True);ap.add_argument('--runtime',default='');ap.add_argument('--timeout',type=int,default=1200);args=ap.parse_args()
 parent=check_path(args.workspace_parent);initial=check_path(args.initial)
 live=check_path(Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'StockRecommendationEngine')
 root=check_path(parent/('SRE-C01-VM-EXPORT-'+uuid.uuid4().hex[:12]))
 # Validate before even creating a report directory. Invalid live/restore paths receive no writes.
 for p in (root,BASE):require(not p.is_relative_to(live)and not live.is_relative_to(p),'LIVE_PATH_OVERLAP')
 require(not root.is_relative_to(initial)and not initial.is_relative_to(root),'INITIAL_PATH_OVERLAP')
 require(not root.is_relative_to(BASE)and not BASE.is_relative_to(root),'PACKAGE_PATH_OVERLAP')
 parent.mkdir(parents=True,exist_ok=True);root.mkdir(exist_ok=False);out=root/'REPORTS';r=report();save(out,r)
 try:
  require(os.name=='nt','WINDOWS_REQUIRED_NO_HOST_APP_FALLBACK');package_verify()
  live=check_path(Path(os.environ['LOCALAPPDATA'])/'StockRecommendationEngine');initial=check_path(args.initial);restore=initial/'PRIVATE_RESTORE'
  for p in (root,BASE,initial):require(not p.is_relative_to(live)and not live.is_relative_to(p),'LIVE_PATH_OVERLAP')
  require(not root.is_relative_to(initial)and not initial.is_relative_to(root),'INITIAL_PATH_OVERLAP')
  for n in ['baseline.json','PRIVATE_RUNTIME_INVENTORY.json','GATE_C_MACHINE_RESULTS.json']:require((initial/n).is_file(),'INITIAL_ARTIFACT_MISSING:'+n)
  actual=json.loads((initial/'GATE_C_MACHINE_RESULTS.json').read_text());baseline=json.loads((initial/'baseline.json').read_text());manifest=json.loads((restore/'manifest.json').read_text())
  for k in ['sqlite_backup','restore_accounting','source_history_backup','evidence_backup']:require(actual['checks'][k]['status']=='PASS','INITIAL_ACCEPTANCE_NOT_PASS:'+k)
  verify(restore/'engine',manifest['engine'],exact=True);verify(restore/'app-state',manifest['app-state'],exact=True)
  require(not list(restore.rglob('*-wal'))and not list(restore.rglob('*-shm'))and not list(restore.rglob('*-journal')),'RESTORE_HAS_PENDING_DB_SIDECAR')
  mark(r,'original_restore','PASS','Existing accepted Initial manifest matches; original restore retained read-only; no new backup test')
  guard=json.loads((BASE/'BASELINE_SOURCE_GUARD.json').read_text());require(len(guard)==46,'EXPECTED_46_SOURCE_GUARD');verify(restore/'engine',guard);mark(r,'source_guard_46','PASS','All46 original installed-source hashes match')
  meta=json.loads((initial/'PRIVATE_RUNTIME_INVENTORY.json').read_text());exe=check_path(args.runtime or meta['executable']);require(exe.is_file(),'RUNTIME_EXECUTABLE_MISSING')
  matches=[b for b in meta['binaries']if os.path.normcase(str(Path(b['path'])))==os.path.normcase(str(exe))];require(len(matches)==1 and sha(exe)==matches[0]['sha256'],'RUNTIME_EXE_NOT_BOUND_TO_INITIAL_INVENTORY')
  probe=subprocess.run([str(exe),'-I','-S','-B','-c','import sys,json;print(json.dumps({"version":list(sys.version_info[:3]),"prefix":sys.prefix,"base_prefix":sys.base_prefix}))'],capture_output=True,text=True,timeout=30)
  require(probe.returncode==0,'RUNTIME_STDLIB_PROBE_FAILED');identity=json.loads(probe.stdout);require(identity['version']==[3,14,3],'EXACT_PYTHON_3_14_3_REQUIRED');runtime=check_path(identity['prefix']);require(not root.is_relative_to(runtime)and not runtime.is_relative_to(root),'RUNTIME_OUTPUT_OVERLAP');require(runtime==check_path(identity['base_prefix']),'SPLIT_RUNTIME_CLOSURE_BLOCKED')
  require(exe.name.lower()=='python.exe'and exe.parent==runtime,'UNSUPPORTED_RUNTIME_LAYOUT')
  mark(r,'runtime_identity','PASS','Exact3.14.3 executable matches Initial inventory; base runtime closure found')
  host_machine=machine_probe();machine_identity(host_machine)
  payload=root/'PRIVATE_INPUT';payload.mkdir();needed=sum(p.stat().st_size for base in (restore,runtime)for p in base.rglob('*')if p.is_file())
  deps=live/'native-engine-0.14.13/.replay-v10-deps';check_path(deps);require(deps.is_dir(),'PRIVATE_V10_DEPENDENCY_DIRECTORY_MISSING');needed+=sum(p.stat().st_size for p in deps.rglob('*')if p.is_file())
  require(shutil.disk_usage(parent).free>needed+1024**3,'INSUFFICIENT_DISK_FOR_COPY: choose a larger drive; nothing deleted')
  restored_map=copy_tree(restore,payload/'restore');runtime_map=copy_tree(runtime,payload/'runtime');dep_map=copy_tree(deps,payload/'deps')
  # Pin every runtime/dependency native binary covered by the Initial inventory.
  for b in meta['binaries']:
   src=check_path(b['path'])
   if src.is_relative_to(deps):require(sha(child(payload/'deps',src.relative_to(deps).as_posix()))==b['sha256'],'DEPENDENCY_NATIVE_DRIFT')
   elif src.is_relative_to(runtime):require(sha(child(payload/'runtime',src.relative_to(runtime).as_posix()))==b['sha256'],'RUNTIME_NATIVE_DRIFT')
  write(payload/'input.json',{'database_snapshots':baseline['databases'],'restore_files':restored_map,'runtime_files':runtime_map,'dependency_files':dep_map,'runtime_version':identity['version'],'package_versions':meta['packages']})
  write(payload/'HOST_MACHINE.json',host_machine)
  transfer=files(payload);write(payload/'TRANSFER_HASHES.json',transfer)
  write(payload/'EXPORT_IDENTITY.json',{'schema':'SRE_C01_VM_EXPORT_V1','transfer_digest':digest(transfer),'host_identity_digest':digest(machine_identity(host_machine))})
  r['export_only']=True;r['application_started']=False;r['private_vm_input_directory']=str(payload);r['execution_complete']=True
  print('PRIVATE_VM_INPUT: '+str(payload))
  print('Copy this private input to C:\\C01Input inside the separate VM. Never upload it to GitHub or public CI.')
 except Exception as exc:
  r['stop_reason']=str(exc);r['execution_complete']=False
  if isinstance(exc,Stop):r['safe_stop']=True
  else:r['runner_error']=type(exc).__name__
 finally:
  save(out,r);print('Results: '+str(out/'C01_WINDOWS_STAGING_RESULTS.json'));print('Read-only export only. No staging or live application was launched. Keep PRIVATE_INPUT local/private.')
if __name__=='__main__':
 try:main()
 except Stop as exc:print('SAFE STOP BEFORE WRITES: '+str(exc));sys.exit(2)
