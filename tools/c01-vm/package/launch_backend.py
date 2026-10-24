"""Launch the unchanged staged app factory in the isolated VM only. No refresh/replay route invoked."""
from pathlib import Path
import json,os,sys,threading
sys.path.insert(0,str(Path(__file__).resolve().parent));sys.dont_write_bytecode=True
from vm_environment import validate_context
validate_context('offline')
root=Path(sys.argv[1]).resolve();data=Path(sys.argv[2]).resolve();port=int(sys.argv[3]);require_root=Path('C:/C01').resolve()
if not(root.is_relative_to(require_root)and data.is_relative_to(require_root)):raise RuntimeError('VM_LOCAL_STAGING_PATHS_REQUIRED')
for key,value in {'STOCK_APP_REPO_ROOT':str(root),'STOCK_REAL_DATA_REPO_ROOT':str(root),'STOCK_APP_DATA_DIR':str(data.parent),'LOCALAPPDATA':str(data.parent),'APPDATA':str(data.parent),'USERPROFILE':str(data.parent),'HOME':str(data.parent),'PYTHONDONTWRITEBYTECODE':'1'}.items():os.environ[key]=value
os.environ.pop('SRE_EXPECTED_SESSION_NOW',None);os.environ['STOCK_MODERN_UI_PREVIEW']='0'
sys.path[:0]=[str(root),str(root/'.replay-v10-deps'),str(Path(sys.prefix)/'Lib/site-packages')]
if hasattr(os,'add_dll_directory'):
 handles=[]
 for base in [Path(sys.prefix),root/'.replay-v10-deps']:
  for p in [base,*base.glob('*.libs'),base/'pyarrow']:
   if p.is_dir():handles.append(os.add_dll_directory(str(p)))
from modern_ui.api import create_app
import uvicorn
app=create_app(repo_root=root,app_data_dir=data)
class NoActions:
 def __init__(self,app):self.app=app
 async def __call__(self,scope,receive,send):
  if scope['type']=='http'and scope['method']not in('GET','HEAD','OPTIONS'):
   await send({'type':'http.response.start','status':403,'headers':[(b'content-type',b'application/json')]});await send({'type':'http.response.body','body':b'{"detail":"C01 staging: state-changing HTTP methods disabled"}'});return
  await self.app(scope,receive,send)
server=uvicorn.Server(uvicorn.Config(NoActions(app),host='127.0.0.1',port=port,log_level='warning',access_log=False))
def control():
 for line in sys.stdin:
  if line.strip()=='STOP':server.should_exit=True;return
threading.Thread(target=control,daemon=True).start();server.run()
