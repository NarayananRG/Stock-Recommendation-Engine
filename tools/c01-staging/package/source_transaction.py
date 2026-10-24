"""C01 source transaction rehearsal. Isolated workspaces only; no live installer."""
from pathlib import Path
import hashlib,json,os,stat,uuid
class Stop(RuntimeError):pass
def require(ok,msg):
 if not ok:raise Stop(msg)
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb')as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def write(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.new-'+uuid.uuid4().hex)
 with tmp.open('xb')as f:f.write((json.dumps(v,indent=2)+'\n').encode());f.flush();os.fsync(f.fileno())
 os.replace(tmp,p)
def check_path(p):
 p=Path(p).absolute()
 for q in [p,*p.parents]:
  if q.exists() or q.is_symlink():
   s=q.lstat();require(not q.is_symlink()and not(getattr(s,'st_file_attributes',0)&0x400),'REPARSE_OR_SYMLINK:'+str(q))
   if q.is_file():require(s.st_nlink==1,'HARDLINK:'+str(q))
 return p.resolve()
def child(root,name):
 require(isinstance(name,str)and name and not name.startswith(('/','\\'))and ':'not in name,'UNSAFE_RELATIVE_PATH')
 parts=name.replace('\\','/').split('/');require(all(x not in ('','..','.')for x in parts),'UNSAFE_RELATIVE_PATH')
 r=check_path(root);p=check_path(r.joinpath(*parts));require(p.is_relative_to(r),'PATH_ESCAPE');return p
def files(root):
 root=check_path(root);out={}
 for p in sorted(root.rglob('*')):
  check_path(p)
  if p.is_file():out[p.relative_to(root).as_posix()]=sha(p)
 return out
def verify(root,expected,exact=False):
 for n,h in expected.items():
  p=child(root,n);require(p.is_file()and sha(p)==h,'HASH_MISMATCH:'+n)
 if exact:require(files(root)==expected,'EXTRA_OR_MISSING_FILES')
def workspace(root):
 root=check_path(root);marker=root/'ISOLATED_WORKSPACE.json'
 require(marker.is_file(),'ISOLATED_MARKER_REQUIRED');v=json.loads(marker.read_text());require(v.get('root')==str(root)and v.get('purpose')=='C01_STAGING_ONLY','WORKSPACE_IDENTITY_MISMATCH')
 return root
def engine(root):return workspace(root)/'engine'
def atomic_bytes(p,b):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name(p.name+'.stage-'+uuid.uuid4().hex)
 with t.open('xb')as f:f.write(b);f.flush();os.fsync(f.fileno())
 os.replace(t,p)
def original(root,guard,manifest):
 e=engine(root);verify(e,guard)
 for f in manifest['files']:
  p=child(e,f['path']);h=f['before_sha256'];require((not p.exists())if h is None else(p.is_file()and sha(p)==h),'ORIGINAL_SOURCE_DRIFT:'+f['path'])
def apply(root,candidate,guard,manifest,fault_after=None):
 root=workspace(root);e=engine(root);receipt=root/'SOURCE_RECEIPT.json'
 require(not receipt.exists(),'RECEIPT_EXISTS_REFUSE_PARTIAL_OR_REPEAT');original(root,guard,manifest)
 entries=manifest['files'];require(len(entries)==6 and sum(x['before_sha256']is None for x in entries)==1,'EXPECTED_SIX_FILES')
 require(len({x['path']for x in entries})==6,'DUPLICATE_TARGET')
 for x in entries:
  p=child(candidate,x['path']);require(p.is_file()and sha(p)==x['after_sha256'],'CANDIDATE_HASH_MISMATCH:'+x['path']);compile(p.read_bytes(),x['path'],'exec')
 old=root/'source-backup';old.mkdir(exist_ok=False)
 for x in entries:
  if x['before_sha256']is not None:atomic_bytes(child(old,x['path']),child(e,x['path']).read_bytes())
 v={'schema':'SRE_C01_ISOLATED_SOURCE_RECEIPT_V1','transaction':uuid.uuid4().hex,'engine':str(e.resolve()),'guard_digest':digest(guard),'manifest_digest':digest(manifest),'state':'PREPARED','entries':entries}
 write(receipt,v)
 for i,x in enumerate(entries,1):
  atomic_bytes(child(e,x['path']),child(candidate,x['path']).read_bytes())
  if fault_after==i:os._exit(79)
 verify(e,{x['path']:x['after_sha256']for x in entries});v['state']='COMMITTED';write(receipt,v);return v
def rollback(root,guard,manifest,recovery=False):
 root=workspace(root);e=engine(root);receipt=root/'SOURCE_RECEIPT.json';require(receipt.is_file(),'RECEIPT_MISSING');v=json.loads(receipt.read_text())
 require(v.get('engine')==str(e.resolve())and v.get('guard_digest')==digest(guard)and v.get('manifest_digest')==digest(manifest)and v.get('entries')==manifest['files'],'RECEIPT_IDENTITY_MISMATCH')
 require(v['state']in (('PREPARED','ROLLING_BACK')if recovery else('COMMITTED',)),'RECEIPT_STATE_REFUSED')
 # Check all dependencies before the first restoration. Never force third-party edits.
 for x in v['entries']:
  p=child(e,x['path']);now=sha(p)if p.exists()else None
  allowed=(x['before_sha256'],x['after_sha256'])if recovery else(x['after_sha256'],)
  require(now in allowed,'ROLLBACK_TARGET_DRIFT:'+x['path'])
  if x['before_sha256']is not None:require(sha(child(root/'source-backup',x['path']))==x['before_sha256'],'BACKUP_HASH_MISMATCH')
 v['state']='ROLLING_BACK';write(receipt,v)
 for x in v['entries']:
  p=child(e,x['path'])
  if x['before_sha256']is None:
   if p.exists():require(sha(p)==x['after_sha256'],'NEW_MODULE_DRIFT');p.unlink()
  else:atomic_bytes(p,child(root/'source-backup',x['path']).read_bytes())
 original(root,guard,manifest);v['state']='RECOVERED'if recovery else'ROLLED_BACK';write(receipt,v);return v
