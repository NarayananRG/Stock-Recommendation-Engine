from pathlib import Path
import sys,json,zlib,sqlite3,hashlib
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import replay_capture as m

def fixture(tmp_path,proof=True):
 d=tmp_path/'application-state/historical_replay_checkpoints_v2';d.mkdir(parents=True)
 c={'sessions':['2026-10-15'],'config':{'period':'CUSTOM'},'runtime':{'python':'3.14.2'}};r={'pit_completeness':'COMPLETE','requested_period':'CUSTOM','requested_range':{'start':'2026-10-15','end':'2026-10-15'},'sessions_replayed':1,'coverage':[{'date':'2026-10-15'}],'metrics':{'closed_trades':0}}
 key=m.digest(c)
 if proof:r['v10_acceptance']={'key':key,'contract':c,'payload_sha256':m.digest(r)}
 p=d/(key+'.complete.zlib');p.write_bytes(zlib.compress(json.dumps({'schema':'SRE_REPLAY_CHECKPOINT_V2','key':key,'value':r}).encode()));return p

def test_inventory_never_promotes_complete_flag(tmp_path):
 fixture(tmp_path,False);r=m.inspect_replays(tmp_path)
 assert r['complete_files']==1 and r['attested_self_integrity_matches']==0
 assert r['distinct_historically_complete_single_sessions']==['2026-10-15']
 assert r['records'][0]['current_validation_status'].startswith('NOT_REVALIDATED')
def test_proof_and_wrapper_checked(tmp_path):
 p=fixture(tmp_path);before=p.read_bytes();r=m.inspect_replays(tmp_path);assert r['records'][0]['wrapper_valid']and r['records'][0]['self_integrity_match'];assert p.read_bytes()==before
 obj=m.unpack(p);obj['value']['metrics']['closed_trades']=50;p.write_bytes(zlib.compress(json.dumps(obj).encode()));assert not m.inspect_replays(tmp_path)['records'][0]['self_integrity_match']
def test_corrupt_preserved(tmp_path):
 p=fixture(tmp_path);p.write_bytes(b'corrupt');r=m.inspect_replays(tmp_path);assert len(r['errors'])==1 and p.read_bytes()==b'corrupt'
def test_trailing_zlib_rejected(tmp_path):
 p=fixture(tmp_path);p.write_bytes(p.read_bytes()+b'extra')
 with pytest.raises(ValueError):m.unpack(p)
def test_bounded_decompression(tmp_path,monkeypatch):
 p=tmp_path/'x';p.write_bytes(zlib.compress(b'x'*100));monkeypatch.setattr(m,'MAX_JSON',10)
 with pytest.raises(ValueError):m.unpack(p)
def test_unrecognized_source_prevents_import(tmp_path):
 (tmp_path/'stock_app').mkdir();(tmp_path/'modern_ui').mkdir();(tmp_path/'stock_app/unknown.py').write_text('raise RuntimeError("DO NOT IMPORT")')
 assert m.native_fingerprints(tmp_path,{'files':{},'guard_files':{}})['status']=='BLOCKED_UNRECOGNIZED_SOURCE'
def test_full_copy_audit_readonly(tmp_path):
 p=fixture(tmp_path);original=tmp_path/'engine';original.mkdir();(original/'runtime.dll').write_bytes(b'binary');db=tmp_path/'application-state/main.sqlite3'
 with sqlite3.connect(db)as c:c.execute('create table holdings(id text)');c.execute("insert into holdings values('unchanged')")
 before={x:hashlib.sha256(x.read_bytes()).hexdigest()for x in [p,db,original/'runtime.dll']}
 r=m.audit_capture(tmp_path,original,{'files':{},'guard_files':{}},compute_native=False)
 assert r['no_replay_executed']and r['no_network']and r['original_databases_opened_by_sqlite']is False
 assert all(hashlib.sha256(x.read_bytes()).hexdigest()==h for x,h in before.items())
 assert not list((tmp_path/'gatebc-evidence').glob('*.dll'))
