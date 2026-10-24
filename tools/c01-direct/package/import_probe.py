"""Imports only. No factory, API, refresh, replay, live database connection or native app launch."""
from pathlib import Path
import sys,os,importlib,json
sys.dont_write_bytecode=True
root=Path(sys.argv[1]).resolve(); deps=Path(sys.argv[2]).resolve()
# Application writes are confined to the disposable check copy; network/process/SQLite access is refused.
def audit(event,args):
    if event.startswith(('socket.connect','socket.bind','subprocess.Popen','os.system','os.startfile')):
        raise RuntimeError('IMPORT_SIDE_EFFECT_REFUSED:'+event)
    if event=='sqlite3.connect': raise RuntimeError('IMPORT_DATABASE_CONNECT_REFUSED')
    if event=='open':
        name,mode,flags=args
        if isinstance(name,(str,bytes,os.PathLike)) and ((flags or 0)&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)):
            if not Path(os.fsdecode(name)).resolve().is_relative_to(root): raise RuntimeError('IMPORT_WRITE_OUTSIDE_CHECK_COPY')
    if event in ('os.remove','os.rmdir','os.mkdir','os.rename','os.link','os.symlink','os.chmod','os.utime'):
        for v in args[:2] if event in ('os.rename','os.link','os.symlink') else args[:1]:
            if isinstance(v,(str,bytes,os.PathLike)) and not Path(os.fsdecode(v)).resolve().is_relative_to(root): raise RuntimeError('IMPORT_MUTATION_OUTSIDE_CHECK_COPY:'+event)
sys.addaudithook(audit)
sys.path[:0]=[str(root),str(deps)]
handles=[]
if hasattr(os,'add_dll_directory'):
    for base in (Path(sys.prefix),deps):
        for p in [base,*base.glob('*.libs'),base/'pyarrow']:
            if p.is_dir(): handles.append(os.add_dll_directory(str(p)))
mods=['stock_app.official_cache_guard','stock_app.official_daily_refresh','stock_app.portfolio','stock_app.historical','stock_app.replay_v10','modern_ui.api']
for name in mods:
    m=importlib.import_module(name)
    if not Path(m.__file__).resolve().is_relative_to(root): raise RuntimeError('WRONG_IMPORT_ORIGIN:'+name)
print(json.dumps({'status':'PASS','modules':mods,'scope':'isolated source copy; no app factory invoked'}))
