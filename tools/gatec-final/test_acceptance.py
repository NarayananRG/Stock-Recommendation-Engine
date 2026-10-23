from pathlib import Path
import importlib.util,tempfile,sqlite3,json,unittest,sys
BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(BASE));import accept_windows as w
class AcceptanceTests(unittest.TestCase):
 def test_consistent_live_wal_backup_and_restore(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'live.sqlite3';c=sqlite3.connect(p);c.execute('pragma journal_mode=wal');c.execute('create table paper(value text)');c.execute("insert into paper values ('immutable')");c.commit()
   try:
    dst=Path(t)/'backup.sqlite3';w.backup_db(p,dst);self.assertEqual(w.db_snapshot(p),w.db_snapshot(dst));self.assertEqual(c.execute('select count(*) from paper').fetchone()[0],1)
   finally:c.close()
 def test_backup_refuses_existing_target(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'existing';p.write_bytes(b'preserve')
   with self.assertRaises(w.InvariantError):w.backup_db(p,p)
   self.assertEqual(p.read_bytes(),b'preserve')
 def test_only_three_readonly_routes(self):
  with self.assertRaises(w.InvariantError):w.get(1,'/api/validation/paper-portfolio')
  with self.assertRaises(w.InvariantError):w.get(1,'/api/validation/historical-replay')
 def test_no_false_closed(self):
  with tempfile.TemporaryDirectory() as t:
   r={'checks':{'a':{'status':'PASS','evidence':'x'},'b':{'status':'BLOCKED','evidence':'not run'}}};w.save_report(Path(t),r);self.assertEqual(r['gate_c'],'BLOCKED');r['checks']['b']['status']='FAIL';w.save_report(Path(t),r);self.assertEqual(r['gate_c'],'FAIL')
 def test_sql_identifiers_and_blobs(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'a.db';c=sqlite3.connect(p);c.execute('create table "odd""name"(a blob)');c.execute('insert into "odd""name" values (?)',(b'bytes',));c.commit();c.close();self.assertEqual(w.db_snapshot(p)['odd"name']['rows'],1)
 def test_source_refresh_contract_known_failure(self):
  from source_contract_checks import check
  result=check(BASE/'source_fixture_official_refresh.py');self.assertEqual(result['same_session_conflicts_replaced'],200);self.assertEqual(result['no_silent_verified_row_replacement'],'FAIL');self.assertTrue(result['identical_row_retry_idempotent']);self.assertTrue(result['unavailable_preserves_rows']);self.assertFalse(result['automatic_yfinance_fallback'])
 def test_copy_hashes_and_exclusions(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t)/'source';root.mkdir();(root/'config.json').write_text('{}');(root/'__pycache__').mkdir();(root/'__pycache__/ignore').write_text('x');dst=Path(t)/'copy';r=w.guarded_copy(root,dst,('__pycache__',));self.assertEqual(set(r),{'config.json'});self.assertEqual(w.sha(root/'config.json'),w.sha(dst/'config.json'))
if __name__=='__main__':unittest.main(verbosity=2)
