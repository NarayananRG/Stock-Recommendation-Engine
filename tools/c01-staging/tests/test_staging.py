"""Synthetic staging guard tests; no private source/data/runtime and no live application."""
from pathlib import Path
import contextlib,hashlib,json,os,shutil,sqlite3,subprocess,sys,tempfile,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'package'))
import source_transaction as t
import prepare_windows as host
import sandbox_worker as guest
NAMES=['stock_app/official_daily_refresh.py','stock_app/portfolio.py','stock_app/historical.py','stock_app/replay_v10.py','modern_ui/api.py','stock_app/official_cache_guard.py']
def fixture(path):
 root=path/'isolated';root.mkdir();(root/'engine').mkdir();t.write(root/'ISOLATED_WORKSPACE.json',{'purpose':'C01_STAGING_ONLY','root':str(root.resolve())});candidate=path/'candidate';candidate.mkdir();guard={};entries=[]
 for i,name in enumerate(NAMES):
  new=t.child(candidate,name);new.parent.mkdir(parents=True,exist_ok=True);new.write_text('VALUE = '+str(i+100)+'\n')
  old=None
  if i<5:
   original=t.child(root/'engine',name);original.parent.mkdir(parents=True,exist_ok=True);original.write_text('VALUE = '+str(i)+'\n');old=t.sha(original);guard[name]=old
  entries.append({'path':name,'before_sha256':old,'after_sha256':t.sha(new)})
 for i in range(41):
  name=f'stock_app/frozen_{i}.py';p=t.child(root/'engine',name);p.write_text('FROZEN = True\n');guard[name]=t.sha(p)
 data=root/'private';data.mkdir();c=sqlite3.connect(data/'synthetic.sqlite3');c.execute('create table journal(id integer primary key,note text)');c.execute('insert into journal values(1,?)',('SYNTHETIC',));c.commit();c.close()
 for i in range(18):(data/f'replay-{i}.complete.zlib').write_bytes(('SYNTHETIC_EVIDENCE_'+str(i)).encode())
 return root,candidate,guard,{'purpose':'TEST_ONLY','files':entries}
class StagingTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name).resolve();self.root,self.candidate,self.guard,self.manifest=fixture(self.base);self.before=t.files(self.root/'engine');self.private=t.files(self.root/'private')
 def tearDown(self):self.tmp.cleanup()
 def apply(self):return t.apply(self.root,self.candidate,self.guard,self.manifest)
 def private_equal(self):self.assertEqual(t.files(self.root/'private'),self.private)
 def test_all_six_apply_exact_receipt_and_financial_preservation(self):
  v=self.apply();self.assertEqual(v['state'],'COMMITTED');self.assertEqual(len(v['entries']),6);t.verify(self.root/'engine',{x['path']:x['after_sha256']for x in self.manifest['files']});self.private_equal()
 def test_rollback_restores_all_46_and_removes_only_matching_addition(self):
  self.apply();v=t.rollback(self.root,self.guard,self.manifest);self.assertEqual(v['state'],'ROLLED_BACK');self.assertEqual(t.files(self.root/'engine'),self.before);self.assertFalse((self.root/'engine'/NAMES[-1]).exists());self.private_equal()
 def test_source_hash_drift_refused_before_backup_or_write(self):
  p=self.root/'engine'/NAMES[0];p.write_bytes(p.read_bytes()+b'# drift');before=t.files(self.root/'engine')
  with self.assertRaisesRegex(t.Stop,'HASH_MISMATCH'):self.apply()
  self.assertEqual(t.files(self.root/'engine'),before);self.assertFalse((self.root/'SOURCE_RECEIPT.json').exists());self.private_equal()
 def test_frozen_unmodified_module_drift_also_refused(self):
  (self.root/'engine/stock_app/frozen_1.py').write_text('FROZEN=False\n')
  with self.assertRaisesRegex(t.Stop,'HASH_MISMATCH'):self.apply()
  self.private_equal()
 def test_candidate_hash_mismatch_refused_before_publication(self):
  (self.candidate/NAMES[1]).write_text('VALUE=999\n')
  with self.assertRaisesRegex(t.Stop,'CANDIDATE_HASH_MISMATCH'):self.apply()
  self.assertEqual(t.files(self.root/'engine'),self.before)
 def test_missing_backup_refuses_rollback_without_source_change(self):
  self.apply();(self.root/'source-backup'/NAMES[0]).unlink();before=t.files(self.root/'engine')
  with self.assertRaises(FileNotFoundError):t.rollback(self.root,self.guard,self.manifest)
  self.assertEqual(t.files(self.root/'engine'),before);self.private_equal()
 def test_corrupt_backup_refuses_rollback_without_source_change(self):
  self.apply();(self.root/'source-backup'/NAMES[0]).write_text('corrupt');before=t.files(self.root/'engine')
  with self.assertRaisesRegex(t.Stop,'BACKUP_HASH_MISMATCH'):t.rollback(self.root,self.guard,self.manifest)
  self.assertEqual(t.files(self.root/'engine'),before)
 def test_modified_new_guard_refuses_removal_or_any_rollback(self):
  self.apply();(self.root/'engine'/NAMES[-1]).write_text('VALUE=12345\n');before=t.files(self.root/'engine')
  with self.assertRaisesRegex(t.Stop,'ROLLBACK_TARGET_DRIFT'):t.rollback(self.root,self.guard,self.manifest)
  self.assertEqual(t.files(self.root/'engine'),before);self.private_equal()
 def test_receipt_manifest_tampering_refused(self):
  self.apply();p=self.root/'SOURCE_RECEIPT.json';v=json.loads(p.read_text());v['manifest_digest']='bad';t.write(p,v);before=t.files(self.root/'engine')
  with self.assertRaisesRegex(t.Stop,'RECEIPT_IDENTITY_MISMATCH'):t.rollback(self.root,self.guard,self.manifest)
  self.assertEqual(t.files(self.root/'engine'),before)
 def test_repeat_apply_refused_without_mutation(self):
  self.apply();before=t.files(self.root/'engine')
  with self.assertRaisesRegex(t.Stop,'RECEIPT_EXISTS'):self.apply()
  self.assertEqual(t.files(self.root/'engine'),before)
 def test_absent_isolation_marker_refused(self):
  (self.root/'ISOLATED_WORKSPACE.json').unlink()
  with self.assertRaisesRegex(t.Stop,'ISOLATED_MARKER_REQUIRED'):self.apply()
  self.assertEqual(t.files(self.root/'engine'),self.before)
 def test_path_traversal_refused(self):
  for name in ['../escape.py','C:/escape.py','x/../../escape.py','x\\..\\escape.py','/tmp/escape']:
   with self.subTest(name=name),self.assertRaises(t.Stop):t.child(self.root,name)
 def test_junction_or_symlink_escape_refused(self):
  outside=self.base/'outside';outside.mkdir();link=self.root/'engine/escape'
  if os.name=='nt':subprocess.run(['cmd','/c','mklink','/J',str(link),str(outside)],check=True,capture_output=True)
  else:link.symlink_to(outside,target_is_directory=True)
  with self.assertRaisesRegex(t.Stop,'REPARSE_OR_SYMLINK'):t.files(self.root/'engine')
 def test_hardlink_refused(self):
  link=self.root/'engine/linked.py';os.link(self.root/'engine'/NAMES[0],link)
  with self.assertRaisesRegex(t.Stop,'HARDLINK'):t.files(self.root/'engine')
 def test_actual_process_interruption_recovers_exact_originals(self):
  inputs=self.base/'transaction.json';t.write(inputs,{'guard':self.guard,'manifest':self.manifest})
  code='import sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import source_transaction as t;v=json.loads(Path(sys.argv[4]).read_text());t.apply(Path(sys.argv[2]),Path(sys.argv[3]),v["guard"],v["manifest"],fault_after=2)'
  r=subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(ROOT/'package'),str(self.root),str(self.candidate),str(inputs)],capture_output=True,text=True,timeout=30);self.assertEqual(r.returncode,79,r.stderr)
  with self.assertRaisesRegex(t.Stop,'RECEIPT_EXISTS'):self.apply()
  t.rollback(self.root,self.guard,self.manifest,recovery=True);self.assertEqual(t.files(self.root/'engine'),self.before);self.private_equal()
 def test_recovery_resumes_interrupted_rollback(self):
  self.apply();p=self.root/'SOURCE_RECEIPT.json';v=json.loads(p.read_text());v['state']='ROLLING_BACK';t.write(p,v);x=self.manifest['files'][0];t.atomic_bytes(self.root/'engine'/x['path'],(self.root/'source-backup'/x['path']).read_bytes());t.rollback(self.root,self.guard,self.manifest,recovery=True);self.assertEqual(t.files(self.root/'engine'),self.before)
 def test_copy_refuses_recursive_destination(self):
  with self.assertRaisesRegex(t.Stop,'COPY_PATH_OVERLAP'):host.copy_tree(self.root,self.root/'nested')
  self.assertFalse((self.root/'nested').exists())
 def test_copy_retains_exact_original_and_refuses_existing_destination(self):
  dest=self.base/'copied';before=t.files(self.root);host.copy_tree(self.root,dest);self.assertEqual(t.files(dest),before);self.assertEqual(t.files(self.root),before)
  with self.assertRaisesRegex(t.Stop,'NEW_COPY_REQUIRED'):host.copy_tree(self.root,dest)
 def test_live_path_rejected_before_any_output_creation(self):
  local=self.base/'local';live=local/'StockRecommendationEngine';live.mkdir(parents=True);output=live/'forbidden-output';env=dict(os.environ,LOCALAPPDATA=str(local));p=subprocess.run([sys.executable,'-I','-S','-B',str(ROOT/'package/prepare_windows.py'),'--initial',str(self.root),'--workspace-parent',str(output)],env=env,capture_output=True,text=True,timeout=30)
  self.assertEqual(p.returncode,2,p.stderr);self.assertIn('LIVE_PATH_OVERLAP',p.stdout);self.assertFalse(output.exists())
 def test_non_monitoring_row_change_fails_closed(self):
  before={'synthetic':{'paper_journal':{'rows':1},'holdings_monitoring':{'rows':1}}};after=json.loads(json.dumps(before));after['synthetic']['holdings_monitoring']['rows']=2;guest.financial_equal(before,after);after['synthetic']['paper_journal']['rows']=2
  with self.assertRaisesRegex(t.Stop,'NON_MONITORING_DATABASE_CHANGED'):guest.financial_equal(before,after)
 def test_sqlite_snapshot_matches_existing_collector_format(self):
  before=guest.db_snapshot(self.root/'private/synthetic.sqlite3');self.assertEqual(before['journal']['rows'],1);self.assertEqual(guest.db_snapshot(self.root/'private/synthetic.sqlite3'),before);self.private_equal()
 def test_wsb_maps_copies_only_with_loopback_offline_and_no_live_mapping(self):
  parent=self.base/'sandbox-launch';parent.mkdir();payload=self.base/'copied-input';payload.mkdir();output=parent/'reports';output.mkdir()
  class Fake:
   returncode=0
   def __init__(self,args):
    config=Path(args[1]).read_text();self_config.append(config);phase=Path(args[1]).stem;t.write(output/phase/'DONE.json',{'checks':{}})
   def poll(self):return 0
   def wait(self,timeout=None):return 0
  self_config=[]
  with patch.object(host.subprocess,'Popen',Fake):host.run('offline',payload,output,parent,Path('WindowsSandbox.exe'),1)
  import xml.etree.ElementTree as E
  config=E.fromstring(self_config[0]);self.assertEqual(config.findtext('Networking'),'Disable');maps=config.findall('MappedFolders/MappedFolder');self.assertEqual(len(maps),3);self.assertEqual([x.findtext('ReadOnly')for x in maps],['true','true','false']);self.assertEqual(maps[1].findtext('HostFolder'),str(payload));self.assertNotIn(str(self.root),self_config[0])
if __name__=='__main__':unittest.main()
