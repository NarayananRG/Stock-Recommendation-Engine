"""Test-only end-to-end exercise of the frozen label and D1 adapters."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;sys.path.insert(0,str(ROOT))
from stage4a3.outcome_resolver import append_event_batch,compute_frozen_d1_policy_events,compute_frozen_label_events,verify_outcome_ledger

TARGET=ROOT/"tests/SYNTHETIC_OUTCOME_RESOLUTION_FIXTURE"
if TARGET.exists():raise RuntimeError("Synthetic outcome fixture already exists; use a fresh test workspace")
snapshot=ROOT/"tests/dry_run_hardened/snapshots/2025/2025-12-10";data=REPO/"Stage 2.2.2 Final/stage2_2_1/data/frozen";frames={}
for path in data.glob("*.csv"):
    frame=pd.read_csv(path);frame["Date"]=pd.to_datetime(frame["Date"]);frame=frame.set_index("Date");frames["^NSEI" if path.stem=="INDEX_NSEI" else path.stem]=frame
predictions=pd.read_csv(snapshot/"candidate_predictions.csv.gz");features=pd.read_csv(snapshot/"feature_snapshot.csv.gz");generated="2026-08-29T00:00:00+00:00"
labels=compute_frozen_label_events(REPO,snapshot,frames,"2026-08-28",generated,"FROZEN_TEST_MARKET")
d1=compute_frozen_d1_policy_events(REPO,predictions,features,frames,"2026-08-28",generated,"FROZEN_TEST_MARKET",include_random_controls=False,include_d0=True,policies=["R0_K1","R3_K1"])
outcomes=TARGET/"outcomes";audit=TARGET/"audit"
append_event_batch(outcomes,labels,generated,audit,"SYNTHETIC_OUTCOME_RESOLUTION_FIXTURE")
append_event_batch(outcomes,d1,"2026-08-29T00:00:01+00:00",audit,"SYNTHETIC_OUTCOME_RESOLUTION_FIXTURE")
result={"Fixture":"SYNTHETIC_OUTCOME_RESOLUTION_FIXTURE","Stage 3.1 Computed Events":len(labels),"Stage 2B.1 Computed Events":len(d1),"Policies":["R0_K1","R3_K1","R0_K1_D0","R3_K1_D0"],"Global Outcome Chain Valid":verify_outcome_ledger(outcomes),"Production Outcomes Written":0}
(TARGET/"result.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8");print(json.dumps(result,indent=2))
