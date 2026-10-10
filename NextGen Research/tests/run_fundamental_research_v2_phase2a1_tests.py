from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "NextGen Research"
sys.path.insert(0, str(ROOT))

from fundamental_research_v2_phase2a.core import effective_availability_ts, rebind_event_availability  # noqa: E402
from fundamental_research_v2_phase2a.validation import validate_pit_events  # noqa: E402

from fundamental_research_v2_phase2a.acquisition import (  # noqa: E402
    NSE_INTEGRATED_API,
    acquire_marketwide,
    acquire_symbol,
    build_query,
    extract_rows,
    map_nse_row,
    normalize_response,
    query_url,
    raw_payload_hash,
    target_quarter_filter,
)

RESULTS=[]
def require(v,msg='assertion failed'):
    if not v: raise AssertionError(msg)
def raises(error, fn, contains=None):
    try: fn()
    except error as exc:
        if contains: require(contains in str(exc), str(exc))
        return
    raise AssertionError(f'expected {error.__name__}')
def case(cat,name,fn):
    try: fn(); s,d='PASS',''
    except Exception as exc: s,d='FAIL',f'{type(exc).__name__}: {exc}'
    RESULTS.append({'category':cat,'test':name,'status':s,'detail':d})

sample_row = {
    'seq_Id':'12345',
    'symbol':'HDFCBANK','smName':'HDFC Bank Limited','qe_Date':'30-JUN-2026',
    'type_Sub':'Original','audited':'Un-Audited','consolidated':'Consolidated',
    'broadcast_Date':'18-Jul-2026 16:01:12','creation_Date':'18-Jul-2026 16:01:13',
    'revised_Date':'-','revision_Remark':'-',
    'xbrl':'https://nsearchives.nseindia.com/corporate/xbrl/test.xml',
    'ixbrl':'https://nsearchives.nseindia.com/corporate/ixbrl/test.html'
}
sample_payload={'data':[sample_row]}

case('QUERY','endpoint locked',lambda: require(NSE_INTEGRATED_API.endswith('/api/integrated-filing-results')))
case('QUERY','symbol alias in query',lambda: require(build_query(symbol='MANDM')['symbol']=='M&M'))
case('QUERY','marketwide query omits symbol',lambda: require('symbol' not in build_query()))
case('QUERY','filing type locked',lambda: require(build_query(symbol='ABC')['type']=='Integrated Filing- Financials'))
case('QUERY','invalid page rejected',lambda: raises(ValueError,lambda:build_query(symbol='ABC',page=0),'PAGINATION'))
case('QUERY','one date bound rejected',lambda: raises(ValueError,lambda:build_query(symbol='ABC',from_date=__import__('datetime').date(2025,1,1)),'BOTH_DATE'))
case('QUERY','URL exposes endpoint',lambda: require('integrated-filing-results' in query_url(build_query(symbol='ABC'))))
case('PAYLOAD','hash deterministic',lambda: require(raw_payload_hash(sample_payload)==raw_payload_hash({'data':[dict(sample_row)]})))
case('PAYLOAD','rows extracted',lambda: require(len(extract_rows(sample_payload))==1))
case('PAYLOAD','non-dict rejected',lambda: raises(ValueError,lambda:extract_rows([]),'PAYLOAD'))
case('MAP','qe field mapped',lambda: require(map_nse_row(sample_row)['Quarter End Date']=='30-JUN-2026'))
case('MAP','xbrl retained',lambda: require(map_nse_row(sample_row)['xbrl'].endswith('.xml')))
case('MAP','live broadcast field mapped',lambda: require(map_nse_row(sample_row)['BROADCAST DATE/TIME']=='18-Jul-2026 16:01:12'))
case('MAP','live revision field mapped',lambda: require(map_nse_row(sample_row)['Revision Remarks']=='-'))
case('MAP','provider seq retained',lambda: require(map_nse_row(sample_row)['seq_id']=='12345'))
case('MAP','ixbrl retained',lambda: require(map_nse_row(sample_row)['ixbrl'].endswith('.html')))
N=normalize_response(sample_payload)
case('NORMALIZE','row normalizes',lambda: require(N['normalized_event_count']==1))
case('NORMALIZE','source payload hashed',lambda: require(len(N['raw_payload_sha256'])==64))
case('NORMALIZE','target quarter normalized',lambda: require(N['events'][0]['quarter_end']=='2026-06-30'))
case('NORMALIZE','publication timestamp preserved',lambda: require(N['events'][0]['publication_ts'].startswith('2026-07-18T16:01:12')))
case('NORMALIZE','creation timestamp normalized',lambda: require(N['events'][0]['creation_ts'].startswith('2026-07-18T16:01:13')))
case('NORMALIZE','availability uses dissemination timestamp',lambda: require(N['events'][0]['availability_ts']==N['events'][0]['creation_ts']))

creation_before_broadcast=dict(sample_row)
creation_before_broadcast['broadcast_Date']='22-Apr-2025 20:04:55'
creation_before_broadcast['creation_Date']='22-Apr-2025 19:45:19'
creation_before_broadcast['qe_Date']='31-MAR-2025'
CB=normalize_response({'data':[creation_before_broadcast]})
case('NORMALIZE','availability uses later broadcast when creation is earlier',lambda: require(
    CB['events'][0]['availability_ts']==CB['events'][0]['broadcast_ts']
))
case('VALIDATE','creation-before-broadcast is warning not failure',lambda: require(
    validate_pit_events(CB['events'], required_symbols=['HDFCBANK'], require_all_target_quarters=False)['status']=='PASS'
))
case('VALIDATE','creation-before-broadcast warning preserved',lambda: require(
    any(x['code']=='ORIGINAL_TIMESTAMP_ORDER_DISAGREEMENT'
        for x in validate_pit_events(CB['events'], required_symbols=['HDFCBANK'], require_all_target_quarters=False)['warnings'])
))
case('NORMALIZE','provider seq survives',lambda: require(N['events'][0]['provider_seq_id']=='12345'))
case('FILTER','target retained',lambda: require(len(target_quarter_filter(N['events']))==1))

case('VALIDATE','single original PIT event passes',lambda: require(
    validate_pit_events(N['events'], required_symbols=['HDFCBANK'], require_all_target_quarters=False)['status']=='PASS'
))

revision_row=dict(sample_row)
revision_row['type_Sub']='Revision'
revision_row['broadcast_Date']=None
revision_row['revised_Date']='22-Jul-2026 10:15:00'
revision_row['creation_Date']='22-Jul-2026 10:15:03'
revision_payload={'data':[revision_row]}
R=normalize_response(revision_payload)
case('VALIDATE','revision row normalizes',lambda: require(R['normalized_event_count']==1))
case('VALIDATE','revision publication uses revised timestamp',lambda: require(
    R['events'][0]['publication_ts'].startswith('2026-07-22T10:15:00')
))
case('VALIDATE','revision broadcast remains null',lambda: require(
    R['events'][0]['broadcast_ts'] is None
))
case('VALIDATE','revision availability uses creation',lambda: require(
    R['events'][0]['availability_ts'].startswith('2026-07-22T10:15:03')
))
PAIR=N['events']+R['events']
case('VALIDATE','original plus later revision passes',lambda: require(
    validate_pit_events(PAIR, required_symbols=['HDFCBANK'], require_all_target_quarters=False)['status']=='PASS'
))

weird_revision=dict(sample_row)
weird_revision['type_Sub']='Revision'
weird_revision['broadcast_Date']=None
weird_revision['revised_Date']='18-Jul-2026 15:55:00'
weird_revision['creation_Date']='18-Jul-2026 16:01:20'
WR=normalize_response({'data':[weird_revision]})
case('VALIDATE','revision raw revised time may precede original if availability is later',lambda: require(
    validate_pit_events(N['events']+WR['events'], required_symbols=['HDFCBANK'], require_all_target_quarters=False)['status']=='PASS'
))

late_old = dict(N['events'][0])
late_old['event_id'] = 'late-old-quarter'
late_old['quarter_end'] = '2025-03-31'
late_old['publication_ts'] = '2026-08-01T10:00:00+05:30'
late_old['availability_ts'] = '2026-08-01T10:00:03+05:30'
late_old['broadcast_ts'] = '2026-08-01T10:00:00+05:30'
late_old['creation_ts'] = '2026-08-01T10:00:03+05:30'

newer_q = dict(N['events'][0])
newer_q['event_id'] = 'newer-quarter-earlier-filed'
newer_q['quarter_end'] = '2025-06-30'
newer_q['publication_ts'] = '2026-07-20T10:00:00+05:30'
newer_q['availability_ts'] = '2026-07-20T10:00:03+05:30'
newer_q['broadcast_ts'] = '2026-07-20T10:00:00+05:30'
newer_q['creation_ts'] = '2026-07-20T10:00:03+05:30'

LATE=validate_pit_events(
    [late_old,newer_q],
    required_symbols=['HDFCBANK'],
    require_all_target_quarters=False
)
case('VALIDATE','late older-quarter filing is warning not failure',lambda: require(LATE['status']=='PASS'))
case('VALIDATE','late older-quarter filing warning preserved',lambda: require(
    any(x['code']=='LATE_OR_OUT_OF_ORDER_ORIGINAL_FILING' for x in LATE['warnings'])
))

stale=dict(CB['events'][0])
stale['availability_ts']=stale['creation_ts']
old_id=stale['event_id']
rebound=rebind_event_availability(stale)
case('REBIND','cached availability repaired conservatively',lambda: require(
    rebound['availability_ts']==effective_availability_ts(rebound)==rebound['broadcast_ts']
))
case('REBIND','event identity changes when derived availability changes',lambda: require(
    rebound['event_id']!=old_id
))

bad_revision=dict(sample_row)
bad_revision['type_Sub']='Revision'
bad_revision['broadcast_Date']=None
bad_revision['revised_Date']='17-Jul-2026 10:15:00'
bad_revision['creation_Date']='17-Jul-2026 10:15:03'
BR=normalize_response({'data':[bad_revision]})
case('VALIDATE','revision before broadcast fails chronology',lambda: require(
    validate_pit_events(N['events']+BR['events'], required_symbols=['HDFCBANK'], require_all_target_quarters=False)['status']=='FAIL'
))

calls=[]
def fake_fetch(url,params,headers):
    calls.append((url,params,headers))
    return sample_payload
A=acquire_symbol('HDFCBANK',fetch_json=fake_fetch,page_size=50)
case('ACQUIRE','one page stops',lambda: require(A['page_count']==1))
case('ACQUIRE','target event counted',lambda: require(A['target_event_count']==1))
case('ACQUIRE','referer supplied',lambda: require('Referer' in calls[0][2]))
case('ACQUIRE','official endpoint supplied',lambda: require(calls[0][0]==NSE_INTEGRATED_API))

market_calls=[]
def market_fetch(url,params,headers):
    market_calls.append(params)
    return sample_payload
MW=acquire_marketwide(fetch_json=market_fetch,page_size=50)
case('MARKETWIDE','one partial page stops',lambda: require(MW['page_count']==1))
case('MARKETWIDE','intersection deliberately false',lambda: require(MW['audited_universe_intersection_performed'] is False))
case('MARKETWIDE','query has no symbol',lambda: require('symbol' not in market_calls[0]))

bad={'data':[dict(sample_row, broadcast_Date='18-May-2026 16:01:12')]}
case('FAIL_CLOSED','invalid chronology rejected row',lambda: require(normalize_response(bad)['rejected_row_count']==1))
case('FAIL_CLOSED','no silent conversion of rejected row',lambda: require(normalize_response(bad)['normalized_event_count']==0))

failed=[x for x in RESULTS if x['status']!='PASS']
print({'tests':len(RESULTS),'passed':len(RESULTS)-len(failed),'failed':len(failed),'failures':failed})
if failed: raise SystemExit(1)
