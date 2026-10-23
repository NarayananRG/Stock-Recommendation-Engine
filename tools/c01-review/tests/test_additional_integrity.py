from pathlib import Path
import concurrent.futures,contextlib,json,os,sys,tempfile,threading,time,unittest
import test_c01 as f
from stock_app.portfolio import OfficialPriceService
class AdditionalIntegrityTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'market';f.seed(self.root);self.before=f.files(self.root)
 def tearDown(self):self.tmp.cleanup()
 def test_reader_cannot_observe_mid_publication(self):
  orig=f.g._durable_write;pause=threading.Event();release=threading.Event();count=0
  def injected(path,data):
   nonlocal count
   orig(path,data)
   if Path(path).parent.resolve()==self.root.resolve() and Path(path).suffix=='.csv':
    count+=1
    if count==2:pause.set();release.wait(20)
  f.g._durable_write=injected;prices=OfficialPriceService(self.root.parent);prices.cache_roots=[self.root]
  try:
   with f.provider(f.equity(f.NEW_DAY),f.index(f.NEW_DAY)),concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    writer=pool.submit(f.m.refresh_official_session,[str(self.root)],f.NEW_DAY)
    self.assertTrue(pause.wait(10));reader=pool.submit(prices.history,'TEST000');time.sleep(.1);blocked=not reader.done();release.set()
    self.assertTrue(blocked);self.assertEqual(writer.result(timeout=30)['status'],'REFRESHED_AND_VERIFIED');self.assertEqual(reader.result(timeout=10)[-1]['date'],f.NEW_DAY)
  finally:release.set();f.g._durable_write=orig
 def test_post_commit_cleanup_error_is_not_reported_as_rollback(self):
  orig=Path.unlink
  def denied(path,*args,**kwargs):
   if path.name==f.g._PENDING:raise PermissionError('SYNTHETIC cleanup denied')
   return orig(path,*args,**kwargs)
  Path.unlink=denied
  try:
   with f.provider(f.equity(f.NEW_DAY),f.index(f.NEW_DAY)):r=f.m.refresh_official_session([str(self.root)],f.NEW_DAY)
  finally:Path.unlink=orig
  self.assertTrue(r['persisted']);self.assertEqual(r['reason_code'],'C01_COMMITTED_RECOVERY_REQUIRED');self.assertTrue((self.root/f.g._PENDING).exists())
  with f.g.cache_guard(self.root):pass
  self.assertFalse((self.root/f.g._PENDING).exists())
  for p in self.root.glob('*.csv'):self.assertIn(f.NEW_DAY,p.read_text())
 def test_staging_validation_failure_does_not_publish_any_file(self):
  old=f.m._validate_history
  def bad(path,day):
   if 'new' in Path(path).parts:raise RuntimeError('SYNTHETIC prepublish validation failure')
   return old(path,day)
  f.m._validate_history=bad
  try:
   with f.provider(f.equity(f.NEW_DAY),f.index(f.NEW_DAY)):r=f.m.refresh_official_session([str(self.root)],f.NEW_DAY)
  finally:f.m._validate_history=old
  self.assertFalse(r['persisted']);self.assertEqual(f.files(self.root),self.before);self.assertFalse((self.root/f.g._PENDING).exists())
 def test_untrusted_origin_is_not_provenance(self):
  for url in ['http://nsearchives.nseindia.com/file','https://nsearchives.nseindia.com.invalid/file','https://user:pass@www.nseindia.com/file']:
   self.assertFalse(f.m._official_url(url))
 def test_journal_path_traversal_is_refused(self):
  for name in ['../outside.csv','x/y.csv','x\\y.csv','..','']:
   with self.assertRaises(RuntimeError):f.g._safe_name(name)
if __name__=='__main__':unittest.main(verbosity=2)
