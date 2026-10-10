from __future__ import annotations
import json,sys
from pathlib import Path
REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))
from fundamental_research_v2_phase2a.independent_validation import final_decision

OUTCOMES=ROOT/"results"/"fundamental_v2_phase2a8_market_outcomes"/"event_market_outcomes.jsonl"
P8=ROOT/"results"/"fundamental_v2_phase2a8_market_outcomes"/"summary.json"
OUT=ROOT/"results"/"fundamental_v2_phase2a9_final_validation"
OUT.mkdir(parents=True,exist_ok=True)

def main():
    p8=json.loads(P8.read_text(encoding='utf-8'))
    if p8.get('status')!='PHASE2A8_MARKET_OUTCOME_EVALUATION_PASS':
        raise RuntimeError('PHASE2A8_NOT_CLOSED')
    outcomes=[json.loads(x) for x in OUTCOMES.read_text(encoding='utf-8').splitlines() if x.strip()]
    decision=final_decision(outcomes,float(p8.get('matched_event_rate') or 0.0))
    decision.update({
      'status':'PHASE2A9_INDEPENDENT_VALIDATION_COMPLETE',
      'source_market_outcome_rows':len(outcomes),
      'official_price_only':True,
      'yfinance_used':False,
      'network_used':False
    })
    (OUT/'fundamental_v2_final_decision.json').write_text(json.dumps(decision,indent=2,sort_keys=True),encoding='utf-8')
    print(json.dumps(decision,indent=2,sort_keys=True))
    return 0
if __name__=='__main__': raise SystemExit(main())
