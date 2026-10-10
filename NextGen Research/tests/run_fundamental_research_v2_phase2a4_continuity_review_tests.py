from __future__ import annotations

import sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.continuity_findings_review import review_continuity  # noqa: E402

RESULTS=[]
def require(v,msg='assertion failed'):
    if not v: raise AssertionError(msg)
def case(cat,name,fn):
    try: fn(); s,d='PASS',''
    except Exception as exc: s,d='FAIL',f'{type(exc).__name__}: {exc}'
    RESULTS.append({'category':cat,'test':name,'status':s,'detail':d})

def row(q,value,status='SELECTED',basis='CONSOLIDATED',archive=False):
    return {
      'symbol':'ABC','quarter_end':q,'reporting_basis':basis,'archive_gap':archive,
      'REVENUE__status':('SOURCE_DOCUMENT_UNAVAILABLE' if archive else status),
      'REVENUE__value':(None if archive else value),
    }

rows=[
 row('2025-03-31','100'),
 row('2025-06-30','110'),
 row('2025-09-30',None,'MISSING_EXPECTED_PERIOD'),
 row('2025-12-31','130'),
 row('2026-03-31','140'),
 row('2026-06-30',None,archive=True),
]
review=review_continuity(rows)
r=next(x for x in review['basis_feature_continuity'] if x['feature']=='REVENUE' and x['reporting_basis']=='CONSOLIDATED')
case('REVIEW','mapped row present count',lambda: require(r['present_row_count']==4))
case('REVIEW','mapped row missing count',lambda: require(r['missing_mapped_row_count']==1))
case('REVIEW','archive gap excluded from mapped denominator',lambda: require(r['mapped_scope_row_count']==5))
case('REVIEW','history has at least four observations',lambda: require(r['histories_with_at_least_4_present']==1))
case('REVIEW','history not all six',lambda: require(r['histories_with_all_6_present']==0))
case('REVIEW','adjacent pairs count only both-present pairs',lambda: require(r['adjacent_pair_present_count']==2))
case('REVIEW','archive blocked adjacent pair tracked',lambda: require(r['adjacent_pair_archive_blocked_count']==1))
case('REVIEW','one available yoy pair',lambda: require(r['yoy_pair_present_count']==1))
case('REVIEW','growth not created',lambda: require(review['derived_growth_features_created'] is False))

failed=[x for x in RESULTS if x['status']!='PASS']
print({'tests':len(RESULTS),'passed':len(RESULTS)-len(failed),'failed':len(failed),'failures':failed})
if failed: raise SystemExit(1)
