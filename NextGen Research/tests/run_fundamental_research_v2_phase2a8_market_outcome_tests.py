from __future__ import annotations
import csv,sys,tempfile
from datetime import date,timedelta
from pathlib import Path
REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))
from fundamental_research_v2_phase2a.market_outcome_evaluation import discover_official_price_history,compute_forward_outcomes

RESULTS=[]
def req(v,m='assertion failed'):
    if not v: raise AssertionError(m)
def case(n,fn):
    try: fn(); s,d='PASS',''
    except Exception as exc: s,d='FAIL',f'{type(exc).__name__}: {exc}'
    RESULTS.append({'test':n,'status':s,'detail':d})

with tempfile.TemporaryDirectory() as td:
    root=Path(td)
    off=root/'official_nse_complete_stock_history.csv'
    yf=root/'yfinance_history.csv'
    rows=[]
    start=date(2026,1,1)
    for i in range(150):
        rows.append({'symbol':'ABC','date':(start+timedelta(days=i)).isoformat(),'close':100+i})
    for path in [off,yf]:
        with path.open('w',newline='',encoding='utf-8') as h:
            w=csv.DictWriter(h,fieldnames=['symbol','date','close']);w.writeheader();w.writerows(rows)
    prices,report=discover_official_price_history(root,{'ABC'})
    case('official file loaded',lambda: req('ABC' in prices))
    case('yfinance path rejected by discovery',lambda: req(all('yfinance' not in x['path'].lower() for x in report['accepted_files'])))
    case('network unused',lambda: req(report['network_used'] is False))
    profile={
      'symbol':'ABC','reporting_basis':'CONSOLIDATED','current_event_id':'E1',
      'current_quarter_end':'2026-03-31','effective_availability_ts':'2026-01-10T12:00:00+05:30',
      'event_profile':'PURE_DETERIORATION','strong_deterioration_transition':False,
      'strong_improvement_transition':False
    }
    outcomes,matched=compute_forward_outcomes([profile],prices)
    case('one event matched',lambda: req(matched==1))
    case('three fixed horizons emitted',lambda: req(len(outcomes)==3))
    h21=next(x for x in outcomes if x['horizon_sessions']==21)
    case('entry strictly after filing date',lambda: req(h21['entry_date']>'2026-01-10'))
    case('21 session mature',lambda: req(h21['mature'] is True and h21['forward_return'] is not None))

failed=[x for x in RESULTS if x['status']!='PASS']
print({'tests':len(RESULTS),'passed':len(RESULTS)-len(failed),'failed':len(failed),'failures':failed})
if failed: raise SystemExit(1)
