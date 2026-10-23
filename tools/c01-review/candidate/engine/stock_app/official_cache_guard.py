"""C01: serialize official cache readers/publications and recover interrupted batches.

Only cache-local market files are managed. No database, portfolio, strategy or
stored replay is opened. Archives are retained; raw multi-file filesystem access
outside these guards is not an atomic snapshot API.
"""
from __future__ import annotations
from contextlib import contextmanager, ExitStack
from functools import wraps
from hashlib import sha256
from pathlib import Path
import json, os, threading, time
from uuid import uuid4

_PENDING='.sre_official_pending.json'
_ARCHIVE='.sre_official_transactions'
_LOCAL=threading.local()
_MUTEX={}
_MUTEX_GUARD=threading.Lock()

class CommittedPublicationNeedsRecovery(RuntimeError):
 def __init__(self,transaction):
  self.transaction=transaction
  super().__init__('C01_COMMITTED_PUBLICATION_REQUIRES_FINALIZATION:'+transaction)

def file_hash(p):return sha256(Path(p).read_bytes()).hexdigest()
def _durable_write(p,data):
 p=Path(p);temp=p.with_name('.'+p.name+'.tmp-'+uuid4().hex)
 try:
  with temp.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(temp,p)
  if os.name!='nt':
   fd=os.open(str(p.parent),os.O_RDONLY)
   try:os.fsync(fd)
   finally:os.close(fd)
 finally:
  if temp.exists():temp.unlink()
def _json_write(p,v):_durable_write(p,(json.dumps(v,sort_keys=True,indent=2)+'\n').encode())
def _safe_name(name):
 if not isinstance(name,str) or not name or Path(name).name!=name or '/' in name or '\\' in name or name in ('.','..'):raise RuntimeError('C01_INVALID_TRANSACTION_PATH')
 return name

def _recover_locked(root):
 pending=root/_PENDING
 if not pending.exists():return
 obj=json.loads(pending.read_text(encoding='utf-8'));token=obj.get('transaction')
 if not isinstance(token,str) or len(token)!=32 or any(c not in '0123456789abcdef' for c in token):raise RuntimeError('C01_INVALID_TRANSACTION_ID')
 archive=root/_ARCHIVE/token
 journal_bytes=(archive/'journal.json').read_bytes()
 if sha256(journal_bytes).hexdigest()!=obj.get('journal_sha256'):raise RuntimeError('C01_TRANSACTION_JOURNAL_CHANGED')
 journal=json.loads(journal_bytes)
 if journal.get('transaction')!=token:raise RuntimeError('C01_TRANSACTION_ID_MISMATCH')
 state=json.loads((archive/'state.json').read_text())['state']
 entries=journal['entries']
 for name,h in journal.get('source_artifacts',{}).items():
  if file_hash(archive/'sources'/_safe_name(name))!=h:raise RuntimeError('C01_SOURCE_ARCHIVE_CHANGED')
 if state=='COMMITTED':
  for e in entries:
   target=root/_safe_name(e['file'])
   if not target.is_file() or file_hash(target)!=e['new_sha256']:raise RuntimeError('C01_COMMITTED_CONTENT_CHANGED')
 elif state in ('PREPARED','ROLLED_BACK'):
  # Refuse to overwrite unexpected third-party content or a corrupt backup.
  for e in entries:
   name=_safe_name(e['file']);target=root/name
   current=file_hash(target) if target.exists() else None
   if current not in (e['old_sha256'],e['new_sha256']):raise RuntimeError('C01_RECOVERY_TARGET_CHANGED:'+name)
   if e['old_sha256'] is not None and file_hash(archive/'old'/name)!=e['old_sha256']:raise RuntimeError('C01_RECOVERY_BACKUP_CHANGED:'+name)
  for e in entries:
   target=root/e['file']
   if e['old_sha256'] is None:
    if target.exists():target.unlink()
   else:_durable_write(target,(archive/'old'/e['file']).read_bytes())
  _json_write(archive/'state.json',{'state':'ROLLED_BACK'})
 else:raise RuntimeError('C01_UNRECOGNIZED_TRANSACTION_STATE')
 pending.unlink()

def _root_key(root):return str(Path(root).resolve())
@contextmanager
def cache_guard(root,timeout=30.0):
 root=Path(root).resolve()
 if not root.is_dir():yield;return
 key=_root_key(root)
 with _MUTEX_GUARD:mutex=_MUTEX.setdefault(key,threading.RLock())
 if not mutex.acquire(timeout=timeout):raise RuntimeError('C01_CACHE_BUSY')
 depths=getattr(_LOCAL,'depths',None)
 if depths is None:depths={};_LOCAL.depths=depths
 if depths.get(key,0):
  depths[key]+=1
  try:yield
  finally:depths[key]-=1;mutex.release()
  return
 f=None;locked=False
 try:
  f=(root/'.sre_official_refresh.lock').open('a+b')
  if f.seek(0,os.SEEK_END)==0:f.write(b'0');f.flush()
  deadline=time.monotonic()+timeout
  while True:
   try:
    f.seek(0)
    if os.name=='nt':
     import msvcrt
     msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
    else:
     import fcntl
     fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    locked=True;break
   except OSError:
    if time.monotonic()>=deadline:raise RuntimeError('C01_CACHE_BUSY')
    time.sleep(.02)
  depths[key]=1
  _recover_locked(root)
  yield
 finally:
  depths.pop(key,None)
  if f is not None:
   if locked:
    f.seek(0)
    if os.name=='nt':
     import msvcrt
     msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
    else:
     import fcntl
     fcntl.flock(f.fileno(),fcntl.LOCK_UN)
   f.close()
  mutex.release()

@contextmanager
def guard_roots(roots):
 with ExitStack() as stack:
  for root in sorted({Path(p).resolve() for p in roots if Path(p).is_dir()},key=str):stack.enter_context(cache_guard(root))
  yield

def guarded(get_roots,invalidate=False):
 """Wrap existing read entry points without changing their numerical algorithms."""
 def decorate(fn):
  @wraps(fn)
  def wrapped(*args,**kwargs):
   roots=list(get_roots(*args,**kwargs))
   with guard_roots(roots):
    if invalidate:
     obj=args[0];generation=tuple((str(Path(p).resolve()),file_hash(Path(p)/'.sre_official_refresh_manifest.json') if (Path(p)/'.sre_official_refresh_manifest.json').exists() else None) for p in roots)
     if getattr(obj,'_c01_generation',None)!=generation:
      for name in ('_history_cache','_cache','cache','_data_cache'):
       value=getattr(obj,name,None)
       if isinstance(value,dict):value.clear()
      obj._c01_generation=generation
    return fn(*args,**kwargs)
  return wrapped
 return decorate

def publish_batch(root,planned,validate,source_artifacts=None):
 """Write-ahead journal; guarded readers recover or finalize before any read.

 Per-file replacement is atomic. Multi-file isolation is enforced by cache_guard,
 not claimed as a filesystem primitive. Backups/receipts survive both outcomes.
 """
 root=Path(root).resolve()
 with cache_guard(root):
  token=uuid4().hex;archive=root/_ARCHIVE/token
  (archive/'old').mkdir(parents=True);(archive/'new').mkdir();(archive/'sources').mkdir()
  artifact_hashes={}
  for name,data in (source_artifacts or {}).items():
   _safe_name(name);_durable_write(archive/'sources'/name,data);artifact_hashes[name]=sha256(data).hexdigest()
  entries=[]
  for path,payload in planned:
   original=Path(path)
   if original.is_symlink():raise RuntimeError('C01_SYMLINK_PUBLICATION_TARGET')
   path=original.resolve()
   if path.parent!=root:raise RuntimeError('C01_INVALID_PUBLICATION_TARGET')
   name=_safe_name(path.name)
   if name in {e['file'] for e in entries}:raise RuntimeError('C01_DUPLICATE_PUBLICATION_TARGET')
   old=path.read_bytes() if path.exists() else None
   if old==payload:continue
   if old is not None:_durable_write(archive/'old'/name,old)
   _durable_write(archive/'new'/name,payload)
   validate(archive/'new'/name)
   entries.append({'file':name,'old_sha256':sha256(old).hexdigest() if old is not None else None,'new_sha256':sha256(payload).hexdigest()})
  if not entries:return None
  journal={'schema':'SRE_OFFICIAL_C01_BATCH_V1','transaction':token,'entries':entries,'source_artifacts':artifact_hashes}
  _json_write(archive/'journal.json',journal);_json_write(archive/'state.json',{'state':'PREPARED'})
  _json_write(root/_PENDING,{'transaction':token,'journal_sha256':file_hash(archive/'journal.json')})
  try:
   for e in entries:_durable_write(root/e['file'],(archive/'new'/e['file']).read_bytes())
   for e in entries:
    if file_hash(root/e['file'])!=e['new_sha256']:raise RuntimeError('C01_POST_WRITE_HASH_MISMATCH')
    validate(root/e['file'])
   _json_write(archive/'state.json',{'state':'COMMITTED'})
   (root/_PENDING).unlink()
   return token
  except Exception as exc:
   if json.loads((archive/'state.json').read_text()).get('state')=='COMMITTED':
    raise CommittedPublicationNeedsRecovery(token) from exc
   _recover_locked(root)
   raise
