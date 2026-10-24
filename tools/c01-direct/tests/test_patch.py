from pathlib import Path
import sys,unittest,tempfile,json,hashlib,subprocess,sqlite3,os
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'package'))
import c01_patch as p
class PatchTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.engine=self.root/'engine';self.engine.mkdir();self.area=self.root/'receipt';self.area.mkdir();self.package=self.root/'package';self.candidate=self.package/'candidate';self.candidate.mkdir(parents=True)
  self.guard={};self.rows=[]
  for i in range(6):
   n=f'pkg/module{i}.py';a=f'old{i}=1\n'.encode() if i<5 else None;b=f'new{i}=2\n'.encode()
   if a is not None:p.atomic(self.engine/n,a);self.guard[n]=hashlib.sha256(a).hexdigest()
   p.atomic(self.candidate/n,b)
   self.rows.append({'path':n,'before_sha256':hashlib.sha256(a).hexdigest() if a else None,'after_sha256':hashlib.sha256(b).hexdigest()})
  self.manifest={'files':self.rows};p.atomic(self.engine/'frozen.py',b'unchanged=1\n');self.guard['frozen.py']=p.sha(self.engine/'frozen.py')
  for v in self.rows:
   if v['before_sha256']:p.atomic(self.area/'originals'/v['path'],(self.engine/v['path']).read_bytes())
  self.receipt={'schema':'SRE_C01_DIRECT_RECEIPT_V1','engine':str(self.engine),'transaction':'a'*32,'guard_digest':p.digest(self.guard),'manifest_digest':p.digest(self.manifest),'entries':self.rows,'state':'PREPARED'};p.write(self.area/'RECEIPT.json',self.receipt)
 def tearDown(self):self.tmp.cleanup()
 def publish(self):p.publish(self.engine,self.area,self.package,self.manifest)
 def restore(self):return p.restore(self.engine,self.area,self.guard,self.manifest,package=self.package)
 def original(self):p.verify(self.engine,p.expected(self.guard,self.manifest,False))
 def test_six_file_apply_and_committed_rollback(self):
  self.publish();p.verify(self.engine,p.expected(self.guard,self.manifest,True));r=p.load(self.area/'RECEIPT.json');r['state']='COMMITTED';p.write(self.area/'RECEIPT.json',r);self.restore();self.original();self.assertEqual(p.load(self.area/'RECEIPT.json')['state'],'ROLLED_BACK')
 def test_hard_exit_every_publication_boundary_recovers(self):
  for i in range(1,7):
   code="import sys;sys.path.insert(0,sys.argv[1]);import c01_patch as p;from pathlib import Path;p.publish(Path(sys.argv[2]),Path(sys.argv[3]),Path(sys.argv[4]),p.load(Path(sys.argv[3])/'MANIFEST.json'),fault=int(sys.argv[5]))"
   p.write(self.area/'MANIFEST.json',self.manifest);p.write(self.area/'RECEIPT.json',self.receipt)
   out=subprocess.run([sys.executable,'-B','-c',code,str(Path(p.__file__).parent),str(self.engine),str(self.area),str(self.package),str(i)],capture_output=True)
   self.assertEqual(out.returncode,79,out.stderr);self.restore();self.original()
 def test_partial_temp_write_recovers(self):
  v=self.rows[0];t=p.source_temp(self.engine/v['path'],'a'*32,'new');t.write_bytes(b'new');self.restore();self.assertFalse(t.exists());self.original()
 def test_foreign_temp_content_refused_before_restoration(self):
  self.publish();t=p.source_temp(self.engine/self.rows[0]['path'],'a'*32,'new');t.write_bytes(b'FOREIGN');before=p.inventory(self.engine)
  with self.assertRaisesRegex(p.Stop,'OWNED_TEMP_DRIFT'):self.restore()
  self.assertEqual(p.inventory(self.engine),before)
 def test_partial_rollback_resumes(self):
  self.publish();r=dict(self.receipt,state='ROLLING_BACK');p.write(self.area/'RECEIPT.json',r);p.atomic(self.engine/self.rows[0]['path'],(self.area/'originals'/self.rows[0]['path']).read_bytes());self.restore();self.original()
 def test_late_target_drift_no_partial_rollback(self):
  self.publish();p.atomic(self.engine/self.rows[-1]['path'],b'edited=1\n');before=p.inventory(self.engine)
  with self.assertRaisesRegex(p.Stop,'ROLLBACK_TARGET_DRIFT'):self.restore()
  self.assertEqual(p.inventory(self.engine),before)
 def test_corrupt_last_backup_no_partial_rollback(self):
  self.publish();p.atomic(self.area/'originals'/self.rows[-2]['path'],b'bad');before=p.inventory(self.engine)
  with self.assertRaisesRegex(p.Stop,'BACKUP_HASH'):self.restore()
  self.assertEqual(p.inventory(self.engine),before)
 def test_frozen_rule_drift_refused(self):
  self.publish();p.atomic(self.engine/'frozen.py',b'wrong');before=p.inventory(self.engine)
  with self.assertRaisesRegex(p.Stop,'SOURCE_HASH_MISMATCH'):self.restore()
  self.assertEqual(p.inventory(self.engine),before)
 def test_receipt_engine_tampering_refused(self):
  self.publish();r=dict(self.receipt,engine=str(self.root));p.write(self.area/'RECEIPT.json',r)
  with self.assertRaisesRegex(p.Stop,'RECEIPT_IDENTITY'):self.restore()
 def test_receipt_entries_tampering_refused(self):
  r=dict(self.receipt,entries=[]);p.write(self.area/'RECEIPT.json',r)
  with self.assertRaisesRegex(p.Stop,'RECEIPT_IDENTITY'):self.restore()
 def test_deleted_new_guard_while_committed_refused(self):
  self.publish();(self.engine/self.rows[-1]['path']).unlink();p.write(self.area/'RECEIPT.json',dict(self.receipt,state='COMMITTED'))
  with self.assertRaisesRegex(p.Stop,'ROLLBACK_TARGET_DRIFT'):self.restore()
 def test_no_double_rollback(self):
  self.restore()
  with self.assertRaisesRegex(p.Stop,'RECEIPT_STATE'):self.restore()
 def test_path_traversal_refused(self):
  for n in ('../x','/x','a//b','x:y','a/../b','a\\b'):
   with self.assertRaises(p.Stop):p.child(self.engine,n)
 def test_symlink_refused(self):
  try:(self.engine/'escape').symlink_to(self.root,target_is_directory=True)
  except OSError:self.skipTest('OS denied symlink creation')
  with self.assertRaisesRegex(p.Stop,'REPARSE'):p.inventory(self.engine)
 def test_hardlink_refused(self):
  os.link(self.engine/'frozen.py',self.engine/'duplicate')
  with self.assertRaisesRegex(p.Stop,'HARDLINK'):p.inventory(self.engine)
 def test_all_accounting_tables_and_market_files_preserved(self):
  data=self.root/'data';data.mkdir();db=data/'paper.sqlite3';c=sqlite3.connect(db);c.executescript("CREATE TABLE positions(id text,qty integer,cost real);INSERT INTO positions VALUES('original-entry',36,545.82);CREATE TABLE journal(id integer,amount real);INSERT INTO journal VALUES(1,61446.26);");c.close();(data/'history.csv').write_bytes(b'unchanged official history');before=p.inventory(data);s=p.sql_snapshot(self.area/'db-before',data,before);self.publish();self.restore();after=p.sql_snapshot(self.area/'db-after',data,p.inventory(data));self.assertEqual(s,after);self.assertEqual(before,p.inventory(data));self.assertEqual(s['paper.sqlite3']['all_tables']['positions']['rows'],1)
 def test_wal_snapshot_uses_copy_and_preserves_live_bytes(self):
  data=self.root/'data';data.mkdir();db=data/'paper.sqlite3';c=sqlite3.connect(db);c.execute('PRAGMA journal_mode=WAL');c.execute('CREATE TABLE journal(id)');c.execute('INSERT INTO journal VALUES(17)');c.commit();before=p.inventory(data);out=p.sql_snapshot(self.area/'wal-copy',data,before);self.assertEqual(out['paper.sqlite3']['all_tables']['journal']['rows'],1);self.assertEqual(before,p.inventory(data));c.close()
 def test_corrupt_database_fails(self):
  data=self.root/'data';data.mkdir();(data/'broken.db').write_bytes(b'SQLite format 3\x00'+b'garbage'*100)
  with self.assertRaises((p.Stop,sqlite3.DatabaseError)):p.sql_snapshot(self.area/'bad-copy',data,p.inventory(data))
 def test_import_probe_blocks_live_write_network_database(self):
  root=self.root/'probe';(root/'stock_app').mkdir(parents=True);(root/'stock_app/__init__.py').write_text('')
  for code in ["open(%r,'w').write('bad')"%str(self.root/'outside'),"import socket;socket.socket().connect(('127.0.0.1',9))","import sqlite3;sqlite3.connect(':memory:')"]:
   (root/'stock_app/official_cache_guard.py').write_text(code)
   r=subprocess.run([sys.executable,'-I','-B',str(Path(p.__file__).parent/'import_probe.py'),str(root),str(self.root/'deps')],capture_output=True,text=True)
   self.assertNotEqual(r.returncode,0);self.assertIn('REFUSED' if 'outside' not in code else 'OUTSIDE',r.stderr)
  self.assertFalse((self.root/'outside').exists())
 def test_import_probe_rejects_foreign_module_origin(self):
  root=self.root/'probe';root.mkdir();r=subprocess.run([sys.executable,'-I','-B',str(Path(p.__file__).parent/'import_probe.py'),str(root),str(self.root/'deps')],capture_output=True,text=True);self.assertNotEqual(r.returncode,0)
 def test_transaction_identifier_injection_refused(self):
  for tx in ('../x','A'*32,'a'*31):
   with self.assertRaises(p.Stop):p.source_temp(self.engine/'file',tx,'new')
 @unittest.skipUnless(os.name=='nt','Windows file-share API required')
 def test_windows_protected_handle_refuses_write_delete(self):
  data=self.root/'protected';data.mkdir();f=data/'journal';f.write_bytes(b'original')
  with p.protect_files(data,set()):
   with self.assertRaises(OSError):f.write_bytes(b'change')
   with self.assertRaises(OSError):f.unlink()
   self.assertEqual(f.read_bytes(),b'original')
  self.assertEqual(f.read_bytes(),b'original')
 @unittest.skipUnless(os.name=='nt','Windows CIM required')
 def test_windows_cim_process_inventory_is_readable(self):
  r=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',"@(Get-CimInstance Win32_Process | Select-Object ProcessId,Name,ExecutablePath,CommandLine) | ConvertTo-Json -Depth 3 -Compress"],capture_output=True,text=True,timeout=40)
  self.assertEqual(r.returncode,0,r.stderr);rows=json.loads(r.stdout);self.assertTrue(any(v['ProcessId']==os.getpid() for v in rows))
if __name__=='__main__':unittest.main(verbosity=2)
