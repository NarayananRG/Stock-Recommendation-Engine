from __future__ import annotations

import sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.period_semantic_resolution import (  # noqa: E402
    expected_cumulative_bucket,
    expected_period,
    resolve_feature,
)

RESULTS=[]
def require(v,msg='assertion failed'):
    if not v: raise AssertionError(msg)
def case(cat,name,fn):
    try: fn(); s,d='PASS',''
    except Exception as exc: s,d='FAIL',f'{type(exc).__name__}: {exc}'
    RESULTS.append({'category':cat,'test':name,'status':s,'detail':d})

case('PERIOD','March cash flow annual',lambda: require(expected_cumulative_bucket('2026-03-31')=='ANNUAL_LIKE'))
case('PERIOD','June cash flow quarter cumulative',lambda: require(expected_cumulative_bucket('2026-06-30')=='QUARTER_LIKE'))
case('PERIOD','September cash flow half year',lambda: require(expected_cumulative_bucket('2026-09-30')=='HALF_YEAR_LIKE'))
case('PERIOD','December cash flow nine month',lambda: require(expected_cumulative_bucket('2026-12-31')=='NINE_MONTH_LIKE'))

Q={
 'end_aligned_to_quarter':True,'undimensioned':True,'period_kind':'DURATION',
 'duration_bucket':'QUARTER_LIKE'
}
Y=dict(Q); Y['duration_bucket']='ANNUAL_LIKE'
I={'end_aligned_to_quarter':True,'undimensioned':True,'period_kind':'INSTANT','duration_bucket':None}
case('PERIOD','revenue takes quarter not annual',lambda: require(
 expected_period(Q,feature='REVENUE',quarter_end='2026-03-31')
 and not expected_period(Y,feature='REVENUE',quarter_end='2026-03-31')
))
case('PERIOD','assets take instant',lambda: require(expected_period(I,feature='TOTAL_ASSETS',quarter_end='2026-03-31')))
case('PERIOD','March OCF takes annual',lambda: require(
 expected_period(Y,feature='OPERATING_CASH_FLOW',quarter_end='2026-03-31')
))

CTX_Q={'context_id':'Q','start_date':'2026-04-01','end_date':'2026-06-30','instant':None,'dimensions':[]}
CTX_Y={'context_id':'Y','start_date':'2025-04-01','end_date':'2026-03-31','instant':None,'dimensions':[]}
UNIT={'unit_id':'INR','measures':['iso4217:INR']}

def doc(domain_token, quarter, facts, contexts):
    return {
      'symbol':'ABC','quarter_end':quarter,'reporting_basis':'CONSOLIDATED',
      'submission_type':'ORIGINAL','source_event_id':'e','availability_ts':'2026-07-01T00:00:00+05:30',
      'source_url':f'https://nsearchives.nseindia.com/corporate/xbrl/{domain_token}_x.xml',
      'contexts':contexts,'units':[UNIT],'numeric_facts':facts,
    }

FACT_R=[
 {'concept_local_name':'RevenueFromOperations','concept_namespace':'ns','context_ref':'Q','unit_ref':'INR','raw_value':'100','decimals':'0','scale':None},
 {'concept_local_name':'Income','concept_namespace':'ns','context_ref':'Q','unit_ref':'INR','raw_value':'105','decimals':'0','scale':None},
]
corp=doc('INDAS','2026-06-30',FACT_R,[CTX_Q])
case('RULE','corporate revenue prefers revenue from operations',lambda: require(
 resolve_feature(corp,feature='REVENUE')['selected_concept']=='RevenueFromOperations'
))
bank=doc('BANK','2026-06-30',FACT_R,[CTX_Q])
case('RULE','bank topline prefers income',lambda: require(
 resolve_feature(bank,feature='REVENUE')['selected_concept']=='Income'
))
nbfc=doc('NBFC','2026-06-30',FACT_R,[CTX_Q])
case('RULE','nbfc topline prefers income',lambda: require(
 resolve_feature(nbfc,feature='REVENUE')['selected_concept']=='Income'
))

PAT_FACTS=[
 {'concept_local_name':'ProfitLossForPeriodFromContinuingOperations','concept_namespace':'ns','context_ref':'Q','unit_ref':'INR','raw_value':'90','decimals':'0','scale':None},
 {'concept_local_name':'ProfitLossForPeriod','concept_namespace':'ns','context_ref':'Q','unit_ref':'INR','raw_value':'95','decimals':'0','scale':None},
]
patdoc=doc('INDAS','2026-06-30',PAT_FACTS,[CTX_Q])
case('RULE','PAT prefers total period profit',lambda: require(
 resolve_feature(patdoc,feature='PAT')['selected_concept']=='ProfitLossForPeriod'
))

TAX_FACTS=[
 {'concept_local_name':'CurrentTax','concept_namespace':'ns','context_ref':'Q','unit_ref':'INR','raw_value':'20','decimals':'0','scale':None},
 {'concept_local_name':'DeferredTax','concept_namespace':'ns','context_ref':'Q','unit_ref':'INR','raw_value':'-2','decimals':'0','scale':None},
 {'concept_local_name':'TaxExpense','concept_namespace':'ns','context_ref':'Q','unit_ref':'INR','raw_value':'18','decimals':'0','scale':None},
]
taxdoc=doc('INDAS','2026-06-30',TAX_FACTS,[CTX_Q])
case('RULE','tax prefers total tax expense',lambda: require(
 resolve_feature(taxdoc,feature='TAX')['selected_concept']=='TaxExpense'
))

failed=[x for x in RESULTS if x['status']!='PASS']
print({'tests':len(RESULTS),'passed':len(RESULTS)-len(failed),'failed':len(failed),'failures':failed})
if failed: raise SystemExit(1)
