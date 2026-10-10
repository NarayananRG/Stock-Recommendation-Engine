from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.derived_event_transforms import (  # noqa: E402
    symmetric_change,
    transform_event,
)

RESULTS=[]
def require(v,msg='assertion failed'):
    if not v:
        raise AssertionError(msg)

def raises_code(fn, code):
    try:
        fn()
    except Exception as exc:
        return code in str(exc)
    return False

def case(cat,name,fn):
    try:
        fn(); status,detail='PASS',''
    except Exception as exc:
        status,detail='FAIL',f'{type(exc).__name__}: {exc}'
    RESULTS.append({'category':cat,'test':name,'status':status,'detail':detail})

case('MATH','positive growth symmetric',lambda: require(
 symmetric_change(Decimal('100'),Decimal('120'))==Decimal('40')/Decimal('220')
))
case('MATH','negative to positive bounded',lambda: require(
 symmetric_change(Decimal('-10'),Decimal('10'))==Decimal('2')
))
case('MATH','positive to negative bounded',lambda: require(
 symmetric_change(Decimal('10'),Decimal('-10'))==Decimal('-2')
))
case('MATH','zero to zero defined',lambda: require(
 symmetric_change(Decimal('0'),Decimal('0'))==Decimal('0')
))
case('MATH','zero to positive defined',lambda: require(
 symmetric_change(Decimal('0'),Decimal('5'))==Decimal('2')
))

eligible={
 'symbol':'ABC','reporting_basis':'CONSOLIDATED','feature':'PAT','comparison':'YOY',
 'previous_quarter_end':'2025-03-31','current_quarter_end':'2026-03-31',
 'previous_event_id':'E1','current_event_id':'E2',
 'effective_availability_ts':'2026-05-01T12:00:00+05:30',
}
previous={
 'symbol':'ABC','reporting_basis':'CONSOLIDATED','event_id':'E1',
 'availability_ts':'2025-05-01T12:00:00+05:30','PAT__value':'-10',
}
current={
 'symbol':'ABC','reporting_basis':'CONSOLIDATED','event_id':'E2',
 'availability_ts':'2026-05-01T12:00:00+05:30','PAT__value':'15',
}
event=transform_event(eligible,previous,current)

case('EVENT','absolute delta preserved',lambda: require(event['absolute_delta']=='25'))
case('EVENT','sign transition explicit',lambda: require(event['sign_transition']=='NEGATIVE_TO_POSITIVE'))
case('EVENT','direction value-only',lambda: require(event['direction']=='INCREASE'))
case('EVENT','effective timestamp current filing',lambda: require(
 event['effective_availability_ts']=='2026-05-01T12:00:00+05:30'
))
case('SAFETY','traditional percent omitted',lambda: require(
 event['traditional_percent_change_created'] is False
))
case('SAFETY','semantic label omitted',lambda: require(
 event['semantic_good_bad_label_created'] is False
))

bad_basis=dict(current); bad_basis['reporting_basis']='STANDALONE'
case('PIT','cross basis rejected',lambda: require(
 raises_code(lambda: transform_event(eligible,previous,bad_basis),'CROSS_BASIS_COMPARISON_FORBIDDEN')
))

bad_time=dict(current); bad_time['availability_ts']='2024-01-01T00:00:00+05:30'
bad_eligible=dict(eligible); bad_eligible['effective_availability_ts']=bad_time['availability_ts']
case('PIT','timestamp inversion rejected',lambda: require(
 raises_code(lambda: transform_event(bad_eligible,previous,bad_time),'PIT_TIMESTAMP_ORDER_VIOLATION')
))

failed=[x for x in RESULTS if x['status']!='PASS']
print({'tests':len(RESULTS),'passed':len(RESULTS)-len(failed),'failed':len(failed),'failures':failed})
if failed:
    raise SystemExit(1)
