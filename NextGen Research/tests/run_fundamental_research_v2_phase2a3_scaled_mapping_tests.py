from __future__ import annotations

import sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.scaled_mapping_validation import (  # noqa: E402
    compact_document_resolution,
    latest_event_groups,
    summarize_resolutions,
)

RESULTS=[]
def require(v,msg='assertion failed'):
    if not v: raise AssertionError(msg)
def case(cat,name,fn):
    try: fn(); s,d='PASS',''
    except Exception as exc: s,d='FAIL',f'{type(exc).__name__}: {exc}'
    RESULTS.append({'category':cat,'test':name,'status':s,'detail':d})

base={
 'symbol':'ABC','quarter_end':'2026-06-30','reporting_basis':'CONSOLIDATED',
 'submission_type':'ORIGINAL','publication_ts':'2026-07-20T10:00:00+05:30',
 'creation_ts':'2026-07-20T10:00:02+05:30','broadcast_ts':'2026-07-20T10:00:00+05:30',
 'revised_ts':None,'availability_ts':'2026-07-20T10:00:02+05:30',
 'event_id':'old','xbrl_url':'https://nsearchives.nseindia.com/a.xml'
}
rev=dict(base)
rev.update({
 'submission_type':'REVISION','broadcast_ts':None,'revised_ts':'2026-07-20T10:01:00+05:30',
 'publication_ts':'2026-07-20T10:01:00+05:30','creation_ts':'2026-07-20T10:01:02+05:30',
 'availability_ts':'2026-07-20T10:01:02+05:30','event_id':'new','xbrl_url':None
})
G=latest_event_groups([base,rev])
case('SELECT','latest event retained even without xbrl',lambda: require(len(G)==1 and G[0]['event_id']=='new' and G[0]['xbrl_url'] is None))

CONTRACT={'domain_mappings':{'IND_AS_CORPORATE':{'REVENUE':'RevenueFromOperations'}}}
DOC={
 'source_event_id':'e','provider_seq_id':'1','symbol':'ABC','quarter_end':'2026-06-30',
 'reporting_basis':'CONSOLIDATED','submission_type':'ORIGINAL',
 'availability_ts':'2026-07-20T10:00:02+05:30',
 'source_url':'https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_x.xml',
 'source_content_sha256':'a'*64,'all_fact_count':1,'numeric_fact_count':1,'context_count':1,'unit_count':1,
 'contexts':[{'context_id':'Q','start_date':'2026-04-01','end_date':'2026-06-30','instant':None,'dimensions':[]}],
 'units':[{'unit_id':'INR','measures':['iso4217:INR']}],
 'numeric_facts':[{'concept_local_name':'RevenueFromOperations','concept_namespace':'ns','context_ref':'Q','unit_ref':'INR','raw_value':'100','decimals':'0','scale':None}],
}
R=compact_document_resolution(DOC,CONTRACT)
case('RESOLVE','frozen concept selected',lambda: require(R['features']['REVENUE']['selected_concept']=='RevenueFromOperations'))
case('RESOLVE','no hard failures',lambda: require(R['hard_failures']==[]))

IXDOC=dict(DOC)
IXDOC['source_url']='https://nsearchives.nseindia.com/corporate/ixbrl/opaque.xhtml'
IXDOC['domain_source_url']='https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_x.xml'
IXDOC['source_document_kind']='IXBRL'
RIX=compact_document_resolution(IXDOC,CONTRACT)
case('RESOLVE','iXBRL recovery keeps original domain identity',lambda: require(
 RIX['domain']=='IND_AS_CORPORATE' and RIX['hard_failures']==[]
))

MISSING=dict(DOC)
MISSING['numeric_facts']=[]
RM=compact_document_resolution(MISSING,CONTRACT)
case('RESOLVE','missing is coverage gap not semantic failure',lambda: require(
 len(RM['coverage_gaps'])==1 and RM['hard_failures']==[]
))

S=summarize_resolutions([R,RM],expected_document_count=2,retrieval_failures=[],url_gaps=[])
case('SUMMARY','coverage gap yields pass with gaps',lambda: require(S['status']=='PASS_WITH_QUANTIFIED_COVERAGE_GAPS'))

S2=summarize_resolutions([R],expected_document_count=2,retrieval_failures=[{'error':'x'}],url_gaps=[])
case('SUMMARY','retrieval failure is incomplete',lambda: require(S2['status']=='INCOMPLETE_RETRIEVAL'))

failed=[x for x in RESULTS if x['status']!='PASS']
print({'tests':len(RESULTS),'passed':len(RESULTS)-len(failed),'failed':len(failed),'failures':failed})
if failed: raise SystemExit(1)
