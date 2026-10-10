from __future__ import annotations

import sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.semantic_interpretation import semantic_audit, semantic_class  # noqa: E402

RESULTS=[]
def require(v,msg='assertion failed'):
    if not v:
        raise AssertionError(msg)
def case(cat,name,fn):
    try:
        fn(); status,detail='PASS',''
    except Exception as exc:
        status,detail='FAIL',f'{type(exc).__name__}: {exc}'
    RESULTS.append({'category':cat,'test':name,'status':status,'detail':detail})

def e(feature,direction,transition,comparison='QOQ'):
    return {
      'symbol':'ABC','reporting_basis':'CONSOLIDATED','feature':feature,
      'comparison':comparison,'current_quarter_end':'2026-06-30',
      'direction':direction,'sign_transition':transition,
      'effective_availability_ts':'2026-07-31T12:00:00+05:30'
    }

case('DIRECT','revenue increase candidate improvement',lambda: require(
 semantic_class(e('REVENUE','INCREASE','POSITIVE_TO_POSITIVE'))[0]=='IMPROVEMENT_CANDIDATE'
))
case('DIRECT','revenue decrease candidate deterioration',lambda: require(
 semantic_class(e('REVENUE','DECREASE','POSITIVE_TO_POSITIVE'))[0]=='DETERIORATION_CANDIDATE'
))
case('PROFIT','profit sign recovery strong improvement',lambda: require(
 semantic_class(e('PAT','INCREASE','NEGATIVE_TO_POSITIVE'))==(
  'IMPROVEMENT_CANDIDATE','STRONG_NEGATIVE_TO_POSITIVE'
 )
))
case('PROFIT','profit sign loss strong deterioration',lambda: require(
 semantic_class(e('EPS','DECREASE','POSITIVE_TO_NEGATIVE'))==(
  'DETERIORATION_CANDIDATE','STRONG_POSITIVE_TO_NEGATIVE'
 )
))
case('OCF','ocf sign crossing interpreted',lambda: require(
 semantic_class(e('OPERATING_CASH_FLOW','DECREASE','POSITIVE_TO_NEGATIVE','YOY_SAME_QUARTER_ONLY'))[0]
 =='DETERIORATION_CANDIDATE'
))
case('FINANCE','finance cost increase inverse deterioration',lambda: require(
 semantic_class(e('FINANCE_COST','INCREASE','POSITIVE_TO_POSITIVE'))[0]=='DETERIORATION_CANDIDATE'
))
case('FINANCE','finance cost sign anomaly contextual',lambda: require(
 semantic_class(e('FINANCE_COST','INCREASE','NEGATIVE_TO_POSITIVE'))[0]=='CONTEXT_REVIEW_REQUIRED'
))
case('CONTEXT','tax remains contextual',lambda: require(
 semantic_class(e('TAX','INCREASE','POSITIVE_TO_POSITIVE'))[0]=='CONTEXT_ONLY'
))
case('CONTEXT','cash remains contextual',lambda: require(
 semantic_class(e('CASH_AND_EQUIVALENTS','DECREASE','POSITIVE_TO_POSITIVE','YOY_SAME_QUARTER_ONLY'))[0]=='CONTEXT_ONLY'
))
case('NEUTRAL','unchanged PAT neutral',lambda: require(
 semantic_class(e('PAT','UNCHANGED','POSITIVE_TO_POSITIVE'))[0]=='NEUTRAL'
))

audit=semantic_audit([
 e('REVENUE','INCREASE','POSITIVE_TO_POSITIVE'),
 e('PAT','DECREASE','POSITIVE_TO_NEGATIVE'),
 e('TAX','INCREASE','POSITIVE_TO_POSITIVE'),
 e('FINANCE_COST','INCREASE','NEGATIVE_TO_POSITIVE'),
])
case('AUDIT','all events counted',lambda: require(audit['derived_event_count']==4))
case('AUDIT','no trading signal created',lambda: require(audit['trading_signal_created'] is False))
case('AUDIT','no market labels created',lambda: require(audit['market_labels_created'] is False))

failed=[x for x in RESULTS if x['status']!='PASS']
print({'tests':len(RESULTS),'passed':len(RESULTS)-len(failed),'failed':len(failed),'failures':failed})
if failed:
    raise SystemExit(1)
