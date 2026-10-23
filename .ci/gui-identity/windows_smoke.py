from pathlib import Path
import tempfile,sys,os,json,hashlib,zlib,zipfile,threading,subprocess,http.server,importlib.util
B=Path(__file__).resolve().parent;spec=importlib.util.spec_from_file_location('probe',B/'inspect_live.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
T=Path(tempfile.mkdtemp(prefix='SRE GUI identity safe '));app=T/'local/StockRecommendationEngine';engine=app/'native-engine-0.14.13';folder=app/'historical_replay_checkpoints_v2';folder.mkdir(parents=True);(engine/'modern_ui').mkdir(parents=True);(engine/'modern_ui/api.py').write_text('synthetic source unchanged');(engine/'data').mkdir();(engine/'data/history.csv').write_text('old')
(app/'stock_recommendation_engine.sqlite3').write_bytes(b'PRIVATE_SYNTHETIC_DATABASE_NEVER_OPENED')
recovery=T/'recovery';recovery.mkdir();out=T/'output';old=[]
def result(day,source='old-source',market='old-market',runtime='worker'):
 c={'schema':'synthetic-test-only','runtime':{'python':runtime},'sessions':[day],'config':{'period':'CUSTOM','start':day,'end':day,'benchmark':'NIFTY 50','starting_capital':100000,'slippage_bps':10,'transaction_cost_bps':5},'source':source,'market':market}
 r={'requested_range':{'start':day,'end':day},'requested_period':'CUSTOM','replay_fundamental_source_fingerprint':source,'replay_market_content_signature':market,'replay_context_signature':'same-context','pit_completeness':'COMPLETE','replay_id':'synthetic-'+day};key=m.digest(c);r['v10_acceptance']={'key':key,'contract':c,'payload_sha256':m.digest(r)};return r
receipt={'destination':str(folder),'plan':[]}
for day in m.DAYS:
 r=result(day);(recovery/(day+'-recovery.json')).write_text(json.dumps(r));key=r['v10_acceptance']['key'];p=folder/(key+'.complete.zlib');p.write_bytes(zlib.compress(json.dumps({'schema':'SRE_REPLAY_CHECKPOINT_V2','key':key,'value':r}).encode()));receipt['plan'].append({'name':p.name,'sha256':m.sha(p)})
(recovery/'publication.json').write_text(json.dumps(receipt));guard={'modern_ui/api.py':m.sha(engine/'modern_ui/api.py')};(recovery/'source-guard.json').write_text(json.dumps(guard))
for i in range(12):
 p=folder/(f'{i:064x}'+'.complete.zlib');p.write_bytes(zlib.compress(json.dumps({'value':{}}).encode()));old.append({'path':'application-state/historical_replay_checkpoints_v2/'+p.name,'source_sha256':m.sha(p)})
manifest={'source_engine':str(engine),'source_files':old+[{'path':'engine/data/history.csv','source_sha256':m.sha(engine/'data/history.csv')}]}
with zipfile.ZipFile(recovery/'SRE-GateBC-ReadOnly-synthetic.zip','w') as z:z.writestr('snapshot-manifest.json',json.dumps(manifest))
(engine/'data/history.csv').write_text('new verified data difference')
r=result(m.DAYS[0],'new-source','new-market','GUI-runtime');key=r['v10_acceptance']['key'];anchor=folder/(key+'.complete.zlib');anchor.write_bytes(zlib.compress(json.dumps({'schema':'SRE_REPLAY_CHECKPOINT_V2','key':key,'value':r}).encode()))
evidence={'complete_replays':1,'stale_replays':15,'partial_replays':0,'invalid_replays':0,'results':[{'requested_range':r['requested_range']}]};routes={'/api/health':{'database':str(app/'stock_recommendation_engine.sqlite3'),'code_root':str(engine),'repo_root':str(engine)},'/api/data-source':{'active':{'path':str(engine)}},'/api/validation/historical-evidence':evidence,'/api/validation/gate-a-diagnostics':{'examples':{'CURRENT_INTEGRITY_CHECKED':[anchor.name]}}};calls=[]
class Handler(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  calls.append(('GET',self.path));data=json.dumps(routes[self.path]).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def do_POST(self):raise AssertionError('POST prohibited')
 def log_message(self,*a):pass
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();(app/'runtime-port.txt').write_text(str(server.server_port))
before={p:m.sha(p) for p in app.rglob('*') if p.is_file()};env=dict(os.environ,LOCALAPPDATA=str(T/'local'));script=B/'INSPECT_SRE_GUI_REPLAYS.ps1'
try:
 q=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-RecoveryDirectory',str(recovery),'-OutputDirectory',str(out)],env=env,text=True,capture_output=True,timeout=90)
 assert q.returncode==0,q.stdout+q.stderr
finally:server.shutdown();server.server_close()
runs=[p for p in out.iterdir() if p.is_dir()];assert len(runs)==1;j=json.loads((runs[0]/'COMPARISON.json').read_text());assert j['publication_destination_matches_gui'];assert j['source_guard_all_same'];assert all(j['original_capture_records_preserved'].values()) and len(j['original_capture_records_preserved'])==12;assert len(j['changed_disk_input_files'])==1;assert j['current_runtime_from_gui_accepted_attestation']['python']=='GUI-runtime';assert all(r['classification']=='PRESENT_BUT_STALE_GLOBAL_IDENTITY_MISMATCH' for r in j['comparisons']);assert j['endpoint_stable_during_capture'] and j['replay_files_stable_during_capture'];assert all(m.sha(p)==h for p,h in before.items());assert len(calls)==5 and all(x[0]=='GET' for x in calls);assert list(out.glob('*.zip'))
print('PASS native Windows GET-only GUI probe: all3 stale present; GUI anchor/runtime comparison; input hash delta;12 originals unchanged; no database access/replay/POST; private report ZIP.')
