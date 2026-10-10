from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "NextGen Research"
sys.path.insert(0, str(ROOT))

from fundamental_research_v2_phase2a.xbrl_extraction import (  # noqa: E402
    latest_events_by_group,
    parse_ixbrl_document,
    parse_xbrl_document,
    sha256_bytes,
)

RESULTS=[]
def require(v,msg='assertion failed'):
    if not v: raise AssertionError(msg)
def case(cat,name,fn):
    try: fn(); s,d='PASS',''
    except Exception as exc: s,d='FAIL',f'{type(exc).__name__}: {exc}'
    RESULTS.append({'category':cat,'test':name,'status':s,'detail':d})

XML=b'''<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl
 xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
 xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
 xmlns:in="https://example.test/indas">
  <xbrli:context id="D2026">
    <xbrli:entity><xbrli:identifier scheme="TEST">ABC</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:unit id="INR"><xbrli:measure>iso4217:INR</xbrli:measure></xbrli:unit>
  <in:RevenueFromOperations contextRef="D2026" unitRef="INR" decimals="-6">123456000</in:RevenueFromOperations>
  <in:ProfitLoss contextRef="D2026" unitRef="INR" decimals="-6">23456000</in:ProfitLoss>
  <in:SomeText contextRef="D2026">Quarterly result</in:SomeText>
  <in:NilFact contextRef="D2026" unitRef="INR" xsi:nil="true"/>
</xbrli:xbrl>'''

EVENT={
  'event_id':'evt1','symbol':'ABC','quarter_end':'2026-06-30',
  'reporting_basis':'CONSOLIDATED','submission_type':'ORIGINAL',
  'provider_seq_id':'1','broadcast_ts':'2026-07-20T10:00:00+05:30',
  'revised_ts':None,'creation_ts':'2026-07-20T10:00:02+05:30',
  'publication_ts':'2026-07-20T10:00:00+05:30',
  'availability_ts':'2026-07-20T10:00:02+05:30',
  'xbrl_url':'https://nsearchives.nseindia.com/corporate/xbrl/test.xml',
  'source_exchange':'NSE','source_sha256':'a'*64,
}

P=parse_xbrl_document(XML,source_url=EVENT['xbrl_url'],source_event=EVENT)
case('HASH','sha256 stable',lambda: require(len(sha256_bytes(XML))==64))
case('PARSE','one context',lambda: require(P['context_count']==1))
case('PARSE','one unit',lambda: require(P['unit_count']==1))
case('PARSE','four facts observed',lambda: require(P['all_fact_count']==4))
case('PARSE','two numeric facts',lambda: require(P['numeric_fact_count']==2))
case('PARSE','nil fact counted',lambda: require(P['nil_fact_count']==1))
case('PARSE','revenue concept preserved',lambda: require(
    any(x['concept_local_name']=='RevenueFromOperations' for x in P['numeric_facts'])
))
case('PARSE','context period preserved',lambda: require(P['contexts'][0]['end_date']=='2026-06-30'))
case('PARSE','availability preserved',lambda: require(P['availability_ts']=='2026-07-20T10:00:02+05:30'))


IXBRL=b'''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
 xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
 xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
 xmlns:in="https://example.test/indas">
 <body>
  <ix:resources>
   <xbrli:context id="D2026">
    <xbrli:entity><xbrli:identifier scheme="TEST">ABC</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period>
   </xbrli:context>
   <xbrli:unit id="INR"><xbrli:measure>iso4217:INR</xbrli:measure></xbrli:unit>
  </ix:resources>
  <div>
   <ix:nonFraction name="in:RevenueFromOperations" contextRef="D2026" unitRef="INR" decimals="-6">123456000</ix:nonFraction>
   <ix:nonFraction name="in:ProfitLossForPeriod" contextRef="D2026" unitRef="INR" decimals="-6">23456000</ix:nonFraction>
  </div>
 </body>
</html>'''
IX_EVENT=dict(EVENT)
IX_EVENT['ixbrl_url']='https://nsearchives.nseindia.com/corporate/ixbrl/test.xhtml'
IX=parse_ixbrl_document(IXBRL,source_url=IX_EVENT['ixbrl_url'],source_event=IX_EVENT)
case('IXBRL','same event identity preserved',lambda: require(IX['source_event_id']=='evt1'))
case('IXBRL','source representation tagged',lambda: require(IX['source_document_kind']=='IXBRL'))
case('IXBRL','contexts parsed',lambda: require(IX['context_count']==1))
case('IXBRL','units parsed',lambda: require(IX['unit_count']==1))
case('IXBRL','inline numeric facts parsed',lambda: require(IX['numeric_fact_count']==2))
case('IXBRL','inline revenue concept resolved',lambda: require(
    any(x['concept_local_name']=='RevenueFromOperations' for x in IX['numeric_facts'])
))
case('IXBRL','inline concept namespace resolved',lambda: require(
    any(x['concept_namespace']=='https://example.test/indas' for x in IX['numeric_facts'])
))

OLD=dict(EVENT)
OLD['event_id']='old'
OLD['creation_ts']='2026-07-20T10:00:01+05:30'
OLD['availability_ts']='2026-07-20T10:00:01+05:30'
NEW=dict(EVENT)
NEW['event_id']='new'
NEW['submission_type']='REVISION'
NEW['broadcast_ts']=None
NEW['revised_ts']='2026-07-20T10:00:03+05:30'
NEW['publication_ts']='2026-07-20T10:00:03+05:30'
NEW['creation_ts']='2026-07-20T10:00:04+05:30'
NEW['availability_ts']='2026-07-20T10:00:04+05:30'
SELECTED=latest_events_by_group([OLD,NEW],symbols={'ABC'},quarters={'2026-06-30'})
case('SELECT','latest version selected',lambda: require(len(SELECTED)==1 and SELECTED[0]['event_id']=='new'))
case('SELECT','unrequested symbol excluded',lambda: require(
    latest_events_by_group([OLD],symbols={'XYZ'},quarters={'2026-06-30'})==[]
))

failed=[x for x in RESULTS if x['status']!='PASS']
print({'tests':len(RESULTS),'passed':len(RESULTS)-len(failed),'failed':len(failed),'failures':failed})
if failed: raise SystemExit(1)
