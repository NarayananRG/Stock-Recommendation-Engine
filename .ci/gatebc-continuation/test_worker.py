import importlib.util,sys,json
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('continuation_worker',Path(__file__).with_name('worker.py'));w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
NAME='a'*64+'.complete.zlib'
def test_exclusive_publication_and_safe_rollback(tmp_path):
 src=tmp_path/'src';src.mkdir();(src/NAME).write_bytes(b'new');dest=tmp_path/'dest';receipt=tmp_path/'receipt.json'
 r=w.publish(src,dest,receipt,[NAME]);assert r['status']=='PUBLISHED' and (dest/NAME).read_bytes()==b'new'
 w.rollback(receipt,dest);assert not (dest/NAME).exists() and (tmp_path/'rolled-back-results'/NAME).read_bytes()==b'new'
def test_existing_identical_file_is_never_rolled_back(tmp_path):
 src=tmp_path/'src';src.mkdir();(src/NAME).write_bytes(b'old');dest=tmp_path/'dest';dest.mkdir();(dest/NAME).write_bytes(b'old');r=tmp_path/'r.json'
 w.publish(src,dest,r,[NAME]);w.rollback(r,dest);assert (dest/NAME).read_bytes()==b'old'
def test_collision_refuses_without_mutation(tmp_path):
 src=tmp_path/'src';src.mkdir();(src/NAME).write_bytes(b'new');dest=tmp_path/'dest';dest.mkdir();(dest/NAME).write_bytes(b'old')
 with pytest.raises(RuntimeError,match='COLLISION'):w.publish(src,dest,tmp_path/'r.json',[NAME])
 assert (dest/NAME).read_bytes()==b'old'
def test_changed_result_refuses_rollback(tmp_path):
 src=tmp_path/'src';src.mkdir();(src/NAME).write_bytes(b'new');dest=tmp_path/'dest';r=tmp_path/'r.json';w.publish(src,dest,r,[NAME]);(dest/NAME).write_bytes(b'changed')
 with pytest.raises(RuntimeError,match='CONTENT_CHANGED'):w.rollback(r,dest)
def test_wrong_destination_refused(tmp_path):
 src=tmp_path/'src';src.mkdir();(src/NAME).write_bytes(b'new');r=tmp_path/'r.json';w.publish(src,tmp_path/'dest',r,[NAME])
 with pytest.raises(RuntimeError,match='DESTINATION'):w.rollback(r,tmp_path/'other')
@pytest.mark.parametrize('name',['../x.complete.zlib','z'*64+'.complete.zlib','a.complete.zlib','a'*64+'.json'])
def test_unsafe_names_refused(name):
 with pytest.raises(ValueError):w.safe_name(name)
def test_source_version_guard(tmp_path):
 p=tmp_path/'a.py';p.write_text('before');m={'a.py':w.sha(p)};w.source_guard(tmp_path,m);p.write_text('after')
 with pytest.raises(RuntimeError,match='VERSION_MISMATCH'):w.source_guard(tmp_path,m)
def test_atomic_failure_leaves_no_final_file(tmp_path,monkeypatch):
 src=tmp_path/'src';src.mkdir();(src/NAME).write_bytes(b'new');dest=tmp_path/'dest'
 def fail(*a):raise OSError('synthetic link failure')
 monkeypatch.setattr(w.os,'link',fail)
 with pytest.raises(OSError):w.publish(src,dest,tmp_path/'r.json',[NAME])
 assert not (dest/NAME).exists();assert json.loads((tmp_path/'r.json').read_text())['status']=='PLANNED'
