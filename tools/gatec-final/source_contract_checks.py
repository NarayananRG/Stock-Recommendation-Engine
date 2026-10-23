"""Execute captured official-refresh code only in disposable synthetic files."""
from pathlib import Path
import importlib.util,tempfile,json,csv,hashlib

def check(module_path):
 spec=importlib.util.spec_from_file_location('sre_official_contract_probe',module_path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 with tempfile.TemporaryDirectory() as t:
  root=Path(t);day='2026-10-22';header='Date,Open,High,Low,Close,Volume\n';row=day+',100,101,99,100,1000\n'
  for i in range(200):(root/(f'TEST{i:03d}.NS.csv')).write_text(header+row)
  (root/'INDEX_NSEI.csv').write_text(header+row)
  before={p.name:p.read_bytes() for p in root.glob('*.csv')}
  # Synthetic transport injection, not genuine official retrieval. No network calls.
  m._download_candidates=lambda *a,**k:(b'synthetic',{'url':'https://nsearchives.nseindia.com/SYNTHETIC-TEST','http_status':200})
  m._parse_bhav=lambda *a:({f'TEST{i:03d}':('100','101','99','100','1000') for i in range(200)},{'equity_session':day})
  m._fetch_index=lambda *a:(('100','101','99','100'),day,{'url':'https://nsearchives.nseindia.com/SYNTHETIC-INDEX'})
  r=m.refresh_official_session([str(root)],day)
  first={p.name:p.read_bytes() for p in root.glob('*.csv')};r2=m.refresh_official_session([str(root)],day)
  repeat={p.name:p.read_bytes() for p in root.glob('*.csv')}
  # A conflicting official response for an already present stock-session.
  m._parse_bhav=lambda *a:({f'TEST{i:03d}':('100','999','99','999','1000') for i in range(200)},{'equity_session':day})
  changed=m.refresh_official_session([str(root)],day)
  after={p.name:p.read_bytes() for p in root.glob('*.csv')}
  conflicts=[n for n in first if n.endswith('.NS.csv') and after[n]!=first[n]]
  pre_failure={p.name:p.read_bytes() for p in root.glob('*.csv')}
  def unavailable(*a,**k):raise m.OfficialDataNotReady('SYNTHETIC UNAVAILABLE')
  m._download_candidates=unavailable;failed=m.refresh_official_session([str(root)],day)
  return {'scope':'synthetic isolated module integration; no real official request','identical_row_retry_idempotent':first==repeat,'unavailable_status':failed['status'],'unavailable_preserves_rows':pre_failure=={p.name:p.read_bytes() for p in root.glob('*.csv')},'same_session_conflicts_replaced':len(conflicts),'conflicting_response_status':changed['status'],'no_silent_verified_row_replacement':'FAIL' if conflicts and changed['status']=='REFRESHED_AND_VERIFIED' else 'PASS','failure_handling':'PASS' if failed['status']=='OFFICIAL_NOT_READY' else 'FAIL','automatic_yfinance_fallback':changed.get('automatic_yfinance_fallback'), 'module_sha256':hashlib.sha256(Path(module_path).read_bytes()).hexdigest()}
if __name__=='__main__':
 import sys
 print(json.dumps(check(Path(sys.argv[1])),indent=2))
