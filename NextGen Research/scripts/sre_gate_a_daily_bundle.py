"""Fail-closed post-close V3 shadow sidecar writer. No trading authority or DB writes."""
from __future__ import annotations
import argparse,json
from datetime import date,datetime,timedelta
from pathlib import Path
from sre_daily_v3_shadow_companion import build
def validate(report):
 if report['authority']!='SHADOW_ONLY' or not report['not_live_approval']:
  raise ValueError('AUTHORITY_BOUNDARY')
 cutoff=datetime.fromisoformat(report['decision_cutoff']);session=date.fromisoformat(report['market_session'])
 if cutoff.date() not in (session,session+timedelta(days=1)):
  raise ValueError('INVALID_SESSION_CUTOFF')
 if report['candidate_count']!=sum(report['v3_status_counts'].values()):
  raise ValueError('CANDIDATE_COUNT_MISMATCH')
 if report['candidate_count']!=len(report['rows']):
  raise ValueError('ROW_COUNT_MISMATCH')
 if len({x['symbol'] for x in report['rows']})!=report['candidate_count']:
  raise ValueError('DUPLICATE_CANDIDATE')
 if not all(x['authority']=='SHADOW_ONLY' and x['action_override_allowed'] is False for x in report['rows']):
  raise ValueError('UNSAFE_ACTION_OVERRIDE')
 return report
def write_once(state,db,replay,output):
 inputs=(state,db,replay);out=output.resolve()
 if any(out==x.resolve() for x in inputs):
  raise ValueError('OUTPUT_OVERWRITES_INPUT')
 if out.exists():raise FileExistsError('OUTPUT_EXISTS_REFUSE_OVERWRITE')
 report=validate(build(state,db,replay))
 out.parent.mkdir(parents=True,exist_ok=True)
 with out.open('xb') as f:f.write((json.dumps(report,indent=2,sort_keys=True)+'\n').encode())
 return report
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('state','db','replay','output'):p.add_argument('--'+n,required=True,type=Path)
 a=p.parse_args();r=write_once(a.state,a.db,a.replay,a.output)
 print(json.dumps({'result':'SHADOW_SIDECAR_WRITTEN','run_id':r['daily_run_id'],
  'counts':r['v3_status_counts'],'output':str(a.output)},sort_keys=True))
if __name__=='__main__':main()
