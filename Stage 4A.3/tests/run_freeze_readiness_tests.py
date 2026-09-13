from __future__ import annotations

import io,json,sys,tempfile
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;sys.path.insert(0,str(ROOT))
from stage4a3.final_evaluation import conditional_t1_outcomes,filter_as_of_inputs,filter_market_as_of,joint_t1_outcomes
from stage4a3.final_market_data import acquire_and_archive,archive_market_frames
from stage4a3.freeze_readiness import parity_table


def event(signal:str,kind:str,value:bool,date:str,policy:str="")->dict:
    return {"Signal ID":signal,"Signal Date":"2026-01-01","Policy":policy,"Outcome Type":kind,"Outcome Value":value,"Label Available Date":date,"Is Terminal":True}


def evaluate()->pd.DataFrame:
    rows=[]
    def check(name:str,value:bool,details:str="")->None:rows.append({"Test":name,"Status":"PASS" if value else "FAIL","Details":details})
    events=pd.DataFrame([
        event("NO_FILL","ENTRY_FILLED",False,"2026-01-03"),
        event("FILL_T1_TRUE","ENTRY_FILLED",True,"2026-01-03"),event("FILL_T1_TRUE","T1_BEFORE_STOP_63",True,"2026-02-01"),
        event("FILL_T1_FALSE","ENTRY_FILLED",True,"2026-01-03"),event("FILL_T1_FALSE","T1_BEFORE_STOP_63",False,"2026-02-02"),
        event("FILL_UNRESOLVED","ENTRY_FILLED",True,"2026-01-03"),
        event("ORPHAN_T1","T1_BEFORE_STOP_63",True,"2026-02-03"),
        event("POLICY_T1","ENTRY_FILLED",False,"2026-01-03","R3_K1"),
    ])
    joint=joint_t1_outcomes(events).set_index("Signal ID");conditional=conditional_t1_outcomes(events).set_index("Signal ID")
    check("JOINT no-fill is terminal zero",bool(joint.loc["NO_FILL","Observed"]==False))
    check("JOINT no-fill uses entry label date",joint.loc["NO_FILL","Label Available Date"]=="2026-01-03")
    check("JOINT filled resolved T1 true",bool(joint.loc["FILL_T1_TRUE","Observed"]==True))
    check("JOINT filled resolved T1 false",bool(joint.loc["FILL_T1_FALSE","Observed"]==False))
    check("JOINT filled unresolved excluded","FILL_UNRESOLVED" not in joint.index)
    check("JOINT policy events excluded","POLICY_T1" not in joint.index)
    check("conditional T1 contains only filled resolved",set(conditional.index)=={"FILL_T1_TRUE","FILL_T1_FALSE"})
    predictions=pd.DataFrame([{"Signal ID":"A","Signal Date":"2026-01-01"},{"Signal ID":"B","Signal Date":"2026-02-01"}]);features=pd.DataFrame([{"Signal ID":"A","x":1},{"Signal ID":"B","x":999}]);ledger=pd.DataFrame([event("A","ENTRY_FILLED",True,"2026-01-02"),event("A","T1_BEFORE_STOP_63",True,"2026-02-01")])
    p,f,e=filter_as_of_inputs(predictions,features,ledger,"2026-01-15")
    check("as-of filters later prediction and paired feature",p["Signal ID"].tolist()==["A"] and f["Signal ID"].tolist()==["A"])
    check("as-of filters later outcome",e["Outcome Type"].tolist()==["ENTRY_FILLED"])
    p0,f0,e0=filter_as_of_inputs(predictions.iloc[[0]],features.iloc[[0]],ledger.iloc[[0]],"2026-01-15")
    check("later snapshots and outcomes have zero earlier-as-of effect",p.equals(p0) and f.equals(f0) and e.equals(e0))
    market={"A":pd.DataFrame({"Close":[1.,2.]},index=pd.to_datetime(["2026-01-15","2026-02-01"]))};filtered_market=filter_market_as_of(market,"2026-01-15")
    check("market rows strictly isolated at as-of",filtered_market["A"].index.tolist()==[pd.Timestamp("2026-01-15")])
    reference=pd.DataFrame({"Policy":["R0_K1"],"Signal ID":["A"],"Exit Reason":["STOP"],"Value":[100000.123456]});serialized=pd.read_csv(io.StringIO(reference.to_csv(index=False,float_format="%.12g")))
    table=parity_table(reference,serialized,["Policy","Signal ID"],["Exit Reason"],["Value"],"synthetic")
    check("canonical reference serialization is explicit",table["Status"].isin(["PASS_EXACT","PASS_SERIALIZATION_ONLY"]).all() and table["Behavioral Match"].all())
    serialization_only=parity_table(reference.assign(Value=reference["Value"]+4.9e-7),serialized,["Policy","Signal ID"],["Exit Reason"],["Value"],"synthetic")
    check("six-decimal canonical delta accepts serialization only",serialization_only["Status"].eq("PASS_SERIALIZATION_ONLY").any() and serialization_only["Behavioral Match"].all())
    changed=reference.assign(**{"Exit Reason":["TARGET"]});behavior=parity_table(changed,serialized,["Policy","Signal ID"],["Exit Reason"],["Value"],"synthetic")
    check("discrete replay mismatch is behavioral failure",behavior["Status"].eq("FAIL_BEHAVIORAL").any())
    unexplained=reference.assign(Value=reference["Value"]+1e-3);numeric=parity_table(unexplained,serialized,["Policy","Signal ID"],["Exit Reason"],["Value"],"synthetic")
    check("numeric difference surviving serialization fails",numeric["Status"].eq("FAIL_NUMERIC_UNEXPLAINED").any())
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);stage=root/"stage";stage.mkdir();pd.DataFrame({"Ticker":["AAA.NS"]}).to_csv(stage/"prospective_universe.csv",index=False)
        parent=root/"archive";dates=pd.to_datetime(["2026-01-01","2026-01-02"]);frame=pd.DataFrame({"Open":[1,2],"High":[2,3],"Low":[.5,1.5],"Close":[1.5,2.5],"Volume":[10,20]},index=dates)
        archive_market_frames({"AAA.NS":frame,"^NSEI":frame},parent/"final_market_data","2026-01-02","TEST","2026-01-03T00:00:00Z")
        loaded,manifest=acquire_and_archive(root,stage,"2026-01-02",parent,"LATER")
        check("matching archive retry reuses verified bytes",set(loaded)=={"AAA.NS","^NSEI"} and manifest["downloaded_utc"]=="2026-01-03T00:00:00Z")
        try:acquire_and_archive(root,stage,"2026-01-03",parent,"LATER");blocked=False
        except RuntimeError as exc:blocked="AS_OF_MISMATCH" in str(exc)
        check("archive retry mismatch stops without overwrite",blocked)
        pd.DataFrame({"Ticker":["BBB.NS"]}).to_csv(stage/"prospective_universe.csv",index=False)
        try:acquire_and_archive(root,stage,"2026-01-02",parent,"LATER");universe_blocked=False
        except RuntimeError as exc:universe_blocked="UNIVERSE_MISMATCH" in str(exc)
        check("archive retry conflicting universe stops",universe_blocked)
        pd.DataFrame({"Ticker":["AAA.NS"]}).to_csv(stage/"prospective_universe.csv",index=False);target=parent/"final_market_data/AAA.NS.csv.gz";payload=bytearray(target.read_bytes());payload[-1]^=1;target.write_bytes(payload)
        try:acquire_and_archive(root,stage,"2026-01-02",parent,"LATER");hash_blocked=False
        except RuntimeError as exc:hash_blocked="TAMPERED" in str(exc) or "HASH" in str(exc)
        check("archive retry hash conflict stops",hash_blocked)
    report=(ROOT/"Stage4A3_Delivery_Report.md").read_text(encoding="utf-8")
    check("stale protocol identity removed","S4A3_PROTOCOL_b4b02f1234e17499" not in report)
    manifest=json.loads((ROOT/"models/frozen_2026/model_bundle_manifest.json").read_text(encoding="utf-8"))
    check("frozen model bundle unchanged",manifest["FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH"]=="4631eb8a1d0b34212252df3b1aae180f64ec98ba5e7955a84729df0a471c62da")
    check("real snapshots remain empty",not any((ROOT/"prospective/snapshots").glob("*/*/candidate_predictions.csv.gz")))
    check("real outcomes remain empty",not any((ROOT/"prospective/outcomes").glob("*/*/*.csv.gz")))
    check("activation remains absent",not (ROOT/"prospective/audit/activation_record.json").exists())
    return pd.DataFrame(rows)


if __name__=="__main__":
    result=evaluate();target=ROOT/"results/stage4a3_freeze_readiness_test_results.csv";result.insert(0,"Test Number",range(165,165+len(result)));result.to_csv(target,index=False,lineterminator="\n");print(result["Status"].value_counts().to_dict());raise SystemExit(0 if result["Status"].eq("PASS").all() else 1)
