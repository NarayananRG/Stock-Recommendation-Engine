from __future__ import annotations
import sys
from pathlib import Path
REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))
from fundamental_research_v2_phase2a.risk_event_builder import build_risk_profiles,summarize_profiles

RESULTS=[]
def require(v,msg='assertion failed'):
    if not v: raise AssertionError(msg)
def case(n,fn):
    try: fn(); s,d='PASS',''
    except Exception as exc: s,d='FAIL',f'{type(exc).__name__}: {exc}'
    RESULTS.append({'test':n,'status':s,'detail':d})
def ev(feature,direction,transition,event_id='E1'):
    return {
      'symbol':'ABC','reporting_basis':'CONSOLIDATED','current_event_id':event_id,
      'current_quarter_end':'2026-03-31','effective_availability_ts':'2026-05-01T12:00:00+05:30',
      'feature':feature,'comparison':'YOY','direction':direction,
      'sign_transition':transition,'symmetric_change':'0.2'
    }

pure_det=build_risk_profiles([ev('REVENUE','DECREASE','POSITIVE_TO_POSITIVE')])[0]
case('pure deterioration',lambda: require(pure_det['event_profile']=='PURE_DETERIORATION'))
pure_imp=build_risk_profiles([ev('PAT','INCREASE','POSITIVE_TO_POSITIVE')])[0]
case('pure improvement',lambda: require(pure_imp['event_profile']=='PURE_IMPROVEMENT'))
mixed=build_risk_profiles([
 ev('REVENUE','DECREASE','POSITIVE_TO_POSITIVE'),
 ev('PAT','INCREASE','POSITIVE_TO_POSITIVE')
])[0]
case('mixed retained',lambda: require(mixed['event_profile']=='MIXED_DIRECTIONAL'))
strong=build_risk_profiles([ev('PAT','DECREASE','POSITIVE_TO_NEGATIVE')])[0]
case('strong deterioration sign crossing',lambda: require(strong['strong_deterioration_transition'] is True))
context=build_risk_profiles([ev('TAX','INCREASE','POSITIVE_TO_POSITIVE')])[0]
case('context only no directional profile',lambda: require(context['event_profile']=='NO_DIRECTIONAL_EVIDENCE'))
summary=summarize_profiles([pure_det,pure_imp,mixed,strong,context])
case('summary count',lambda: require(summary['event_profile_count']==5))
case('no score',lambda: require(summary['composite_score_created'] is False))
case('no signal',lambda: require(summary['trading_signal_created'] is False))
failed=[x for x in RESULTS if x['status']!='PASS']
print({'tests':len(RESULTS),'passed':len(RESULTS)-len(failed),'failed':len(failed),'failures':failed})
if failed: raise SystemExit(1)
