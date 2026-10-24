"""Guarded six-file C01 deployment. Invoked locally by the operator, never remotely."""
from pathlib import Path
import argparse, contextlib, ctypes, datetime, hashlib, json, os, shutil, sqlite3, struct, subprocess, sys, uuid

class Stop(RuntimeError): pass
def require(ok, why):
    if not ok: raise Stop(why)
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def digest(v): return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def load(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def safe(p):
    p=Path(p).absolute()
    require(not str(p).startswith('\\\\'), 'NETWORK_PATH_REFUSED')
    for q in (p,*p.parents):
        if q.exists() or q.is_symlink():
            s=q.lstat()
            require(not q.is_symlink() and not (getattr(s,'st_file_attributes',0)&0x400), 'REPARSE_PATH:'+str(q))
            if q.is_file(): require(s.st_nlink==1,'HARDLINK:'+str(q))
    return p.resolve()
def child(root,n):
    require(isinstance(n,str) and n and ':' not in n and '\\' not in n and not n.startswith('/') and all(x not in ('','.','..') for x in n.split('/')),'BAD_RELATIVE_PATH')
    root=safe(root); p=safe(root/n); require(p.is_relative_to(root),'PATH_ESCAPE'); return p

def atomic(p,b):
    p=safe(p); p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_name(p.name+'.c01-'+uuid.uuid4().hex)
    try:
        with t.open('xb') as f: f.write(b); f.flush(); os.fsync(f.fileno())
        os.replace(t,p)
    finally:
        if t.exists(): t.unlink()
def write(p,v): atomic(p,(json.dumps(v,indent=2)+'\n').encode())
def verify(root,values):
    for n,h in values.items():
        p=child(root,n); require((not p.exists()) if h is None else (p.is_file() and sha(p)==h),'SOURCE_HASH_MISMATCH:'+n)
def candidate_checks(package,guard,manifest):
    rows=manifest['files']; require(len(guard)==46 and len(rows)==6 and len({r['path'] for r in rows})==6 and sum(r['before_sha256'] is None for r in rows)==1,'MANIFEST_SHAPE')
    for r in rows:
        require(guard.get(r['path'])==r['before_sha256'],'BASELINE_MANIFEST_DISAGREEMENT')
        p=child(package/'candidate',r['path']); require(sha(p)==r['after_sha256'],'CANDIDATE_HASH:'+r['path']); compile(p.read_bytes(),r['path'],'exec')
    require(guard['stock_app/live_decision_v1.py']=='ae1814b9709b064f2ebffbe7a4daa9de589e74295cd894e5013a4043f79e30b8','FROZEN_CONTRACT')
def expected(guard,manifest,after):
    out=dict(guard)
    for r in manifest['files']: out[r['path']]=r['after_sha256'] if after else r['before_sha256']
    return out

def inventory(root,excluded=()):
    root=safe(root); out={}; excluded=set(excluded)
    for base,dirs,names in os.walk(root,followlinks=False):
        for n in dirs: safe(Path(base)/n)
        for n in names:
            p=safe(Path(base)/n); rel=p.relative_to(root).as_posix()
            if rel not in excluded: out[rel]={'sha256':sha(p),'size':p.stat().st_size}
    return out

def sql_snapshot(copyroot, data, inv):
    """Open ONLY byte-copied SQLite files; never connect to the installed database."""
    result={}; copyroot.mkdir(parents=True,exist_ok=True)
    for rel,meta in inv.items():
        p=child(data,rel)
        with p.open('rb') as f: header=f.read(16)
        if header!=b'SQLite format 3\x00': continue
        dest=child(copyroot,rel); dest.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(p,dest)
        for suffix in ('-wal','-shm','-journal'):
            side=Path(str(p)+suffix)
            if side.exists(): shutil.copyfile(side,Path(str(dest)+suffix))
        require(sha(dest)==meta['sha256'],'DATABASE_COPY_CHANGED')
        c=sqlite3.connect(dest)
        try:
            require(c.execute('PRAGMA quick_check').fetchall()==[('ok',)],'SQLITE_INTEGRITY:'+rel)
            schema=c.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
            tables={}
            for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
                q='"'+name.replace('"','""')+'"'
                encoded=[]
                for row in c.execute('SELECT * FROM '+q):
                    encoded.append(json.dumps([(type(x).__name__,x.hex() if isinstance(x,bytes) else x) for x in row],ensure_ascii=True,separators=(',',':')))
                encoded.sort(); tables[name]={'rows':len(encoded),'sha256':hashlib.sha256('\n'.join(encoded).encode()).hexdigest()}
            result[rel]={'quick_check':'ok','schema_sha256':digest(schema),'all_tables':tables}
        finally: c.close()
    require(result,'NO_SQLITE_DATABASE_FOUND')
    return result

def required_space(data,inv,engine):
    source=0; databases=0
    for n,m in inv.items():
        if n.startswith((engine.name+'/stock_app/',engine.name+'/modern_ui/')): source+=m['size']
        path=child(data,n)
        with path.open('rb') as f: header=f.read(16)
        if header==b'SQLite format 3\x00' or n.endswith(('-wal','-shm','-journal')): databases+=m['size']
    return 128*1024*1024+source*4+databases*3

def begin(engine,area,package,guard,manifest,protected):
    require(not (area/'RECEIPT.json').exists(),'EXISTING_RECEIPT_USE_ROLLBACK')
    verify(engine,expected(guard,manifest,False)); candidate_checks(package,guard,manifest)
    area.mkdir(parents=True,exist_ok=True)
    for r in manifest['files']:
        if r['before_sha256'] is not None:
            p=child(area/'originals',r['path']); atomic(p,child(engine,r['path']).read_bytes()); require(sha(p)==r['before_sha256'],'BACKUP_HASH')
    receipt={'schema':'SRE_C01_DIRECT_RECEIPT_V1','transaction':uuid.uuid4().hex,'engine':str(engine),'guard_digest':digest(guard),'manifest_digest':digest(manifest),'entries':manifest['files'],'state':'PREPARED','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'protected_before_sha256':digest(protected),'python':sys.version,'python_executable':sys.executable,'python_sha256':sha(sys.executable)}
    write(area/'PROTECTED_BEFORE.json',protected); write(area/'RECEIPT.json',receipt); return receipt

def source_temp(p,transaction,phase):
    require(len(transaction)==32 and all(c in '0123456789abcdef' for c in transaction),'BAD_TRANSACTION_ID')
    return safe(p.with_name(p.name+'.c01-'+transaction+'-'+phase))
def atomic_source(p,b,transaction,phase):
    t=source_temp(p,transaction,phase)
    if t.exists():
        require(t.stat().st_size<=len(b) and b.startswith(t.read_bytes()),'OWNED_TEMP_DRIFT'); t.unlink()
    with t.open('xb') as f: f.write(b); f.flush(); os.fsync(f.fileno())
    os.replace(t,p)
def publish(engine,area,package,manifest,fault=None,check=lambda:None):
    transaction=load(area/'RECEIPT.json')['transaction']
    for i,r in enumerate(manifest['files'],1):
        check(); verify(engine,{r['path']:r['before_sha256']}); atomic_source(child(engine,r['path']),child(package/'candidate',r['path']).read_bytes(),transaction,'new')
        if fault==i: os._exit(79)

def restore(engine,area,guard,manifest,check=lambda:None,package=None):
    rp=area/'RECEIPT.json'; r=load(rp)
    require(r.get('schema')=='SRE_C01_DIRECT_RECEIPT_V1' and r.get('engine')==str(engine) and r.get('entries')==manifest['files'] and r.get('guard_digest')==digest(guard) and r.get('manifest_digest')==digest(manifest),'RECEIPT_IDENTITY')
    require(r['state'] in ('PREPARED','COMMITTED','ROLLING_BACK'),'RECEIPT_STATE')
    # Preflight EVERY target, backup and protected authority module before ANY restoration.
    changed={v['path'] for v in manifest['files']}
    verify(engine,{n:h for n,h in guard.items() if n not in changed})
    for v in manifest['files']:
        p=child(engine,v['path']); now=sha(p) if p.exists() else None
        allowed=(v['after_sha256'],) if r['state']=='COMMITTED' else (v['before_sha256'],v['after_sha256'])
        require(now in allowed,'ROLLBACK_TARGET_DRIFT:'+v['path'])
        if v['before_sha256'] is not None: require(sha(child(area/'originals',v['path']))==v['before_sha256'],'BACKUP_HASH:'+v['path'])
    # Only receipt-bound, prefix-verified temporary source files may be removed after interruption.
    temps=[]
    for v in manifest['files']:
        p=child(engine,v['path'])
        for phase in ('new','old'):
            t=source_temp(p,r['transaction'],phase)
            if t.exists():
                origin=child((package or Path(__file__).parent)/'candidate',v['path']) if phase=='new' else child(area/'originals',v['path'])
                require(origin.is_file(),'TEMP_WITHOUT_ORIGIN')
                b=origin.read_bytes(); require(t.stat().st_size<=len(b) and b.startswith(t.read_bytes()),'OWNED_TEMP_DRIFT')
                temps.append(t)
    for t in temps: t.unlink()
    check(); r['state']='ROLLING_BACK'; write(rp,r)
    for v in manifest['files']:
        check(); p=child(engine,v['path'])
        if v['before_sha256'] is None:
            if p.exists(): require(sha(p)==v['after_sha256'],'NEW_GUARD_DRIFT'); p.unlink()
        else: atomic_source(p,child(area/'originals',v['path']).read_bytes(),r['transaction'],'old')
    verify(engine,expected(guard,manifest,False)); r['state']='ROLLED_BACK'; write(rp,r); return r

def closed(data):
    # Fail closed on missing CIM details. Conservatively require all other Python sessions closed.
    ps=r'''$ErrorActionPreference='Stop'; @(Get-CimInstance Win32_Process | Select-Object ProcessId,Name,ExecutablePath,CommandLine) | ConvertTo-Json -Depth 3 -Compress'''
    p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',ps],capture_output=True,text=True,timeout=40)
    require(p.returncode==0,'PROCESS_ENUMERATION_FAILED'); rows=json.loads(p.stdout or '[]'); rows=[rows] if isinstance(rows,dict) else rows
    hits=[]
    for r in rows:
        if r['ProcessId']==os.getpid(): continue
        name=(r.get('Name') or '').lower(); cmd=(r.get('CommandLine') or '').lower(); exe=(r.get('ExecutablePath') or '').lower()
        if name=='sre.exe' or 'python' in name or 'stockrecommendation' in name.replace('-','').replace('_','') or ('stock' in name and 'engine' in name) or str(data).lower() in exe or (str(data).lower() in cmd and name not in ('powershell.exe','pwsh.exe')) or ('stock_app' in cmd and name not in ('powershell.exe','pwsh.exe')):
            hits.append({'pid':r['ProcessId'],'name':r.get('Name')})
    require(not hits,'SRE_OR_OTHER_PYTHON_RUNNING:'+json.dumps(hits))

@contextlib.contextmanager
def protect_files(data,excluded):
    """Windows deny-write/delete handles on all protected files, held until operation ends."""
    require(os.name=='nt','WINDOWS_REQUIRED')
    data=safe(data)
    from ctypes import wintypes
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]; k.CreateFileW.restype=wintypes.HANDLE
    k.CloseHandle.argtypes=[wintypes.HANDLE]; k.CloseHandle.restype=wintypes.BOOL
    handles=[]
    try:
        # Files may be read by imports, but cannot be changed or deleted by any process.
        for base,dirs,names in os.walk(data,followlinks=False):
            for n in dirs: safe(Path(base)/n)
            for n in names:
                p=safe(Path(base)/n)
                if p.relative_to(data).as_posix() in excluded: continue
                h=k.CreateFileW(str(p),0x80000000,1,None,3,0x80,None)
                require(h not in (None,ctypes.c_void_p(-1).value),'PROTECTED_FILE_IN_USE:'+str(p)); handles.append(h)
        yield
    finally:
        for h in reversed(handles): k.CloseHandle(h)

def import_check(engine,area,package,deps=None):
    # Copy source only; imports execute with redirected paths, no factory/startup/database creation.
    root=area/('import-check-'+uuid.uuid4().hex); root.mkdir()
    for pkg in ('stock_app','modern_ui'):
        dest=root/pkg; dest.mkdir()
        for p in (engine/pkg).rglob('*.py'):
            safe(p); q=dest/p.relative_to(engine/pkg); q.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(p,q); compile(q.read_bytes(),str(q),'exec')
    cmd=[sys.executable,'-I','-B',str(package/'import_probe.py'),str(root),str(deps or engine/'.replay-v10-deps')]
    env=os.environ.copy()
    for key in list(env):
        if key.startswith(('STOCK_','SRE_')) or key in ('PYTHONPATH','PYTHONHOME','PYTHONSTARTUP'): env.pop(key,None)
    for key in ('LOCALAPPDATA','APPDATA','USERPROFILE','HOME','TEMP','TMP'): env[key]=str(root)
    for key in ('STOCK_APP_REPO_ROOT','STOCK_REAL_DATA_REPO_ROOT','STOCK_APP_DATA_DIR'): env[key]=str(root)
    p=subprocess.run(cmd,cwd=root,env=env,capture_output=True,text=True,timeout=150)
    atomic(root/'IMPORT_STDOUT.txt',p.stdout.encode()); atomic(root/'IMPORT_STDERR.txt',p.stderr.encode())
    require(p.returncode==0,'IMPORT_CHECK_FAILED:'+str(root)); return {'status':'PASS','isolated_source_copy':str(root),'stdout':p.stdout.strip()}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('action',choices=['apply','rollback']); ap.add_argument('--engine',required=True); ap.add_argument('--data',required=True); ap.add_argument('--receipt'); args=ap.parse_args()
    require(os.name=='nt' and struct.calcsize('P')==8 and sys.version_info[:3] in ((3,12,10),(3,14,3)),'TESTED_WINDOWS_X64_PYTHON_3_12_10_OR_3_14_3_REQUIRED')
    package=safe(Path(__file__).parent); engine=safe(args.engine); data=safe(args.data)
    require(engine.name=='native-engine-0.14.13' and engine.parent==data and data.name=='StockRecommendationEngine','INSTALLED_LAYOUT_MISMATCH')
    require(not package.is_relative_to(data),'EXTRACT_PACKAGE_OUTSIDE_APP_DATA')
    verify(package,load(package/'PACKAGE_HASHES.json'))
    guard=load(package/'BASELINE_SOURCE_GUARD.json'); manifest=load(package/'CHANGE_MANIFEST.json'); candidate_checks(package,guard,manifest)
    safe(sys.executable)
    closed(data)
    parent=safe(data.parent/'SRE-C01-Transactions'); parent.mkdir(exist_ok=True)
    # Cross-process OS lock; a hard exit releases it. The fixed file contains no financial data.
    lock=open(parent/'DEPLOYMENT.lock','a+b'); import msvcrt
    if lock.tell()==0: lock.write(b'0'); lock.flush()
    lock.seek(0); msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    try:
        incomplete=[]
        for p in parent.glob('C01-*/RECEIPT.json'):
            r=load(p)
            if r.get('engine')==str(engine) and r.get('state') in ('PREPARED','ROLLING_BACK'): incomplete.append(p)
        if args.action=='apply':
            require(not incomplete,'PARTIAL_INSTALLATION_RUN_ROLLBACK:'+str(incomplete))
            verify(engine,expected(guard,manifest,False))
            area=parent/('C01-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]); area.mkdir()
        else:
            require(args.receipt,'EXPLICIT_RECEIPT_REQUIRED'); rp=safe(args.receipt)
            require(rp.name=='RECEIPT.json' and rp.parent.parent==parent,'RECEIPT_LOCATION'); area=rp.parent
        excluded={engine.relative_to(data).as_posix()+'/'+r['path'] for r in manifest['files']}
        if args.action=='rollback':
            transaction=load(area/'RECEIPT.json')['transaction']
            for v in manifest['files']:
                for phase in ('new','old'):
                    t=source_temp(child(engine,v['path']),transaction,phase)
                    excluded.add(t.relative_to(data).as_posix())
        print('Transaction folder: '+str(area),flush=True)
        with protect_files(data,excluded):
            closed(data); before=inventory(data,excluded); write(area/('APPLY_BEFORE.json' if args.action=='apply' else 'ROLLBACK_BEFORE.json'),before)
            database_before=sql_snapshot(area/('database-before-'+uuid.uuid4().hex),data,before)
            report={'action':args.action,'live_acceptance':'NOT_TESTED_BY_AUTHOR','protected_files':len(before),'database_before':database_before,'receipt':str(area/'RECEIPT.json')}
            require(shutil.disk_usage(area).free > required_space(data,before,engine), 'INSUFFICIENT_BACKUP_SPACE')
            started=False
            try:
                if args.action=='apply':
                    # Complete isolated imports before publication; repeat against installed bytes afterwards.
                    stage=area/'preflight-source'; stage.mkdir()
                    for pkg in ('stock_app','modern_ui'):
                        shutil.copytree(engine/pkg,stage/pkg,ignore=shutil.ignore_patterns('__pycache__'))
                    for r in manifest['files']: atomic(child(stage,r['path']),child(package/'candidate',r['path']).read_bytes())
                    report['preflight_imports']=import_check(stage,area,package,engine/'.replay-v10-deps')
                    begin(engine,area,package,guard,manifest,before); started=True
                    publish(engine,area,package,manifest,check=lambda:closed(data)); verify(engine,expected(guard,manifest,True))
                    report['post_install_imports']=import_check(engine,area,package)
                else:
                    restore(engine,area,guard,manifest,check=lambda:closed(data))
                    report['restored_imports']=import_check(engine,area,package)
                require(inventory(data,excluded)==before,'PROTECTED_STATE_CHANGED_DO_NOT_START_APP')
                after_db=sql_snapshot(area/('database-after-'+uuid.uuid4().hex),data,before)
                require(after_db==database_before,'DATABASE_TABLES_OR_ACCOUNTING_CHANGED')
                report.update(status='PASS',protected_byte_equality=True,all_sqlite_tables_equal=True,paper_and_journal_preservation='ALL_DATABASE_TABLES_AND_ALL_NON_SOURCE_FILES_BYTE_IDENTICAL',frozen_contract='UNCHANGED',replay_effect='Source identity changes can legitimately stale the previously 3 COMPLETE records. All evidence files retained; no promotion, modification, API call or replay executed.',database_after=after_db)
                if args.action=='apply':
                    r=load(area/'RECEIPT.json'); r['state']='COMMITTED'; r['verified_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat(); write(area/'RECEIPT.json',r)
                write(area/'RESULTS.json',report); print('PASS. Receipt and private machine results: '+str(area),flush=True)
            except BaseException as e:
                report.update(status='FAIL',error=str(e))
                if args.action=='apply' and started:
                    try: restore(engine,area,guard,manifest,check=lambda:closed(data)); report['automatic_source_rollback']='PASS'
                    except BaseException as rollback_error: report['automatic_source_rollback']='BLOCKED:'+str(rollback_error)
                report['protected_byte_equality']=inventory(data,excluded)==before
                write(area/'RESULTS.json',report)
                raise
    finally:
        lock.seek(0); msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1); lock.close()

if __name__=='__main__':
    try: main()
    except BaseException as exc:
        print('STOP: '+str(exc)+'\nKeep SRE closed on any incomplete receipt. Use ROLLBACK_C01.ps1 -ReceiptPath with the printed receipt path. No database repair or replay is performed.',file=sys.stderr); sys.exit(1)
