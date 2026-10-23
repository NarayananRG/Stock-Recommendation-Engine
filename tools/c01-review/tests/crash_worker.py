"""Hard-exit test worker operating exclusively on its caller's temporary cache."""
from pathlib import Path
import os,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_c01 as f
root=Path(sys.argv[1]);mode=sys.argv[2]
original=f.g._durable_write;writes=0
if mode=='mid':
 def injected(path,data):
  global writes
  original(path,data)
  if Path(path).parent.resolve()==root.resolve() and Path(path).suffix=='.csv':
   writes+=1
   if writes==2:os._exit(73)
 f.g._durable_write=injected
elif mode=='committed':
 def injected(path,data):
  original(path,data)
  if Path(path).name=='state.json' and b'COMMITTED' in data:os._exit(74)
 f.g._durable_write=injected
elif mode=='hold':
 import time
 with f.g.cache_guard(root):
  (root/'SYNTHETIC_LOCK_HELD').write_text('ready');time.sleep(1)
 sys.exit(0)
with f.provider(f.equity(f.NEW_DAY),f.index(f.NEW_DAY)):
 result=f.m.refresh_official_session([str(root)],f.NEW_DAY)
if result['status'] not in ('REFRESHED_AND_VERIFIED','ALREADY_CURRENT'):raise RuntimeError(str(result))
