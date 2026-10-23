from pathlib import Path
import contextlib,http.server,io,json,os,sqlite3,sys,tempfile,threading,unittest
sys.path.insert(0,str(Path(__file__).resolve().parent));import accept_windows as w
class NativeCollectorIntegration(unittest.TestCase):
 def test_initial_backups_restore_and_no_live_writes(self):
  base=Path(__file__).resolve().parent
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);app=root/'local/StockRecommendationEngine';engine=app/'native-engine-0.14.13';(engine/'stock_app').mkdir(parents=True);(engine/'modern_ui').mkdir()
   (engine/'stock_app/official_daily_refresh.py').write_bytes((base/'source_fixture_official_refresh.py').read_bytes());(engine/'modern_ui/api.py').write_text('# synthetic identity guard')
   package=root/'package';package.mkdir();w.write(package/'source-guard.json',{n:w.sha(engine/n) for n in ['stock_app/official_daily_refresh.py','modern_ui/api.py']});template=json.loads((base/'GATE_C_MACHINE_RESULTS.json').read_text());template['expected_holdings']={'SYNTHETIC_A':1,'SYNTHETIC_B':2};w.write(package/'GATE_C_MACHINE_RESULTS.json',template)
   for name in ['stock_recommendation_engine.sqlite3','phase81_validation.sqlite3']:
    c=sqlite3.connect(app/name);c.execute('create table paper_v2_portfolios(portfolio_id text,status text,state_json text)');c.execute('insert into paper_v2_portfolios values (?,?,?)',('immutable','ACTIVE',json.dumps({'nav':12345.67,'cash':6789.01,'invested_value':5556.66})));c.execute('create table paper_v2_positions(position_id text,portfolio_id text,symbol text,state text,qty integer,entry_price real,position_json text)')
    for s,q in [('SYNTHETIC_A',1),('SYNTHETIC_B',2)]:c.execute('insert into paper_v2_positions values (?,?,?,?,?,?,?)',(s,'immutable',s,'OPEN',q,100,'{}'))
    c.commit();c.close()
   evidence=app/'historical_replay_checkpoints_v2';evidence.mkdir()
   for i in range(18):(evidence/(str(i)+'.complete.zlib')).write_bytes(b'SYNTHETIC-UNCHANGED')
   ev={'complete_replays':3,'stale_replays':15,'invalid_replays':0,'results':[dict(requested_range={'start':d,'end':d},pit_completeness='COMPLETE',replay_integrity_checked=True) for d in w.DAYS]}
   class H(http.server.BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def do_GET(self):
     r={'code_root':str(engine),'decision_authority':'LIVE_DECISION_V1','database':str(app/'stock_recommendation_engine.sqlite3')} if self.path=='/api/health' else (ev if self.path.endswith('historical-evidence') else {})
     self.send_response(200);self.end_headers();self.wfile.write(json.dumps(r).encode())
    def do_POST(self):raise AssertionError('No POST authorized')
   server=http.server.ThreadingHTTPServer(('127.0.0.1',0),H);threading.Thread(target=server.serve_forever,daemon=True).start();(app/'runtime-port.txt').write_text(str(server.server_port))
   before={p.name:w.sha(p) for p in app.glob('*.sqlite3')};oldbase=w.BASE;oldargs=sys.argv[:];oldenv=os.environ.get('LOCALAPPDATA');oldruntime=w.runtime_inventory
   try:
    w.BASE=package;os.environ['LOCALAPPDATA']=str(root/'local');w.runtime_inventory=lambda *a:{};sys.argv=['accept','--stage','Initial','--run',str(root/'run'),'--pid','synthetic-process']
    with contextlib.redirect_stdout(io.StringIO()):w.main()
    report=json.loads((root/'run/GATE_C_MACHINE_RESULTS.json').read_text());self.assertEqual(report['checks']['restore_accounting']['status'],'PASS');self.assertEqual(report['checks']['verified_row_preservation']['status'],'FAIL');self.assertEqual(report['gate_c'],'FAIL');self.assertEqual({p.name:w.sha(p) for p in app.glob('*.sqlite3')},before)
   finally:
    w.BASE=oldbase;w.runtime_inventory=oldruntime;sys.argv=oldargs
    if oldenv is None:os.environ.pop('LOCALAPPDATA',None)
    else:os.environ['LOCALAPPDATA']=oldenv
    server.shutdown();server.server_close()
if __name__=='__main__':unittest.main(verbosity=2)
