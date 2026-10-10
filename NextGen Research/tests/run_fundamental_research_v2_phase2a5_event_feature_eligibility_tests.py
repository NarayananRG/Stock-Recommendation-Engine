from __future__ import annotations

import sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.event_feature_eligibility import eligibility_audit  # noqa: E402

RESULTS=[]
def require(v,msg='assertion failed'):
    if not v: raise AssertionError(msg)
def case(cat,name,fn):
    try: fn(); s,d='PASS',''
    except Exception as exc: s,d='FAIL',f'{type(exc).__name__}: {exc}'
    RESULTS.append({'category':cat,'test':name,'status':s,'detail':d})

def row(q,revenue=None,ocf=None,basis='CONSOLIDATED',archive=False):
    base={
      'symbol':'ABC','quarter_end':q,'reporting_basis':basis,'archive_gap':archive,
      'event_id':'E'+q,'availability_ts':q+'T12:00:00+05:30',
    }
    for feature,value in [('REVENUE',revenue),('OPERATING_CASH_FLOW',ocf)]:
        base[f'{feature}__status']=(
            'SOURCE_DOCUMENT_UNAVAILABLE' if archive
            else ('SELECTED' if value is not None else 'MISSING_EXPECTED_PERIOD')
        )
        base[f'{feature}__value']=None if archive else value
    base['DEBT_EQUITY_RATIO__status']='NOT_MAPPED_FOR_DOMAIN'
    base['DEBT_EQUITY_RATIO__value']=None
    return base

rows=[
 row('2025-03-31','100','10'),
 row('2025-06-30','110',None),
 row('2025-09-30','120','12'),
 row('2025-12-31','130',None),
 row('2026-03-31','140','14'),
 row('2026-06-30','150',None),
]
audit=eligibility_audit(rows)
rev=next(x for x in audit['feature_eligibility'] if x['feature']=='REVENUE')
ocf=next(x for x in audit['feature_eligibility'] if x['feature']=='OPERATING_CASH_FLOW')
der=next(x for x in audit['feature_eligibility'] if x['feature']=='DEBT_EQUITY_RATIO')

case('POLICY','revenue permits qoq',lambda: require('QOQ' in rev['allowed_comparisons']))
case('POLICY','revenue five qoq comparisons',lambda: require(rev['qoq_eligible_count']==5))
case('POLICY','revenue two yoy comparisons',lambda: require(rev['yoy_eligible_count']==2))
case('POLICY','ocf forbids qoq',lambda: require(ocf['qoq_eligible_count']==0 and 'QOQ' not in ocf['allowed_comparisons']))
case('POLICY','ocf same-quarter yoy only',lambda: require(ocf['yoy_eligible_count']==1))
case('POLICY','debt equity excluded',lambda: require(der['excluded'] is True))
case('PIT','effective timestamp comes from current event',lambda: require(
 all(x['effective_availability_ts']==x['current_quarter_end']+'T12:00:00+05:30' for x in audit['eligible_events'])
))
case('SAFETY','no derived values created',lambda: require(audit['derived_feature_values_created'] is False))

failed=[x for x in RESULTS if x['status']!='PASS']
print({'tests':len(RESULTS),'passed':len(RESULTS)-len(failed),'failed':len(failed),'failures':failed})
if failed: raise SystemExit(1)
