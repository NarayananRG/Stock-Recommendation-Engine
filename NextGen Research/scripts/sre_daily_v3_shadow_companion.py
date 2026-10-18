"""Gate A read-only companion: join saved daily results to PIT-qualified V3 shadow replay."""
import argparse,hashlib,json,sqlite3
from pathlib import Path
from collections import Counter
def sha256(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
 return h.hexdigest()
def build(state_path,db_path,replay_path):
 paths=(state_path,db_path,replay_path)
 before=[sha256(p) for p in paths]
 state=json.loads(state_path.read_text(encoding='utf-8'))
 replay=json.loads(replay_path.read_text(encoding='utf-8'))
 succ=state['last_successful_run'];rid=succ['run_id'];session=succ['market_session']
 if replay.get('run_id')!=rid or replay.get('authority')!='SHADOW_ONLY' or replay.get('cutoff','')[:10]<session:
  raise ValueError('SHADOW_RUN_PIT_IDENTITY_MISMATCH')
 shadow=replay['recovered'];by={x['symbol']:x for x in shadow}
 if len(by)!=len(shadow):raise ValueError('DUPLICATE_SHADOW_SYMBOL')
 with sqlite3.connect(f'file:{db_path}?mode=ro',uri=True) as db:
  db.execute('PRAGMA query_only=ON')
  candidates=db.execute('SELECT symbol,rank,raw_json FROM prediction_candidates WHERE run_id=?',(rid,)).fetchall()
 if not candidates or len(candidates)!=len(by) or {x[0] for x in candidates}!=set(by):
  raise ValueError('SHADOW_AND_DAILY_CANDIDATE_UNIVERSE_MISMATCH')
 rows=[]
 for sym,rank,raw in candidates:
  old=json.loads(raw)['combined_evidence'];v=by[sym]
  rows.append({'symbol':sym,'rank_unchanged':rank,'saved_combined_v1_eligibility':old.get('eligibility'),
  'saved_combined_v1_decision':old.get('combined_decision'),'fundamental_v3_shadow_status':v.get('status'),
  'fundamental_v3_weighted_coverage':v.get('coverage'),
  'v3_missing_components':[k for k,val in (v.get('component_signals') or {}).items() if val is None],
  'authority':'SHADOW_ONLY','action_override_allowed':False})
 rows.sort(key=lambda x:x['rank_unchanged'])
 if [sha256(p) for p in paths]!=before:raise RuntimeError('INPUT_CHANGED_WHILE_READING')
 return {'schema':'SRE_DAILY_V3_SHADOW_COMPANION_V1','authority':'SHADOW_ONLY',
  'daily_run_id':rid,'market_session':session,'decision_cutoff':replay['cutoff'],
  'saved_daily_recommendation_count':succ.get('recommendation_count'),
  'saved_daily_executable_count':succ.get('executable_count'),
  'daily_status_executable_count':(state.get('last_result') or {}).get('executable_count'),
  'candidate_count':len(rows),'v3_status_counts':dict(Counter(x['fundamental_v3_shadow_status'] for x in rows)),
  'legacy_eligibility_counts':dict(Counter(x['saved_combined_v1_eligibility'] for x in rows)),
  'input_sha256':dict(zip(('daily_state','prediction_db','shadow_replay'),before)),
  'legacy_actions_modified':False,'ranking_modified':False,'paper_orders_modified':False,
  'not_live_approval':True,'rows':rows}
def main():
 p=argparse.ArgumentParser()
 for n in ('state','db','replay','output'):p.add_argument('--'+n,required=True,type=Path)
 a=p.parse_args()
 if a.output.exists():raise FileExistsError('OUTPUT_EXISTS_REFUSE_OVERWRITE')
 result=build(a.state,a.db,a.replay)
 a.output.parent.mkdir(parents=True,exist_ok=True)
 a.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
 print(result['v3_status_counts'])
if __name__=='__main__':main()
