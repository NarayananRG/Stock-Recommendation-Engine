from __future__ import annotations

import sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.canonical_mapping_audit import (  # noqa: E402
    audit_documents,
    classify_context,
    deterministic_candidate_status,
    enrich_candidate_facts,
)

RESULTS=[]
def require(v,msg='assertion failed'):
    if not v: raise AssertionError(msg)
def case(cat,name,fn):
    try: fn(); s,d='PASS',''
    except Exception as exc: s,d='FAIL',f'{type(exc).__name__}: {exc}'
    RESULTS.append({'category':cat,'test':name,'status':s,'detail':d})

quarter_ctx={'context_id':'Q','start_date':'2026-04-01','end_date':'2026-06-30','instant':None,'dimensions':[]}
annual_ctx={'context_id':'Y','start_date':'2025-04-01','end_date':'2026-03-31','instant':None,'dimensions':[]}
segment_ctx={'context_id':'S','start_date':'2026-04-01','end_date':'2026-06-30','instant':None,'dimensions':[{'dimension':'SegmentAxis','member':'A'}]}
instant_ctx={'context_id':'I','start_date':None,'end_date':None,'instant':'2026-06-30','dimensions':[]}

case('CONTEXT','quarter classified',lambda: require(classify_context(quarter_ctx,quarter_end='2026-06-30')['duration_bucket']=='QUARTER_LIKE'))
case('CONTEXT','annual classified',lambda: require(classify_context(annual_ctx,quarter_end='2026-03-31')['duration_bucket']=='ANNUAL_LIKE'))
case('CONTEXT','dimension preserved',lambda: require(classify_context(segment_ctx,quarter_end='2026-06-30')['undimensioned'] is False))
case('CONTEXT','instant aligned',lambda: require(classify_context(instant_ctx,quarter_end='2026-06-30')['end_aligned_to_quarter'] is True))

DOC={
 'symbol':'ABC','quarter_end':'2026-06-30','reporting_basis':'CONSOLIDATED',
 'submission_type':'ORIGINAL','source_event_id':'e1','availability_ts':'2026-07-20T10:00:00+05:30',
 'source_url':'https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_test.xml',
 'contexts':[quarter_ctx,segment_ctx,instant_ctx],
 'units':[{'unit_id':'INR','measures':['iso4217:INR']},{'unit_id':'R','measures':['xbrli:pure']}],
 'numeric_facts':[
   {'concept_local_name':'RevenueFromOperations','concept_namespace':'ns','context_ref':'Q','unit_ref':'INR','raw_value':'100','decimals':'0','scale':None},
   {'concept_local_name':'RevenueFromOperations','concept_namespace':'ns','context_ref':'S','unit_ref':'INR','raw_value':'30','decimals':'0','scale':None},
   {'concept_local_name':'ProfitLossForPeriod','concept_namespace':'ns','context_ref':'Q','unit_ref':'INR','raw_value':'10','decimals':'0','scale':None},
   {'concept_local_name':'Assets','concept_namespace':'ns','context_ref':'I','unit_ref':'INR','raw_value':'500','decimals':'0','scale':None},
   {'concept_local_name':'DebtEquityRatio','concept_namespace':'ns','context_ref':'I','unit_ref':'R','raw_value':'0.5','decimals':'2','scale':None},
 ]
}
ROWS=enrich_candidate_facts(DOC)
case('ENRICH','candidate rows found',lambda: require(len(ROWS)==5))
case('ENRICH','segment candidate marked dimensioned',lambda: require(
 any(x['concept_local_name']=='RevenueFromOperations' and x['undimensioned'] is False for x in ROWS)
))
REV=[x for x in ROWS if x['feature']=='REVENUE']
case('STATUS','one eligible undimensioned revenue',lambda: require(
 deterministic_candidate_status(REV)['status']=='SINGLE_STRUCTURAL_CANDIDATE'
))
AUDIT=audit_documents([DOC])
case('AUDIT','one document',lambda: require(AUDIT['document_count']==1))
case('AUDIT','revenue structurally single',lambda: require(
 AUDIT['per_document'][0]['features']['REVENUE']['status']=='SINGLE_STRUCTURAL_CANDIDATE'
))
case('AUDIT','assets structurally single',lambda: require(
 AUDIT['per_document'][0]['features']['TOTAL_ASSETS']['status']=='SINGLE_STRUCTURAL_CANDIDATE'
))

AMBIG_DOC=dict(DOC)
AMBIG_DOC['numeric_facts']=DOC['numeric_facts']+[
 {'concept_local_name':'Income','concept_namespace':'ns','context_ref':'Q','unit_ref':'INR','raw_value':'105','decimals':'0','scale':None}
]
AMBIG=audit_documents([AMBIG_DOC])
case('AUDIT','revenue ambiguity preserved',lambda: require(
 AMBIG['per_document'][0]['features']['REVENUE']['status']=='AMBIGUOUS_MULTIPLE_CANDIDATES'
))

failed=[x for x in RESULTS if x['status']!='PASS']
print({'tests':len(RESULTS),'passed':len(RESULTS)-len(failed),'failed':len(failed),'failures':failed})
if failed: raise SystemExit(1)
