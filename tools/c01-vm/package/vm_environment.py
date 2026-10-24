"""Read-only VM identity/network checks; never installs a hypervisor or changes host settings."""
from pathlib import Path
import base64,json,os,re,subprocess,uuid
from source_transaction import Stop,require,digest,check_path
SCRIPT=r'''
$ErrorActionPreference='Stop'
$c=Get-CimInstance Win32_ComputerSystem
$p=Get-CimInstance Win32_ComputerSystemProduct
$o=Get-CimInstance Win32_OperatingSystem
$guid=(Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Cryptography').MachineGuid
$drives=@(Get-CimInstance Win32_LogicalDisk | Select-Object DeviceID,DriveType,ProviderName)
$network=@(Get-NetAdapter -IncludeHidden | Where-Object {$_.Status -eq 'Up'} | Select-Object InterfaceGuid,Name,Status)
$shares=@()
foreach($path in @('\\tsclient\','\\VBOXSVR\','\\vmware-host\Shared Folders\','\\.host\Shared Folders')) {
 if(Test-Path -LiteralPath $path -ErrorAction SilentlyContinue){$shares+=$path}
}
@{manufacturer=$c.Manufacturer;model=$c.Model;uuid=$p.UUID;machine_guid=$guid;caption=$o.Caption;version=$o.Version;architecture=$o.OSArchitecture;network_up=$network;drives=$drives;reachable_sharing=$shares;session=$env:SESSIONNAME} | ConvertTo-Json -Depth 8 -Compress
'''
def probe():
 require(os.name=='nt','WINDOWS_REQUIRED')
 command=base64.b64encode(SCRIPT.encode('utf-16le')).decode()
 p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',command],capture_output=True,text=True,timeout=45)
 require(p.returncode==0,'VM_MACHINE_PROBE_FAILED');return json.loads(p.stdout.lstrip('\ufeff'))
def identity(v):
 def normal(name):
  try:u=uuid.UUID(str(v[name]));require(u.int not in(0,(1<<128)-1),'EMPTY_MACHINE_ID');return str(u)
  except (KeyError,ValueError):raise Stop('MACHINE_ID_UNAVAILABLE:'+name)
 return {'uuid':normal('uuid'),'machine_guid':normal('machine_guid')}
def guest_guard(current,host,attestation,phase):
 cur=identity(current);origin=identity(host)
 require(cur['uuid']!=origin['uuid']and cur['machine_guid']!=origin['machine_guid'],'ORIGINAL_HOST_OR_CLONED_HOST_OS_REFUSED')
 vendor=str(current.get('manufacturer','')).lower();model=str(current.get('model','')).lower()
 supported=(('microsoft' in vendor and model=='virtual machine')or('vmware'in vendor and 'virtual'in model)or('virtualbox'in model)or('qemu'in vendor)or('kvm'in model)or('red hat'in vendor and 'virtual'in model)or('parallels'in vendor and 'virtual'in model))
 require(supported,'RECOGNIZED_ISOLATED_VM_HARDWARE_REQUIRED')
 version=[int(x)for x in str(current.get('version','')).split('.')]
 require('Windows 11'in current.get('caption','')and '64'in current.get('architecture','')and len(version)>=3 and version[0]==10 and version[2]>=26200,'SUPPORTED_WINDOWS_11_25H2_OR_NEWER_X64_GUEST_REQUIRED')
 require(attestation.get('schema')=='SRE_C01_VM_ISOLATION_V1'and str(attestation.get('vm_uuid','')).lower()==cur['uuid'],'VM_ATTESTATION_IDENTITY_MISMATCH')
 for k in ['supported_guest_release','clean_vm','checkpoint_created','shared_folders_disabled','host_drive_redirection_disabled','clipboard_disabled','drag_and_drop_disabled']:
  require(attestation.get(k)is True,'VM_OPERATOR_SETTING_REQUIRED:'+k)
 require(not current.get('reachable_sharing'),'HOST_SHARING_PROVIDER_REACHABLE')
 require(not any(int(d.get('DriveType',0))==4 or d.get('ProviderName')for d in current.get('drives',[])),'MAPPED_NETWORK_OR_HOST_DRIVE_REFUSED')
 if phase=='offline':require(not current.get('network_up'),'OFFLINE_VM_NETWORK_STILL_UP')
 else:require(bool(current.get('network_up')),'OFFICIAL_VM_NETWORK_NOT_UP')
 return {'vm_identity_digest':digest(cur),'origin_identity_digest':digest(origin),'hardware_model':current['model'],'network_up_count':len(current.get('network_up',[])),'sharing_probe':'no mapped/reachable host sharing detected','sharing_policy':'operator-attested hypervisor settings; guest checks do not cryptographically prove host configuration'}
def local_paths(current,paths):
 local={str(d['DeviceID']).lower():int(d['DriveType'])for d in current.get('drives',[])}
 for path in paths:
  p=check_path(path);require(p.drive.lower()in local and local[p.drive.lower()]in(3,5),'VM_LOCAL_DISK_REQUIRED:'+str(p))
def validate_context(phase=None):
 context=Path('C:/C01VMContext.json');require(context.is_file(),'VALIDATED_VM_CONTEXT_REQUIRED')
 ctx=json.loads(context.read_text());require(ctx.get('schema')=='SRE_C01_VM_CONTEXT_V1','VM_CONTEXT_SCHEMA_MISMATCH')
 if phase:require(ctx['phase']==phase,'VM_CONTEXT_PHASE_MISMATCH')
 current=probe();host=json.loads(Path('C:/C01Input/HOST_MACHINE.json').read_text());evidence=guest_guard(current,host,ctx['attestation'],ctx['phase'])
 require(evidence['vm_identity_digest']==ctx['vm_identity_digest'],'VM_IDENTITY_CHANGED');return evidence
