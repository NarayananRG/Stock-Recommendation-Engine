from __future__ import annotations
import json,sys
from pathlib import Path
REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))
from fundamental_research_v2_phase2a.market_outcome_evaluation import discover_official_price_history,compute_forward_outcomes,summarize_outcomes

PROFILES=ROOT/"results"/"fundamental_v2_phase2a7_risk_events"/"risk_event_profiles.jsonl"
P7=ROOT/"results"/"fundamental_v2_phase2a7_risk_events"/"summary.json"
OUT=ROOT/"results"/"fundamental_v2_phase2a8_market_outcomes"
OUT.mkdir(parents=True,exist_ok=True)

def main():
    p7=json.loads(P7.read_text(encoding='utf-8'))
    if p7.get('status')!='PHASE2A7_RISK_EVENT_BUILDER_PASS':
        raise RuntimeError('PHASE2A7_NOT_CLOSED')
    profiles=[json.loads(x) for x in PROFILES.read_text(encoding='utf-8').splitlines() if x.strip()]
    targets={x.get('symbol') for x in profiles}
    prices,discovery=discover_official_price_history(REPO,targets)
    (OUT/'official_price_discovery.json').write_text(json.dumps(discovery,indent=2,sort_keys=True),encoding='utf-8')
    if not prices:
        raise RuntimeError('OFFICIAL_PRICE_HISTORY_NOT_FOUND_OR_NOT_RECOGNIZED:SEE_official_price_discovery.json')
    outcomes,matched=compute_forward_outcomes(profiles,prices)
    with (OUT/'event_market_outcomes.jsonl').open('w',encoding='utf-8') as h:
        for row in outcomes: h.write(json.dumps(row,sort_keys=True)+'\n')
    matched_rate=matched/len(profiles) if profiles else 0.0
    summary={
      'artifact_type':'FUNDAMENTAL_RESEARCH_V2_PHASE2A8_MARKET_OUTCOME_SUMMARY_V1',
      'authority':'SHADOW_ONLY',
      'status':'PHASE2A8_MARKET_OUTCOME_EVALUATION_PASS',
      'risk_event_profile_count':len(profiles),
      'matched_event_count':matched,
      'matched_event_rate':matched_rate,
      'outcome_row_count':len(outcomes),
      'horizons_sessions':[21,63,126],
      'cohort_horizon_summary':summarize_outcomes(outcomes),
      'official_price_discovery':{
        'accepted_file_count':discovery['accepted_file_count'],
        'loaded_symbol_count':discovery['loaded_symbol_count'],
        'loaded_price_row_count':discovery['loaded_price_row_count'],
        'equal_priority_conflict_count':discovery['equal_priority_conflict_count'],
        'yfinance_used':False,'network_used':False
      },
      'market_labels_created':False,
      'production_model_changed':False,
      'model_training_started':False,
      'next_gate':'PHASE2A9_INDEPENDENT_VALIDATION_AND_FINAL_DECISION'
    }
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True),encoding='utf-8')
    print(json.dumps(summary,indent=2,sort_keys=True))
    return 0
if __name__=='__main__': raise SystemExit(main())
