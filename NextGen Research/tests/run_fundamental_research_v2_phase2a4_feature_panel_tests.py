from __future__ import annotations

import sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.canonical_feature_panel import (  # noqa: E402
    FEATURES,
    build_panel_rows,
    continuity_audit,
)

RESULTS=[]
def require(v,msg='assertion failed'):
    if not v: raise AssertionError(msg)
def case(cat,name,fn):
    try: fn(); s,d='PASS',''
    except Exception as exc: s,d='FAIL',f'{type(exc).__name__}: {exc}'
    RESULTS.append({'category':cat,'test':name,'status':s,'detail':d})

def event(eid,quarter,basis='CONSOLIDATED'):
    return {
      'symbol':'ABC','quarter_end':quarter,'reporting_basis':basis,
      'submission_type':'ORIGINAL','availability_ts':quarter+'T12:00:00+05:30',
      'publication_ts':quarter+'T12:00:00+05:30','creation_ts':quarter+'T12:00:00+05:30',
      'broadcast_ts':quarter+'T12:00:00+05:30','revised_ts':None,
      'event_id':eid,'provider_seq_id':eid,
    }

def doc(eid,quarter):
    return {
      'source_event_id':eid,'symbol':'ABC','quarter_end':quarter,
      'reporting_basis':'CONSOLIDATED','submission_type':'ORIGINAL',
      'availability_ts':quarter+'T12:00:00+05:30','domain':'IND_AS_CORPORATE',
      'source_document_kind':'XBRL','retrieval_representation':'XBRL_PRIMARY',
      'source_content_sha256':'a'*64,'hard_failures':[],
      'features':{
        'REVENUE':{
          'status':'SELECTED','selected_concept':'RevenueFromOperations',
          'selected':{'normalized_value':'100'}
        }
      }
    }

events=[event('e1','2025-03-31'),event('e2','2025-06-30')]
docs=[doc('e1','2025-03-31')]
rows=build_panel_rows(events,docs,{'e2'})
case('PANEL','all expected rows preserved',lambda: require(len(rows)==2))
case('PANEL','archive gap preserved as row',lambda: require(
 any(x['event_id']=='e2' and x['archive_gap'] for x in rows)
))
case('PANEL','selected canonical value preserved',lambda: require(
 any(x['event_id']=='e1' and x['REVENUE__value']=='100' for x in rows)
))
case('PANEL','unmapped domain feature is explicit',lambda: require(
 any(x['event_id']=='e1' and x['EPS__status']=='NOT_MAPPED_FOR_DOMAIN' for x in rows)
))
case('PANEL','archive gap feature status explicit',lambda: require(
 any(x['event_id']=='e2' and x['REVENUE__status']=='SOURCE_DOCUMENT_UNAVAILABLE' for x in rows)
))

audit=continuity_audit(rows)
case('AUDIT','one symbol basis history',lambda: require(audit['history_count']==1))
case('AUDIT','archive row counted once',lambda: require(audit['archive_gap_row_count']==1))
case('AUDIT','feature set stable',lambda: require('REVENUE' in FEATURES and 'TOTAL_ASSETS' in FEATURES))

failed=[x for x in RESULTS if x['status']!='PASS']
print({'tests':len(RESULTS),'passed':len(RESULTS)-len(failed),'failed':len(failed),'failures':failed})
if failed: raise SystemExit(1)
