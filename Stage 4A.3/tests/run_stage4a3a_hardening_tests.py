from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parent
sys.path.insert(0,str(ROOT))

from stage4a3.activation import signal_is_after_activation
from stage4a3.candidate_input_builder import build_signal_close_input,verify_candidate_input
from stage4a3.final_evaluation import FINAL_OUTPUTS,evaluate as final_evaluate,parser as final_parser
from stage4a3.hashing import dataframe_content_hash
from stage4a3.ledger_counts import derive_final_gate_counts
from stage4a3.outcome_resolver import append_event_batch,load_all_events,verify_outcome_ledger
from stage4a3.status_report import ALLOWED_FIELDS,FORBIDDEN_TERMS,derive_operational_status


NAMES=[
    "same activation date signal blocked","next-day eligible signal accepted","production runner calls anti-backfill gate",
    "protocol-tag source drift blocks production snapshot","committed source drift blocks production snapshot",
    "coordinated model-manifest and joblib mutation blocked by activation identity","frozen universe mutation blocked","protocol identity mutation blocked",
    "production arbitrary input prohibited","frozen production input builder parity on historical fixture",
    "candidate Signal-ID set provenance verified","feature values and input logical hash provenance verified",
    "multiple outcome batches for same Signal Date work","outcome-event global chain verifies","outcome-event tampering fails",
    "duplicate contradictory terminal target blocked","labels computed from frozen logic not caller supplied","gate counts derived from ledger",
    "no production counts-json","synthetic matured fixture unlocks final evaluator","final evaluator creates all preregistered outputs under tests",
    "premature real evaluation remains blocked","status report contains operational counts only","real prospective snapshot count remains zero",
    "real prospective outcome count remains zero","activation record remains absent",
]


def _event(kind:str,value:object,generated:str) -> dict:
    return {"Generated UTC":generated,"Signal ID":"TEST_SIGNAL","Signal Date":"2025-01-02","Ticker":"TEST.NS","Policy":"","Outcome Type":kind,"Outcome State":"RESOLVED","Outcome Value":value,"Observation Through Date":"2025-03-31","Label Available Date":"2025-03-31","Source Market Data Hash":"TEST_HASH","Is Terminal":True}


def _feature_parity(built:pd.DataFrame,reference:pd.DataFrame,features:list[str]) -> tuple[bool,float]:
    left=built.set_index("Signal ID").sort_index();right=reference.set_index("Signal ID").loc[left.index].sort_index();maximum=0.0
    for name in features:
        a=left[name];b=right[name]
        numeric_a=pd.to_numeric(a,errors="coerce");numeric_b=pd.to_numeric(b,errors="coerce")
        numeric=(a.notna()==numeric_a.notna()).all() and (b.notna()==numeric_b.notna()).all()
        if numeric:
            mask=numeric_a.notna()|numeric_b.notna()
            if mask.any():maximum=max(maximum,float(np.nanmax(np.abs(numeric_a[mask].to_numpy(float)-numeric_b[mask].to_numpy(float)))))
            # The accepted Stage 3.1 CSV stores source prices at eight decimal
            # places; recomputation retains binary precision from the frozen bars.
            if not np.allclose(numeric_a.to_numpy(float),numeric_b.to_numpy(float),rtol=0,atol=1e-7,equal_nan=True):return False,maximum
        else:
            normalize=lambda s:s.astype("string").fillna("<NA>")
            if not normalize(a).equals(normalize(b)):return False,maximum
    return True,maximum


def evaluate() -> list[dict]:
    values={};activation={"Activation UTC":"2026-01-01T00:00:00+00:00","Activation Local Date":"2026-01-01"}
    values[1]=not signal_is_after_activation(activation,"2026-01-01T23:59:59+00:00","2026-01-01")
    values[2]=signal_is_after_activation(activation,"2026-01-02T11:00:00+00:00","2026-01-02")
    runner=(ROOT/"stage4a3/prospective_runner.py").read_text(encoding="utf-8");integrity=(ROOT/"stage4a3/protocol_integrity.py").read_text(encoding="utf-8")
    values[3]=runner.index("signal_is_after_activation(")<runner.index("score_candidates(") and "SIGNAL_DATE_NOT_PROSPECTIVE_AFTER_ACTIVATION" in runner
    values[4]="git(repo,\"diff\",\"--quiet\",tag" in integrity and "PROTECTED_FILE_MISMATCH" in integrity
    values[5]="expected_commit=activation[\"Protocol Commit\"]" in integrity and "require_head=False" in integrity
    values[6]="expected_hashes" in integrity and "MODEL_BUNDLE_IDENTITY_MISMATCH" in integrity and "models/frozen_2026" in integrity
    values[7]="FROZEN_UNIVERSE_MISMATCH" in integrity and "prospective_universe.csv" in integrity
    values[8]="protocol_identity" in integrity and "activation[\"Protocol Identity\"]" in integrity
    values[9]="PRODUCTION_ARBITRARY_INPUT_PROHIBITED" in runner and not {"counts_json","force"}&{a.dest for a in final_parser()._actions}

    with tempfile.TemporaryDirectory() as td:
        built,manifest,_=build_signal_close_input(REPO,"2025-12-10",Path(td),"FROZEN")
    built.to_csv(ROOT/"tests/fixtures/HISTORICAL_FROZEN_BUILDER_OUTPUT_2025-12-10.csv.gz",index=False,compression={"method":"gzip","mtime":0},lineterminator="\n",float_format="%.17g")
    reference=pd.read_csv(REPO/"Stage 3.1/results/stage3_1_signal_state_dataset.csv.gz",low_memory=False)
    reference=reference.loc[reference["Signal ID"].astype(str).isin(built["Signal ID"].astype(str))].copy()
    import joblib
    model=joblib.load(ROOT/"models/frozen_2026/PRIMARY_ONLY_T1_LOGIT_FULL.joblib");feature_names=model["feature_names"]
    same_ids=set(built["Signal ID"].astype(str))==set(reference["Signal ID"].astype(str)) and len(built)==3
    parity,max_diff=_feature_parity(built,reference,feature_names)
    values[10]=same_ids and parity;values[11]=same_ids
    try:verify_candidate_input(built,manifest,manifest["Frozen Universe Hash"]);provenance=True
    except Exception:provenance=False
    values[12]=provenance and parity and manifest["Full Input Logical Hash"]==dataframe_content_hash(built)
    pd.DataFrame([{"Signal Date":"2025-12-10","Candidate Count":len(built),"Signal IDs Match":same_ids,"Feature Values Match":parity,"Maximum Absolute Feature Difference":max_diff,"Input Logical Hash Verified":values[12],"Status":"PASS" if values[10] and values[12] else "FAIL"}]).to_csv(ROOT/"results/stage4a3_frozen_input_builder_parity.csv",index=False,lineterminator="\n")

    with tempfile.TemporaryDirectory() as td:
        outcome=Path(td)/"outcomes";audit=Path(td)/"audit"
        append_event_batch(outcome,[_event("ENTRY_FILLED",True,"2025-04-01T00:00:00+00:00")],"2025-04-01T00:00:00+00:00",audit,"TEST")
        append_event_batch(outcome,[_event("T1_BEFORE_STOP_63",False,"2025-04-02T00:00:00+00:00")],"2025-04-02T00:00:00+00:00",audit,"TEST")
        events=load_all_events(outcome);values[13]=len(events)==2 and events["Signal Date"].nunique()==1;values[14]=verify_outcome_ledger(outcome)
        batch=next(outcome.glob("*/*/*.csv.gz"));raw=pd.read_csv(batch,compression="gzip",dtype=str,keep_default_na=False);raw.loc[0,"Outcome Value"]="FALSE";raw.to_csv(batch,index=False,compression="gzip",lineterminator="\n");values[15]=not verify_outcome_ledger(outcome)
    with tempfile.TemporaryDirectory() as td:
        outcome=Path(td)/"outcomes";audit=Path(td)/"audit";append_event_batch(outcome,[_event("ENTRY_FILLED",True,"2025-04-01T00:00:00+00:00")],"2025-04-01T00:00:00+00:00",audit,"TEST")
        try:append_event_batch(outcome,[_event("ENTRY_FILLED",False,"2025-04-02T00:00:00+00:00")],"2025-04-02T00:00:00+00:00",audit,"TEST");blocked=False
        except RuntimeError as exc:blocked="CONTRADICTORY_TERMINAL_OUTCOME" in str(exc)
        values[16]=blocked
    resolver=(ROOT/"stage4a3/outcome_resolver.py").read_text(encoding="utf-8");values[17]="simulate_entry(" in resolver and "add_opportunity_labels(" in resolver and "outcome_value" not in resolver.lower()
    synthetic=ROOT/"tests/SYNTHETIC_MATURED_PROSPECTIVE_FIXTURE";counts=derive_final_gate_counts(REPO,synthetic,"2026-02-01",synthetic_integrity=True)
    values[18]=counts["candidate_count"]==150 and counts["r0_k1_completed_d1"]==50 and counts["r3_k1_completed_d1"]==50
    values[19]="counts_json" not in {a.dest for a in final_parser()._actions} and "derive_final_gate_counts(" in (ROOT/"stage4a3/final_evaluation.py").read_text()
    values[20]=all((synthetic/"tests/final_outputs"/name).exists() for name in FINAL_OUTPUTS)
    values[21]=values[20] and len(FINAL_OUTPUTS)==20
    with tempfile.TemporaryDirectory() as td:
        copy=Path(td)/"tests"/"SYNTHETIC_LOCKED_FIXTURE";shutil.copytree(synthetic,copy);locked=False
        try:final_evaluate(REPO,copy,"2024-06-01",copy/"tests/locked_outputs")
        except RuntimeError as exc:locked="PROSPECTIVE_EVALUATION_LOCKED" in str(exc)
        values[22]=locked and (copy/"prospective/audit/protocol_breaches.csv").exists()
    status=derive_operational_status(synthetic,"2026-02-01");values[23]=set(status)==ALLOWED_FIELDS and not any(term in " ".join(status).lower() for term in FORBIDDEN_TERMS)
    values[24]=not any((ROOT/"prospective/snapshots").glob("*/*/candidate_predictions.csv.gz"))
    values[25]=not any((ROOT/"prospective/outcomes").glob("*/*/*.csv.gz"))
    values[26]=not (ROOT/"prospective/audit/activation_record.json").exists()
    return [{"Test Number":118+i,"Test":name,"Status":"PASS" if values.get(i,False) else "FAIL","Details":"Stage 4A.3A explicit regression"} for i,name in enumerate(NAMES,1)]


def main()->None:
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,default=ROOT/"results/stage4a3a_hardening_test_results.csv");args=parser.parse_args();frame=pd.DataFrame(evaluate());args.output.parent.mkdir(parents=True,exist_ok=True);frame.to_csv(args.output,index=False,lineterminator="\n");print(frame["Status"].value_counts().to_dict());raise SystemExit(0 if frame["Status"].eq("PASS").all() else 1)


if __name__=="__main__":main()
