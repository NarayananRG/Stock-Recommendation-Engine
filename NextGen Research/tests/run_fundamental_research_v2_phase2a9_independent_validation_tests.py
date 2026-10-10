from __future__ import annotations
import sys
from pathlib import Path
REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))
from fundamental_research_v2_phase2a.independent_validation import validation_table,final_decision

RESULTS=[]
def req(v,m='assertion failed'):
    if not v: raise AssertionError(m)
def case(n,fn):
    try: fn(); s,d='PASS',''
    except Exception as exc: s,d='FAIL',f'{type(exc).__name__}: {exc}'
    RESULTS.append({'test':n,'status':s,'detail':d})

rows=[]
for split_q in ['2025-09-30','2026-03-31']:
  for h in [21,63]:
    for i in range(40):
      rows.append({'mature':True,'event_profile':'PURE_DETERIORATION','current_quarter_end':split_q,'horizon_sessions':h,'forward_return':-0.05+i*0.0001})
      rows.append({'mature':True,'event_profile':'PURE_IMPROVEMENT','current_quarter_end':split_q,'horizon_sessions':h,'forward_return':0.05+i*0.0001})
table=validation_table(rows)
case('oos 21 eligible',lambda: req(next(x for x in table if x['split']=='OUT_OF_SAMPLE' and x['horizon_sessions']==21)['eligible_for_validation']))
case('oos 21 supports',lambda: req(next(x for x in table if x['split']=='OUT_OF_SAMPLE' and x['horizon_sessions']==21)['directional_support']))
decision=final_decision(rows,0.90)
case('validated candidate decision',lambda: req(decision['decision']=='VALIDATED_RISK_FILTER_CANDIDATE_SHADOW_ONLY'))
case('promotion still false',lambda: req(decision['promotion_authorized'] is False))
case('research closed',lambda: req(decision['fundamental_v2_research_cycle_closed'] is True))
low=final_decision(rows,0.50)
case('coverage gate dominates',lambda: req(low['decision']=='DO_NOT_PROMOTE_INSUFFICIENT_OFFICIAL_PRICE_COVERAGE'))

failed=[x for x in RESULTS if x['status']!='PASS']
print({'tests':len(RESULTS),'passed':len(RESULTS)-len(failed),'failed':len(failed),'failures':failed})
if failed: raise SystemExit(1)
