from __future__ import annotations

import sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.ambiguity_resolution import (  # noqa: E402
    diagnose_feature_rows,
    normalized_numeric_value,
)

RESULTS=[]
def require(v,msg='assertion failed'):
    if not v: raise AssertionError(msg)
def case(cat,name,fn):
    try: fn(); s,d='PASS',''
    except Exception as exc: s,d='FAIL',f'{type(exc).__name__}: {exc}'
    RESULTS.append({'category':cat,'test':name,'status':s,'detail':d})

BASE={
 'end_aligned_to_quarter':True,'undimensioned':True,'period_kind':'DURATION',
 'duration_bucket':'QUARTER_LIKE','duration_days':91,'unit_measures':['iso4217:INR'],
 'concept_local_name':'RevenueFromOperations','context_ref':'Q1','raw_value':'100',
 'scale':None,'sign':None,
}
case('VALUE','raw numeric preserved',lambda: require(normalized_numeric_value(BASE)=='100'))
scaled=dict(BASE); scaled['raw_value']='1.2'; scaled['scale']='3'
case('VALUE','scale applied',lambda: require(normalized_numeric_value(scaled)=='1200'))

single=diagnose_feature_rows([BASE],feature='REVENUE')
case('STATUS','single expected candidate',lambda: require(single['status']=='SINGLE_EXPECTED_PERIOD_CANDIDATE'))

dup=dict(BASE); dup['context_ref']='Q1_ALT'
equiv=diagnose_feature_rows([BASE,dup],feature='REVENUE')
case('STATUS','equivalent duplicates identified',lambda: require(equiv['status']=='EQUIVALENT_DUPLICATE_CANDIDATES'))
case('STATUS','duplicate reason retained',lambda: require('EQUIVALENT_NUMERIC_DUPLICATES' in equiv['reason_codes']))

comp=dict(BASE); comp['context_ref']='Q1_ALT'; comp['raw_value']='101'
amb=diagnose_feature_rows([BASE,comp],feature='REVENUE')
case('STATUS','competing values are genuine ambiguity',lambda: require(amb['status']=='GENUINE_AMBIGUITY'))
case('STATUS','competing value reason retained',lambda: require('COMPETING_NUMERIC_VALUES' in amb['reason_codes']))

annual=dict(BASE); annual['context_ref']='FY'; annual['duration_bucket']='ANNUAL_LIKE'; annual['duration_days']=365; annual['raw_value']='400'
period=diagnose_feature_rows([BASE,annual],feature='REVENUE')
case('STATUS','quarter annual mixture ambiguous',lambda: require(period['status']=='GENUINE_AMBIGUITY'))
case('STATUS','multiple period buckets retained',lambda: require('MULTIPLE_DURATION_BUCKETS' in period['reason_codes']))

segment=dict(BASE); segment['undimensioned']=False
case('FILTER','dimensioned fact excluded from expected candidates',lambda: require(
 diagnose_feature_rows([segment],feature='REVENUE')['status']=='NO_EXPECTED_PERIOD_CANDIDATE'
))

instant={
 'end_aligned_to_quarter':True,'undimensioned':True,'period_kind':'INSTANT',
 'duration_bucket':None,'duration_days':None,'unit_measures':['iso4217:INR'],
 'concept_local_name':'Assets','context_ref':'I','raw_value':'500','scale':None,'sign':None,
}
case('FILTER','instant feature accepts instant context',lambda: require(
 diagnose_feature_rows([instant],feature='TOTAL_ASSETS')['status']=='SINGLE_EXPECTED_PERIOD_CANDIDATE'
))
case('FILTER','duration feature rejects instant context',lambda: require(
 diagnose_feature_rows([instant],feature='REVENUE')['status']=='NO_EXPECTED_PERIOD_CANDIDATE'
))

failed=[x for x in RESULTS if x['status']!='PASS']
print({'tests':len(RESULTS),'passed':len(RESULTS)-len(failed),'failed':len(failed),'failures':failed})
if failed: raise SystemExit(1)
