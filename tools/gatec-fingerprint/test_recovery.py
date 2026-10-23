from pathlib import Path
import ast,collections,contextlib,copy,hashlib,http.server,importlib.util,io,json,os,sqlite3,tempfile,threading,types,unittest,zlib
BASE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('recovery',BASE/'RECOVER_GUI_CURRENT_REPLAYS.py');w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
class RecoveryTests(unittest.TestCase):
 def test_nonresearch_change_rejected(self):
  with self.assertRaises(RuntimeError):w.preserved({'paper_v2_positions':collections.Counter(a=1)},{'paper_v2_positions':collections.Counter(b=1)})
 def test_old_research_replacement_rejected(self):
  with self.assertRaises(RuntimeError):w.preserved({'replay_v2_runs':collections.Counter(a=1)},{'replay_v2_runs':collections.Counter(b=1)})
 def test_added_research_allowed(self):w.preserved({'replay_v2_runs':collections.Counter(a=1)},{'replay_v2_runs':collections.Counter(a=1,b=1)})
 def test_trailing_cache_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'cache';p.write_bytes(zlib.compress(b'{}')+b'junk')
   with self.assertRaises(RuntimeError):w.unpack(p)
 def test_bounded_api_execution_and_repeat_no_posts(self):self.integration()
 def integration(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);app=root/'local/StockRecommendationEngine';engine=app/'native-engine-0.14.13';modules=engine/'stock_app';modules.mkdir(parents=True);(root/'user/Downloads').mkdir(parents=True)
   tool=root/'tool';tool.mkdir();directory=app/'historical_replay_checkpoints_v2';directory.mkdir()
   native=(BASE/'native_validator.py').read_text();(modules/'replay_v10_final.py').write_text(native)
   api=engine/'modern_ui/api.py';api.parent.mkdir();api.write_text('# synthetic api')
   marketdir=engine/'market';marketdir.mkdir();market=marketdir/'SYNTHETIC.csv';market.write_text('date,close\n2026-10-09,100\n')
   source={'replay_v10_final.py':w.sha(modules/'replay_v10_final.py'),'modern_ui/api.py':w.sha(api)}
   for n,v in [('source-preimage.json',['schema',{},source]),('market-preimage.json',['schema',{},[[str(market.resolve()),w.sha(market)]]]),('EXACT_FINGERPRINT_REPRODUCTION.json',{'cases':{'3.14.3':{'source':'current-source','market':'current-market'}}})]:(tool/n).write_text(json.dumps(v))
   ns={'Path':Path,'json':json,'math':__import__('math'),'digest':w.digest,'VERSION':'SRE_V10_PERFORMANCE_CORRECTION_1'};exec(native,ns)
   current={'source':'current-source','market':'current-market','context':'50ea935bf32af31986e7883fad64586602974940c809ae37c73e5a0d844ed3e7'}
   db=app/'engine.sqlite3';con=sqlite3.connect(db);con.execute('create table replay_v2_runs(replay_id text primary key, value text)');con.execute('create table replay_v2_sessions(replay_id text, value text)')
   for i in range(13):con.execute('create table paper_'+str(i)+'(value text)');con.execute('insert into paper_'+str(i)+' values (?)',('preserve',))
   con.commit();con.close()
   def result(day,old=False):
    conf=w.wanted(day,current)
    if old:conf['v10_market_signature']='old-market'
    coverage=[{'date':day,'replayability':'FULL_PIT_VALID'}];c={'schema':'SRE_V10_PERFORMANCE_CORRECTION_1','config':conf,'sessions':[day],'source':'old-source' if old else current['source'],'market':conf['v10_market_signature'],'runtime':{'python':'3.14.2' if old else '3.14.3'}}
    rid='SREVR2_'+hashlib.sha256(json.dumps((conf,coverage),sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()[:24]
    r={'schema':'SRE_POINT_IN_TIME_HISTORICAL_REPLAY_V2','requested_period':'CUSTOM','requested_range':{'start':day,'end':day},'coverage':coverage,'series':[dict(date=day,portfolio_nav=100000.,cash=100000.,invested_value=0.)],'sessions_replayed':1,'sessions_excluded':0,'execution_assumptions':dict(starting_capital=100000.,slippage_bps=10.,transaction_cost_bps=5.,broker_execution=False),'automatic_yfinance_fallback':False,'pit_completeness':'COMPLETE','v10':{'affects_live_decisions':False},'replay_fundamental_source_fingerprint':c['source'],'replay_market_content_signature':c['market'],'replay_context_signature':current['context'],'metrics':{},'trades':[],'replay_id':rid}
    ns['attest'](r,c);return r
   def put(r):
    key=r['v10_acceptance']['key'];(directory/(key+'.complete.zlib')).write_bytes(zlib.compress(json.dumps(dict(schema='SRE_REPLAY_CHECKPOINT_V2',key=key,value=r)).encode()))
   for day in w.DAYS:put(result(day,True))
   for i in range(12):(directory/(f'{i:064x}'+'.complete.zlib')).write_bytes(zlib.compress(json.dumps({'value':{}}).encode()))
   put(result(w.DAYS[0]));posts=[]
   class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def do_GET(self):
     if self.path=='/api/health':r={'code_root':str(engine),'database':str(db)}
     elif self.path=='/api/validation/gate-a-diagnostics':r={}
     else:r=ns['completed_evidence'](directory,current['source'],current['market'],current['context'])
     self.reply(r)
    def reply(self,r):
     b=json.dumps(r).encode();self.send_response(200);self.end_headers();self.wfile.write(b)
    def do_POST(self):
     q=__import__('urllib.parse',fromlist=['parse_qs']).parse_qs(self.path.split('?')[1]);day=q['start_date'][0];posts.append(day);r=result(day);r['replay_cache_status']='NEW_COMPUTATION';put(r)
     c=sqlite3.connect(db);c.execute('insert into replay_v2_runs values (?,?)',(r['replay_id'],json.dumps(r)));c.commit();c.close();self.reply(r)
   server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();(app/'runtime-port.txt').write_text(str(server.server_port))
   oldbase,oldos=w.BASE,w.os;w.BASE=tool;w.os=types.SimpleNamespace(name='nt',environ={'LOCALAPPDATA':str(root/'local'),'USERPROFILE':str(root/'user')})
   try:
    with contextlib.redirect_stdout(io.StringIO()):w.main()
    self.assertEqual(posts,list(w.DAYS[1:]));report=json.loads(next((root/'user/Downloads').glob('*/RECOVERY_STATUS.json')).read_text());self.assertEqual(report['status'],'PASS_THREE_CURRENT_SESSIONS');self.assertTrue(report['old_research_rows_preserved'])
    # Unique output path without waiting; no duplicate computation on repeat.
    for p in (root/'user/Downloads').iterdir():p.rename(p.with_name(p.name+'-first'))
    with contextlib.redirect_stdout(io.StringIO()):w.main()
    self.assertEqual(posts,list(w.DAYS[1:]))
   finally:w.BASE=oldbase;w.os=oldos;server.shutdown();server.server_close()
if __name__=='__main__':unittest.main(verbosity=2)
