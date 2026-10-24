"""Synthetic VM gate tests. No private data and no claim of actual VM app acceptance."""
from pathlib import Path
import copy,json,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'package'))
import vm_environment as v
import vm_runner as runner
from source_transaction import Stop
HOST={'uuid':'11111111-1111-4111-8111-111111111111','machine_guid':'22222222-2222-4222-8222-222222222222'}
GUEST={'uuid':'33333333-3333-4333-8333-333333333333','machine_guid':'44444444-4444-4444-8444-444444444444','manufacturer':'VMware, Inc.','model':'VMware Virtual Platform','caption':'Microsoft Windows 11 Home Single Language','version':'10.0.26100','architecture':'64-bit','network_up':[],'drives':[{'DeviceID':'C:','DriveType':3,'ProviderName':None}],'reachable_sharing':[]}
SETTINGS=['clean_vm','checkpoint_created','shared_folders_disabled','host_drive_redirection_disabled','clipboard_disabled','drag_and_drop_disabled']
def attestation():return {'schema':'SRE_C01_VM_ISOLATION_V1','vm_uuid':GUEST['uuid'],**{n:True for n in SETTINGS}}
class VmTests(unittest.TestCase):
 def test_distinct_windows11_home_vm_is_supported_without_sandbox(self):
  x=v.guest_guard(GUEST,HOST,attestation(),'offline');self.assertEqual(x['network_up_count'],0);self.assertIn('operator-attested',x['sharing_policy'])
 def test_original_laptop_uuid_refused_before_any_app(self):
  guest=copy.deepcopy(GUEST);guest['uuid']=HOST['uuid'];a=attestation();a['vm_uuid']=guest['uuid']
  with self.assertRaisesRegex(Stop,'ORIGINAL_HOST'):v.guest_guard(guest,HOST,a,'offline')
 def test_cloned_host_os_machine_guid_refused(self):
  guest=copy.deepcopy(GUEST);guest['machine_guid']=HOST['machine_guid']
  with self.assertRaisesRegex(Stop,'CLONED_HOST_OS'):v.guest_guard(guest,HOST,attestation(),'offline')
 def test_physical_hardware_with_vbs_does_not_count_as_vm(self):
  guest=copy.deepcopy(GUEST);guest.update(manufacturer='SYNTHETIC_PHYSICAL_VENDOR',model='SYNTHETIC_LAPTOP',hypervisor_present=True)
  with self.assertRaisesRegex(Stop,'VM_HARDWARE'):v.guest_guard(guest,HOST,attestation(),'offline')
 def test_attestation_must_bind_current_vm_uuid(self):
  a=attestation();a['vm_uuid']=HOST['uuid']
  with self.assertRaisesRegex(Stop,'ATTESTATION_IDENTITY'):v.guest_guard(GUEST,HOST,a,'offline')
 def test_all_sharing_and_checkpoint_settings_require_true_boolean(self):
  for setting in SETTINGS:
   for bad in [False,None,'true',1]:
    a=attestation();a[setting]=bad
    with self.subTest(setting=setting,bad=bad),self.assertRaisesRegex(Stop,'OPERATOR_SETTING'):v.guest_guard(GUEST,HOST,a,'offline')
 def test_mapped_host_drive_refused(self):
  guest=copy.deepcopy(GUEST);guest['drives'].append({'DeviceID':'Z:','DriveType':4,'ProviderName':'\\\\SYNTHETIC-HOST\\share'})
  with self.assertRaisesRegex(Stop,'HOST_DRIVE_REFUSED'):v.guest_guard(guest,HOST,attestation(),'offline')
 def test_reachable_sharing_provider_refused(self):
  guest=copy.deepcopy(GUEST);guest['reachable_sharing']=['SYNTHETIC_PROVIDER']
  with self.assertRaisesRegex(Stop,'SHARING_PROVIDER'):v.guest_guard(guest,HOST,attestation(),'offline')
 def test_offline_active_adapter_refused(self):
  guest=copy.deepcopy(GUEST);guest['network_up']=[{'Name':'SYNTHETIC_NIC'}]
  with self.assertRaisesRegex(Stop,'OFFLINE_VM_NETWORK_STILL_UP'):v.guest_guard(guest,HOST,attestation(),'offline')
 def test_official_phase_requires_connection_and_preserves_host_state(self):
  with self.assertRaisesRegex(Stop,'OFFICIAL_VM_NETWORK_NOT_UP'):v.guest_guard(GUEST,HOST,attestation(),'official')
  guest=copy.deepcopy(GUEST);guest['network_up']=[{'Name':'SYNTHETIC_NIC'}];before=copy.deepcopy(guest);v.guest_guard(guest,HOST,attestation(),'official');self.assertEqual(guest,before)
 def test_invalid_and_empty_machine_identifiers_refused(self):
  for bad in ['','not-a-uuid','00000000-0000-0000-0000-000000000000','ffffffff-ffff-ffff-ffff-ffffffffffff']:
   guest=copy.deepcopy(GUEST);guest['uuid']=bad
   with self.subTest(bad=bad),self.assertRaises(Stop):v.guest_guard(guest,HOST,attestation(),'offline')
 def test_incompatible_guest_os_refused(self):
  for caption in ['Microsoft Windows 10 Home','Microsoft Windows Server 2025']:
   guest=copy.deepcopy(GUEST);guest['caption']=caption
   with self.assertRaisesRegex(Stop,'WINDOWS_11_X64'):v.guest_guard(guest,HOST,attestation(),'offline')
 def test_previous_offline_report_requires_real_scope_and_exact_input(self):
  report={'schema':'SRE_C01_VM_STAGING_V1','phase':'offline','input_digest':'SYNTHETIC_INPUT','actual_private_vm_execution':True,'checks':{k:{'status':'PASS'}for k in runner.REQUIRED+['vm_isolation','offline_network']}}
  runner.previous_offline(report,'SYNTHETIC_INPUT')
  for key in runner.REQUIRED:
   altered=copy.deepcopy(report);altered['checks'][key]['status']='BLOCKED'
   with self.subTest(key=key),self.assertRaisesRegex(Stop,'OFFLINE_ACCEPTANCE_NOT_PASS'):runner.previous_offline(altered,'SYNTHETIC_INPUT')
  with self.assertRaisesRegex(Stop,'INPUT_IDENTITY'):runner.previous_offline(report,'DIFFERENT_INPUT')
  report['actual_private_vm_execution']=False
  with self.assertRaisesRegex(Stop,'SYNTHETIC_REPORT_REFUSED'):runner.previous_offline(report,'SYNTHETIC_INPUT')
if __name__=='__main__':unittest.main()
