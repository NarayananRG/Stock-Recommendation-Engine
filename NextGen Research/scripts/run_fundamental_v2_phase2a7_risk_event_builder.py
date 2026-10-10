from __future__ import annotations
import json,sys
from pathlib import Path
REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))
from fundamental_research_v2_phase2a.risk_event_builder import build_risk_profiles,summarize_profiles

EVENTS=ROOT/"results"/"fundamental_v2_phase2a5_derived_event_transforms"/"derived_events.jsonl"
SEM=ROOT/"results"/"fundamental_v2_phase2a6_semantic_interpretation"/"summary.json"
OUT=ROOT/"results"/"fundamental_v2_phase2a7_risk_events"
OUT.mkdir(parents=True,exist_ok=True)

def main():
    sem=json.loads(SEM.read_text(encoding='utf-8'))
    if sem.get('status')!='PHASE2A6_SEMANTIC_COVERAGE_AUDIT_PASS':
        raise RuntimeError('PHASE2A6_NOT_CLOSED')
    events=[json.loads(x) for x in EVENTS.read_text(encoding='utf-8').splitlines() if x.strip()]
    if len(events)!=17253:
        raise RuntimeError(f'PHASE2A7_DERIVED_EVENT_COUNT_MISMATCH:{len(events)}')
    profiles=build_risk_profiles(events)
    if not profiles:
        raise RuntimeError('PHASE2A7_NO_EVENT_PROFILES')
    with (OUT/'risk_event_profiles.jsonl').open('w',encoding='utf-8') as h:
        for row in profiles: h.write(json.dumps(row,sort_keys=True)+'\n')
    summary=summarize_profiles(profiles)
    summary.update({
      'status':'PHASE2A7_RISK_EVENT_BUILDER_PASS',
      'next_gate':'PHASE2A8_MARKET_OUTCOME_EVALUATION'
    })
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True),encoding='utf-8')
    print(json.dumps(summary,indent=2,sort_keys=True))
    return 0
if __name__=='__main__': raise SystemExit(main())
