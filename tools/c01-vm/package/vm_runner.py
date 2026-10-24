"""Run the preserved C01 worker only inside a distinct, verified isolated Windows VM."""
from pathlib import Path
import argparse,json,os,shutil,subprocess,sys,uuid
sys.path.insert(0,str(Path(__file__).resolve().parent));sys.dont_write_bytecode=True
from source_transaction import *
from vm_environment import probe,guest_guard,local_paths
from prepare_windows import report,save
BASE=Path(__file__).resolve().parent;INPUT=Path('C:/C01Input');WORK=Path('C:/C01');WORK_OUTPUT=Path('C:/C01Output');CTX=Path('C:/C01VMContext.json')
REQUIRED=['source_apply','source_rollback','interrupted_install_recovery','hash_drift_refusal','staged_regressions','backend_lifecycle','financial_preservation','evidence_preservation','official_history_preservation']
def previous_offline(value,input_digest):
 require(value.get('schema')=='SRE_C01_VM_STAGING_V1'and value.get('phase')=='offline','VERIFIED_OFFLINE_REPORT_REQUIRED')
 require(value.get('input_digest')==input_digest,'OFFLINE_INPUT_IDENTITY_MISMATCH')
 require(value.get('actual_private_vm_execution')is True,'SYNTHETIC_REPORT_REFUSED')
 for key in REQUIRED+['vm_isolation','offline_network']:
  require(value.get('checks',{}).get(key,{}).get('status')=='PASS','OFFLINE_ACCEPTANCE_NOT_PASS:'+key)
 return value

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--phase',choices=['offline','official'],required=True);ap.add_argument('--attestation',required=True);ap.add_argument('--offline-report',default='');args=ap.parse_args()
 # No workspace/report/app write before the VM and host-separation checks.
 require(os.name=='nt','WINDOWS_VM_REQUIRED');require(str(BASE).lower()=='c:\\c01package','GUEST_PACKAGE_PATH_REQUIRED')
 current=probe();host=json.loads((INPUT/'HOST_MACHINE.json').read_text());attestation=json.loads(check_path(args.attestation).read_text());vm=guest_guard(current,host,attestation,args.phase)
 local_paths(current,[BASE,INPUT,Path('C:/')]);require(not(Path(os.environ['LOCALAPPDATA'])/'StockRecommendationEngine').exists(),'EXISTING_GUEST_SRE_INSTALLATION_REFUSED')
 require(not WORK.exists()and not WORK_OUTPUT.exists()and not CTX.exists(),'CLEAN_VM_CHECKPOINT_REQUIRED_DO_NOT_OVERWRITE_PRIOR_RUN')
 expected=json.loads((BASE/'PACKAGE_HASHES.json').read_text());verify(BASE,expected)
 transfer=json.loads((INPUT/'TRANSFER_HASHES.json').read_text());verify(INPUT,transfer)
 require(set(files(INPUT))-set(transfer)=={'TRANSFER_HASHES.json','EXPORT_IDENTITY.json'},'UNREVIEWED_TRANSFER_FILES')
 identity=json.loads((INPUT/'EXPORT_IDENTITY.json').read_text());require(identity.get('schema')=='SRE_C01_VM_EXPORT_V1'and identity['transfer_digest']==digest(transfer),'TRANSFER_MANIFEST_MISMATCH')
 info=json.loads((INPUT/'input.json').read_text());require(sys.version_info[:3]==(3,14,3)and sha(sys.executable)==info['runtime_files']['python.exe'],'EXACT_RECORDED_RUNTIME_REQUIRED')
 input_digest=digest({'transfer':transfer,'runtime':info['runtime_version'],'candidate':json.loads((BASE/'review/CHANGE_MANIFEST.json').read_text())})
 prior=None
 if args.phase=='official':prior=previous_offline(json.loads(check_path(args.offline_report).read_text()),input_digest)
 parent=Path('C:/C01VMReports');check_path(parent);root=parent/(args.phase+'-'+uuid.uuid4().hex[:12]);root.mkdir(parents=True,exist_ok=False)
 r=report();r['schema']='SRE_C01_VM_STAGING_V1';r['checks'].pop('sandbox_isolation',None);r.update(phase=args.phase,input_digest=input_digest,actual_private_vm_execution=True,vm_evidence=vm,execution_complete=False)
 if prior:r['checks'].update(prior['checks']);r['prior_offline_report_digest']=digest(prior)
 r['checks']['vm_isolation']={'status':'PASS','evidence':'Distinct recognized VM hardware and OS identity; no mapped/reachable sharing detected. Hypervisor sharing/checkpoint settings are explicitly operator-attested.'}
 if args.phase=='offline':r['checks']['offline_network']={'status':'PASS','evidence':'No guest network adapter is Up before execution; loopback will be tested by staged backend. No host network settings changed.'}
 write(CTX,{'schema':'SRE_C01_VM_CONTEXT_V1','phase':args.phase,'vm_identity_digest':vm['vm_identity_digest'],'attestation':attestation})
 try:
  size=sum(p.stat().st_size for p in (INPUT/'restore').rglob('*')if p.is_file());require(shutil.disk_usage('C:/').free>size*5+1024**3,'INSUFFICIENT_VM_DISK')
  log=root/'PRIVATE/worker.log';log.parent.mkdir();save(root,r)
  with log.open('wb')as stream:
   child_process=subprocess.Popen([sys.executable,'-I','-S','-B',str(BASE/'sandbox_worker.py'),'--phase',args.phase],stdout=stream,stderr=subprocess.STDOUT)
   try:child_process.wait(timeout=1200)
   except subprocess.TimeoutExpired:
    child_process.terminate();child_process.wait(timeout=10);raise Stop('VM_WORKER_TIMEOUT: power off disposable VM to terminate any staged children; retain this report and checkpoint. Do not use the live app.')
  require((WORK_OUTPUT/'DONE.json').is_file(),'VM_WORKER_DID_NOT_COMPLETE: inspect PRIVATE/worker.log locally')
  done=json.loads((WORK_OUTPUT/'DONE.json').read_text(encoding='utf-8-sig'));r['checks'].update(done['checks']);r['worker_details']={k:v for k,v in done.items()if k!='checks'}
  require(child_process.returncode==0 and done.get('execution_complete')is True,'VM_WORKER_BLOCKED_OR_FAILED')
  after=guest_guard(probe(),host,attestation,args.phase);require(after['vm_identity_digest']==vm['vm_identity_digest'],'VM_IDENTITY_CHANGED_DURING_RUN');verify(INPUT,transfer)
  if args.phase=='offline':
   for key in REQUIRED:require(r['checks'].get(key,{}).get('status')=='PASS','STAGING_CONDITION_NOT_PASS:'+key)
  r['execution_complete']=True
 except Exception as exc:
  r['stop_reason']=str(exc);r['checks']['execution']={'status':'FAIL'if any(x in str(exc)for x in ['CHANGED','MISMATCH'])else'BLOCKED','evidence':str(exc)}
 finally:
  r['retained_workspace']='C:\\C01';r['retained_private_worker_output']='C:\\C01Output';save(root,r)
  print('CONSOLIDATED_REPORT: '+str(root/'C01_WINDOWS_STAGING_RESULTS.json'));print('Retain the full VM/checkpoint. Transfer only this report; never publish C01Input, C01, C01Output or PRIVATE folders.')
if __name__=='__main__':
 try:main()
 except Stop as exc:print('SAFE STOP BEFORE APP START: '+str(exc));sys.exit(2)
