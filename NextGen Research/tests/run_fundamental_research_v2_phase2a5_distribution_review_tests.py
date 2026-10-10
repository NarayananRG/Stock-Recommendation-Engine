from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.derived_event_distribution_review import (  # noqa: E402
    review_distributions,
    summarize_group,
)

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

events=[
 {'feature':'PAT','comparison':'QOQ','reporting_basis':'CONSOLIDATED',
  'symmetric_change':'-2','direction':'DECREASE','sign_transition':'POSITIVE_TO_NEGATIVE'},
 {'feature':'PAT','comparison':'QOQ','reporting_basis':'CONSOLIDATED',
  'symmetric_change':'0','direction':'UNCHANGED','sign_transition':'ZERO_TO_ZERO'},
 {'feature':'PAT','comparison':'QOQ','reporting_basis':'CONSOLIDATED',
  'symmetric_change':'2','direction':'INCREASE','sign_transition':'NEGATIVE_TO_POSITIVE'},
 {'feature':'REVENUE','comparison':'YOY','reporting_basis':'STANDALONE',
  'symmetric_change':'0.2','direction':'INCREASE','sign_transition':'POSITIVE_TO_POSITIVE'},
]
elig={
 'pre_pit_candidate_count':5,
 'pit_order_rejection_count':1,
 'pit_order_rejections':[{
   'feature':'REVENUE','comparison':'QOQ','reporting_basis':'STANDALONE'
 }]
}
pat=summarize_group(events[:3])
case('DIST','count preserved',lambda: require(pat['count']==3))
case('DIST','median zero',lambda: require(Decimal(pat['p50'])==Decimal('0')))
case('DIST','positive boundary counted',lambda: require(pat['positive_two_boundary_count']==1))
case('DIST','negative boundary counted',lambda: require(pat['negative_two_boundary_count']==1))
case('DIST','sign crossings counted',lambda: require(pat['sign_crossing_count']==2))
case('DIST','zero transition counted',lambda: require(pat['zero_transition_count']==1))

review=review_distributions(events,elig)
case('REVIEW','derived count preserved',lambda: require(review['derived_event_count']==4))
case('REVIEW','pit rejection preserved',lambda: require(review['pit_order_rejection_count']==1))
case('REVIEW','feature summaries split',lambda: require(len(review['feature_summary'])==2))
case('REVIEW','basis summaries split',lambda: require(len(review['feature_basis_summary'])==2))
case('SAFETY','no absolute delta cross-company distribution',lambda: require(
 review['absolute_delta_cross_company_distribution_created'] is False
))
case('SAFETY','no semantic labels',lambda: require(
 review['semantic_good_bad_label_created'] is False
))

failed=[x for x in RESULTS if x['status']!='PASS']
print({'tests':len(RESULTS),'passed':len(RESULTS)-len(failed),'failed':len(failed),'failures':failed})
if failed:
    raise SystemExit(1)
