from pathlib import Path
from dataclasses import asdict
import ast,concurrent.futures,contextlib,hashlib,importlib.util,json,os,subprocess,sys,tempfile,threading,time,unittest
import test_c01 as f
from stock_app.portfolio import OfficialPriceService
from stock_app.historical import HistoricalTechnicalPredictionAdapter
class RecoveryReaderTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'market';f.seed(self.root);self.before=f.files(self.root)
 def tearDown(self):self.tmp.cleanup()
 def child(self,mode):
  env=dict(os.environ,C01_TEST_ENGINE=str(f.ENGINE));return subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('crash_worker.py')),str(self.root),mode],env=env,capture_output=True,text=True,timeout=60)
 def prices(self):
  obj=OfficialPriceService(self.root.parent);obj.cache_roots=[self.root];return obj
 def test_hard_process_exit_recovers_before_price_reader_returns(self):
  r=self.child('mid');self.assertEqual(r.returncode,73,r.stderr);self.assertTrue((self.root/f.g._PENDING).exists());self.assertNotEqual(f.files(self.root),self.before)
  bars=self.prices().history('TEST000',5000);self.assertEqual(bars[-1]['date'],f.BASE_DAY);self.assertEqual(f.files(self.root),self.before);self.assertFalse((self.root/f.g._PENDING).exists())
 def test_hard_process_exit_recovers_before_historical_reader_returns(self):
  self.assertEqual(self.child('mid').returncode,73)
  bars=HistoricalTechnicalPredictionAdapter._read_bars(self.root/'TEST000.NS.csv');self.assertEqual(bars[-1].date,f.BASE_DAY);self.assertEqual(f.files(self.root),self.before)
 def test_committed_but_pending_exit_finalizes_whole_new_batch(self):
  r=self.child('committed');self.assertEqual(r.returncode,74,r.stderr);self.assertTrue((self.root/f.g._PENDING).exists());bars=self.prices().history('TEST000',5000)
  self.assertEqual(bars[-1]['date'],f.NEW_DAY);self.assertFalse((self.root/f.g._PENDING).exists())
  for p in self.root.glob('*.csv'):self.assertIn(f.NEW_DAY,p.read_text())
 def test_corrupt_backup_causes_fail_closed_not_forced_restore(self):
  self.assertEqual(self.child('mid').returncode,73);pending=json.loads((self.root/f.g._PENDING).read_text());archive=self.root/f.g._ARCHIVE/pending['transaction'];(archive/'old/TEST000.NS.csv').write_bytes(b'SYNTHETIC_CORRUPT');before=f.files(self.root)
  with self.assertRaisesRegex(RuntimeError,'BACKUP_CHANGED'):self.prices().history('TEST000')
  self.assertEqual(f.files(self.root),before);self.assertTrue((self.root/f.g._PENDING).exists())
 def test_reader_waits_for_process_lock(self):
  env=dict(os.environ,C01_TEST_ENGINE=str(f.ENGINE));p=subprocess.Popen([sys.executable,'-B',str(Path(__file__).with_name('crash_worker.py')),str(self.root),'hold'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  try:
   deadline=time.monotonic()+20
   while not (self.root/'SYNTHETIC_LOCK_HELD').exists():
    if p.poll() is not None:raise AssertionError(p.communicate())
    self.assertLess(time.monotonic(),deadline);time.sleep(.02)
   start=time.monotonic();self.prices().history('TEST000');self.assertGreater(time.monotonic()-start,.25)
  finally:p.communicate(timeout=20)
  self.assertEqual(p.returncode,0)
 def test_two_processes_refresh_without_duplicate_sessions(self):
  env=dict(os.environ,C01_TEST_ENGINE=str(f.ENGINE));commands=[sys.executable,'-B',str(Path(__file__).with_name('crash_worker.py')),str(self.root),'normal']
  procs=[subprocess.Popen(commands,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
  for p in procs:
   output=p.communicate(timeout=60);self.assertEqual(p.returncode,0,output)
  for p in self.root.glob('*.csv'):self.assertEqual(p.read_text().count(f.NEW_DAY),1)
 def test_cached_price_reader_invalidates_after_publication(self):
  obj=self.prices();old=obj.history('TEST000');self.assertEqual(len(old),1)
  with f.provider(f.equity(f.NEW_DAY,'101'),f.index(f.NEW_DAY)):r=f.m.refresh_official_session([str(self.root)],f.NEW_DAY)
  self.assertEqual(r['status'],'REFRESHED_AND_VERIFIED');new=obj.history('TEST000');self.assertEqual(len(new),2);self.assertEqual(new[-1]['close'],101)
 def test_market_signature_and_api_status_entry_points_use_guard(self):
  for rel,name in [('stock_app/replay_v10.py','market_signature'),('modern_ui/api.py','_inspect_data_repo')]:
   tree=ast.parse((f.ENGINE/rel).read_text());fn=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name)
   self.assertTrue(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='guarded' for n in fn.decorator_list))
 def test_market_signature_recovers_before_hashing(self):
  source=ast.parse((f.ENGINE/'stock_app/replay_v10.py').read_text());fn=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='market_signature')
  ns={'Path':Path,'file_hash':f.g.file_hash,'digest':lambda v:hashlib.sha256(json.dumps(v,sort_keys=True).encode()).hexdigest(),'SCHEMA':'SRE_REPLAY_V10_1','RUNTIME':{'synthetic':'fixture'},'guarded':f.g.guarded}
  exec(compile(ast.Module(body=[fn],type_ignores=[]),'market-signature-under-test','exec'),ns);before=ns['market_signature'](self.prices());self.assertEqual(self.child('mid').returncode,73);after=ns['market_signature'](self.prices());self.assertEqual(before,after);self.assertEqual(f.files(self.root),self.before)
if __name__=='__main__':unittest.main(verbosity=2)
