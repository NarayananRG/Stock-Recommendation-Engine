"""Synthetic market fixtures only. No application databases or personal data."""
from pathlib import Path
import ast,concurrent.futures,contextlib,copy,csv,hashlib,hmac,io,json,os,sqlite3,subprocess,sys,tempfile,threading,time,unittest,zipfile
from datetime import datetime,timezone,timedelta
ROOT=Path(__file__).resolve().parents[1]
ENGINE=Path(os.environ.get('C01_TEST_ENGINE',ROOT/'candidate/engine'))
sys.path.insert(0,str(ENGINE))
from stock_app import official_daily_refresh as m
from stock_app import official_cache_guard as g
BASE_DAY='2026-10-22';NEW_DAY='2026-10-23'
FIELDS=['TradDt','TckrSymb','SctySrs','ISIN','OpnPric','HghPric','LwPric','ClsPric','TtlTradgVol']
def equity(day,close='100',count=200,changes=None,duplicate=False):
 out=io.StringIO();w=csv.DictWriter(out,fieldnames=FIELDS);w.writeheader()
 for i in range(count):
  row=dict(zip(FIELDS,[day,f'TEST{i:03d}','EQ',f'TEST{i:08d}','100',str(max(102,float(close))) if close not in ('NaN','Infinity') else '102','99',close,'1000']))
  row.update((changes or {}).get(i,{}));w.writerow(row)
  if duplicate and i==0:w.writerow(row)
 b=io.BytesIO()
 with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('official.csv',out.getvalue())
 return b.getvalue()
def index(day,close='100'):
 return ('Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value\nNIFTY 50,'+datetime.strptime(day,'%Y-%m-%d').strftime('%d-%m-%Y')+',100,102,99,'+close+'\n').encode()
def seed(root,day=BASE_DAY):
 root.mkdir(parents=True,exist_ok=True)
 for i in range(200):(root/(f'TEST{i:03d}.NS.csv')).write_bytes(('Date,Open,High,Low,Close,Volume\r\n'+day+',100.00,102,99,100,1000\r\n').encode())
 (root/'INDEX_NSEI.csv').write_bytes(('Date,Open,High,Low,Close,Volume\r\n'+day+',100.00,102,99,100,0\r\n').encode())
def files(root):return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob('*.csv')}
class Session:
 def __init__(self,eq,idx):self.eq=eq;self.idx=idx;self.headers={};self.calls=[]
 def get(self,url,**kwargs):
  self.calls.append(url)
  content=self.idx if '/content/indices/' in url else self.eq
  return m._Response(200,{'content-type':'application/zip' if content[:2]==b'PK' else 'text/csv'},content)
@contextlib.contextmanager
def provider(eq,idx):
 old=m._session;sess=Session(eq,idx);m._session=lambda:sess
 try:yield sess
 finally:m._session=old
class C01Tests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'market';seed(self.root);self.before=files(self.root)
 def tearDown(self):self.tmp.cleanup()
 def run_refresh(self,day=BASE_DAY,close='100',**kw):
  with provider(equity(day,close),index(day)) as sess:r=m.refresh_official_session([str(self.root)],day,**kw)
  return r
 def assert_preserved(self):self.assertEqual(files(self.root),self.before)
 def test_identical_official_refresh_preserves_exact_csv_bytes(self):
  r=self.run_refresh();self.assertEqual(r['status'],'ALREADY_CURRENT');self.assert_preserved()
 def test_all_200_conflicting_stock_rows_rejected_not_overwritten(self):
  r=self.run_refresh(close='101');self.assertEqual(r['reason_code'],'C01_EXISTING_ROW_CONFLICT');self.assertFalse(r['persisted']);self.assert_preserved()
 def test_one_conflict_rejects_entire_batch(self):
  with provider(equity(BASE_DAY,changes={199:{'ClsPric':'101'}}),index(BASE_DAY)):r=m.refresh_official_session([str(self.root)],BASE_DAY)
  self.assertEqual(r['reason_code'],'C01_EXISTING_ROW_CONFLICT');self.assert_preserved()
 def test_conflicting_index_rejects_all(self):
  with provider(equity(BASE_DAY),index(BASE_DAY,'101')):r=m.refresh_official_session([str(self.root)],BASE_DAY)
  self.assertEqual(r['reason_code'],'C01_EXISTING_ROW_CONFLICT');self.assert_preserved()
 def test_valid_new_session_appends_all_201_preserving_old_prefixes(self):
  old={p.name:p.read_bytes() for p in self.root.glob('*.csv')};r=self.run_refresh(NEW_DAY,'101');self.assertEqual(r['status'],'REFRESHED_AND_VERIFIED')
  for p in self.root.glob('*.csv'):
   self.assertTrue(p.read_bytes().startswith(old[p.name]));self.assertEqual(len(list(csv.DictReader(io.StringIO(p.read_text())))),2)
 def test_199_of_200_provider_response_is_not_publishable(self):
  with provider(equity(NEW_DAY,count=199),index(NEW_DAY)):r=m.refresh_official_session([str(self.root)],NEW_DAY)
  self.assertEqual(r['status'],'OFFICIAL_COVERAGE_FAILED');self.assert_preserved()
 def test_invalid_provider_values_cannot_publish(self):
  for changes in [{'ClsPric':'NaN'},{'HghPric':'Infinity'},{'LwPric':'101'},{'TtlTradgVol':'-1'},{'TtlTradgVol':'1.5'},{'ClsPric':''}]:
   with self.subTest(changes=changes),provider(equity(NEW_DAY,changes={0:changes}),index(NEW_DAY)):
    r=m.refresh_official_session([str(self.root)],NEW_DAY);self.assertFalse(r['persisted']);self.assert_preserved()
 def test_mixed_or_noncanonical_source_dates_rejected(self):
  for invalid in ['2026-10-22','2026-10-23T00:00:00','2026-02-30']:
   with self.subTest(invalid=invalid),provider(equity(NEW_DAY,changes={0:{'TradDt':invalid}}),index(NEW_DAY)):
    r=m.refresh_official_session([str(self.root)],NEW_DAY);self.assertEqual(r['status'],'OFFICIAL_SCHEMA_ERROR');self.assert_preserved()
 def test_duplicate_provider_symbol_rejected(self):
  with provider(equity(NEW_DAY,duplicate=True),index(NEW_DAY)):r=m.refresh_official_session([str(self.root)],NEW_DAY)
  self.assertEqual(r['status'],'OFFICIAL_COVERAGE_FAILED');self.assert_preserved()
 def test_duplicate_local_date_rejected_without_repairing_history(self):
  p=self.root/'TEST000.NS.csv';p.write_bytes(p.read_bytes()+p.read_bytes().splitlines(keepends=True)[1]);self.before=files(self.root)
  r=self.run_refresh(NEW_DAY);self.assertFalse(r['persisted']);self.assert_preserved()
 def test_holiday_rejected_before_provider_access(self):
  with provider(equity('2026-10-20'),index('2026-10-20')) as p:r=m.refresh_official_session([str(self.root)],'2026-10-20')
  self.assertEqual(r['reason_code'],'C01_SESSION_REJECTED');self.assertEqual(p.calls,[]);self.assert_preserved()
 def test_special_sunday_session_is_accepted(self):
  for p in self.root.glob('*.csv'):p.write_bytes(p.read_bytes().replace(BASE_DAY.encode(),b'2026-01-30'))
  r=self.run_refresh('2026-02-01');self.assertEqual(r['status'],'REFRESHED_AND_VERIFIED')
 def test_repeat_new_refresh_is_idempotent(self):
  self.assertEqual(self.run_refresh(NEW_DAY)['status'],'REFRESHED_AND_VERIFIED');a=files(self.root);manifest=(self.root/'.sre_official_refresh_manifest.json').read_bytes()
  self.assertEqual(self.run_refresh(NEW_DAY)['status'],'ALREADY_CURRENT');self.assertEqual(files(self.root),a);self.assertEqual((self.root/'.sre_official_refresh_manifest.json').read_bytes(),manifest)
 def authorization(self,eq):
  p=self.root/'TEST000.NS.csv';source=hashlib.sha256(eq).hexdigest();keys={'SYNTHETIC_REVIEWER_A':os.urandom(32),'SYNTHETIC_REVIEWER_B':os.urandom(32)}
  body={'schema':'SRE_C01_REVIEWED_CORRECTION_V1','session':BASE_DAY,'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'reason':'SYNTHETIC verified correction fixture','reviewers':list(keys),'independent_official_evidence':{'url':'https://www.nseindia.com/api/SYNTHETIC_SECOND_EVIDENCE','source_sha256':'a'*64},'changes':[{'file':p.name,'old_file_sha256':g.file_hash(p),'old_row_sha256':m._row_hash(BASE_DAY,('100','102','99','100','1000')),'new_row_sha256':m._row_hash(BASE_DAY,('100','102','99','101','1000')),'source_sha256':source}]}
  raw=json.dumps(body,sort_keys=True,separators=(',',':'),allow_nan=False).encode();token={'body':body,'signatures':{i:hmac.new(k,raw,'sha256').hexdigest() for i,k in keys.items()}};return token,keys
 def test_two_authenticated_local_reviewers_allow_only_bound_correction(self):
  eq=equity(BASE_DAY,changes={0:{'ClsPric':'101'}});token,keys=self.authorization(eq)
  with provider(eq,index(BASE_DAY)):r=m.refresh_official_session([str(self.root)],BASE_DAY,correction_authorization=token,correction_trust=keys)
  self.assertEqual(r['status'],'REFRESHED_AND_VERIFIED');after=files(self.root);self.assertEqual(sum(after[k]!=self.before[k] for k in after),1)
  manifest=json.loads((self.root/'.sre_official_refresh_manifest.json').read_text());audit=manifest['rows'][0];self.assertEqual(audit['action'],'REVIEWED_CORRECTION');self.assertNotEqual(audit['old_row_sha256'],audit['new_row_sha256']);self.assertEqual(audit['review']['reviewers'],list(keys))
 def test_unauthenticated_or_tampered_correction_refused(self):
  eq=equity(BASE_DAY,changes={0:{'ClsPric':'101'}});token,keys=self.authorization(eq);token['body']['reason']='tampered'
  with provider(eq,index(BASE_DAY)):r=m.refresh_official_session([str(self.root)],BASE_DAY,correction_authorization=token,correction_trust=keys)
  self.assertEqual(r['reason_code'],'C01_EXISTING_ROW_CONFLICT');self.assert_preserved()
 def test_missing_second_trust_key_refused(self):
  eq=equity(BASE_DAY,changes={0:{'ClsPric':'101'}});token,keys=self.authorization(eq);keys.pop(next(iter(keys)))
  with provider(eq,index(BASE_DAY)):r=m.refresh_official_session([str(self.root)],BASE_DAY,correction_authorization=token,correction_trust=keys)
  self.assertFalse(r['persisted']);self.assert_preserved()
 def test_correction_is_bound_to_exact_source_payload(self):
  eq=equity(BASE_DAY,changes={0:{'ClsPric':'101'}});token,keys=self.authorization(eq);different=equity(BASE_DAY,changes={0:{'ClsPric':'101','ISIN':'SYNTHETIC_CHANGED'}})
  with provider(different,index(BASE_DAY)):r=m.refresh_official_session([str(self.root)],BASE_DAY,correction_authorization=token,correction_trust=keys)
  self.assertFalse(r['persisted']);self.assert_preserved()
 def test_accepted_publication_retains_raw_sources_and_old_new_hashes(self):
  r=self.run_refresh(NEW_DAY);archive=self.root/g._ARCHIVE/r['transaction_id'];journal=json.loads((archive/'journal.json').read_text());self.assertEqual(len(journal['entries']),202)
  for name,h in journal['source_artifacts'].items():self.assertEqual(g.file_hash(archive/'sources'/name),h)
  manifest=json.loads((self.root/'.sre_official_refresh_manifest.json').read_text());self.assertIsNone(manifest['provenance']['equity']['source_publication_time']);self.assertIn('retrieved_at',manifest['provenance']['equity'])
 def test_missing_provenance_never_publishes(self):
  old=m._download_candidates;m._download_candidates=lambda *a,**k:(equity(NEW_DAY),{'url':'https://nsearchives.nseindia.com/no-proof','http_status':200})
  try:r=m.refresh_official_session([str(self.root)],NEW_DAY)
  finally:m._download_candidates=old
  self.assertEqual(r['status'],'OFFICIAL_SCHEMA_ERROR');self.assert_preserved()
 def test_wrong_source_hash_rejected(self):
  eq=equity(NEW_DAY);old=m._download_candidates;m._download_candidates=lambda *a,**k:(eq,{'url':'https://nsearchives.nseindia.com/file','http_status':200,'source_sha256':'0'*64,'retrieved_at':datetime.now(timezone.utc).isoformat()})
  try:r=m.refresh_official_session([str(self.root)],NEW_DAY)
  finally:m._download_candidates=old
  self.assertFalse(r['persisted']);self.assert_preserved()
 def test_no_unapproved_fallback_on_official_failure(self):
  old=m._download_candidates
  def fail(*a,**k):raise m.OfficialDataNotReady('SYNTHETIC endpoint unavailable')
  m._download_candidates=fail
  try:r=m.refresh_official_session([str(self.root)],NEW_DAY)
  finally:m._download_candidates=old
  self.assertEqual(r['status'],'OFFICIAL_NOT_READY');self.assertFalse(r['automatic_yfinance_fallback']);self.assert_preserved()
 def test_index_invalid_or_missing_session_rejected(self):
  for idx in [index(NEW_DAY,'NaN'),index(NEW_DAY).replace(b'23-10-2026',b'')]:
   with provider(equity(NEW_DAY),idx):r=m.refresh_official_session([str(self.root)],NEW_DAY)
   self.assertFalse(r['persisted']);self.assert_preserved()
 def test_exception_mid_batch_rolls_back_all_original_csv_and_manifest(self):
  orig=g._durable_write;calls=[]
  def injected(path,data):
   if Path(path).parent.resolve()==self.root.resolve() and str(path).endswith('.csv'):
    calls.append(str(path))
    if len(calls)==3:raise OSError('SYNTHETIC third file failed')
   return orig(path,data)
  g._durable_write=injected
  try:r=self.run_refresh(NEW_DAY)
  finally:g._durable_write=orig
  self.assertFalse(r['persisted']);self.assert_preserved();self.assertFalse((self.root/g._PENDING).exists());self.assertFalse((self.root/'.sre_official_refresh_manifest.json').exists())
 def test_concurrent_refreshes_do_not_duplicate_or_mix(self):
  with provider(equity(NEW_DAY),index(NEW_DAY)):
   with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:r=list(pool.map(lambda _:m.refresh_official_session([str(self.root)],NEW_DAY),range(2)))
  self.assertEqual(sorted(x['status'] for x in r),['ALREADY_CURRENT','REFRESHED_AND_VERIFIED'],r)
  for p in self.root.glob('*.csv'):self.assertEqual(len(list(csv.DictReader(io.StringIO(p.read_text())))),2)
 def test_all_target_databases_and_saved_replays_unchanged(self):
  outside=self.root.parent/'state';outside.mkdir();db=outside/'synthetic.sqlite3';c=sqlite3.connect(db)
  for name in ['paper_portfolio','paper_orders','paper_fills','paper_journal']:
   c.execute('create table '+name+'(id text primary key,value text)');c.execute('insert into '+name+' values (?,?)',('SYNTHETIC-ID','SYNTHETIC-IMMUTABLE'))
  c.commit();c.close();evidence=outside/'research.complete.zlib';evidence.write_bytes(b'SYNTHETIC NEVER PROMOTE');before={p.name:g.file_hash(p) for p in outside.iterdir()}
  self.run_refresh(NEW_DAY);self.assertEqual({p.name:g.file_hash(p) for p in outside.iterdir()},before)
if __name__=='__main__':unittest.main(verbosity=2)
