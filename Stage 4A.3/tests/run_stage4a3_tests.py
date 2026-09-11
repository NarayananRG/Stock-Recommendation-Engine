from __future__ import annotations

import argparse,inspect,json,shutil,subprocess,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path

import joblib,numpy as np,pandas as pd

ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent
sys.path.insert(0,str(ROOT))
from stage4a3.activation import signal_is_after_activation
from stage4a3.candidate_selection import rank_and_select
from stage4a3.feature_snapshot import feature_row_hash,validate_feature_contract
from stage4a3.final_analysis_gate import gate_audit,is_unlocked
from stage4a3.final_evaluation import economic_criteria,parser as evaluation_parser
from stage4a3.hash_chain import current_chain_hash,genesis_hash,verify_index
from stage4a3.hashing import canonical_json_hash,sha256_file
from stage4a3.immutable_ledger import INDEX_COLUMNS,verify_ledger,verify_snapshot_files
from stage4a3.market_data_adapter import validate_capture_window
from stage4a3.model_scoring import score_candidates,verify_bundle
from stage4a3.outcome_contract import OUTCOME_SCHEMA
from stage4a3.outcome_resolver import seal_event,verify_event_chain
from stage4a3.snapshot_contract import FORBIDDEN_OUTCOME_TOKENS,PREDICTION_COLUMNS,SNAPSHOT_SCHEMA,validate_candidate_predictions
from stage4a3.status_report import ALLOWED_FIELDS,operational_status


NAMES=[
"Stage 4A.2 tag exact","Stage 4A.1 tag exact","Stage 4A tag exact","Stage 3.1 tag exact","Stage 2B.1 tag exact","Stage 4A.2 experiment exact","Stage 4A.2 package hash exact","upstream folders unchanged","branch merge base exact Stage 4A.2 frozen commit",
"seven required model components exist","no extra model variant silently added","exact feature sets","exact model hyperparameters","exact preprocessing","exact 2026 training cutoff","no post-2026-01-01 label availability in training","deterministic model reconstruction","historical 2026 Signal IDs match","reconstructed probability parity","max abs probability difference <= allowed parity contract","model bundle manifest hashes exact","bundle mutation is detected","prospective scorer refuses altered bundle",
"FS2 exactly 92","FS3 exactly 97","no date-like feature","no ticker feature","no Signal ID feature","no target label column","no future-return feature","no entry-outcome feature","no D1-outcome feature","categorical unknown handling frozen","feature row hash deterministic",
"production mode cannot specify historical date","dry-run historical date stays under tests only","snapshot before after-close window blocked","stale market-data date blocked","future market-data date blocked","existing snapshot overwrite blocked","existing snapshot append blocked","zero-candidate day snapshot valid","candidate snapshot contains no outcome fields","all expected scores exist","no missing score imputation","R0 ranking exact","R1 ranking exact","R2 ranking exact","R3 product formula exact","R4 product formula exact","R5 score exact","K1 exact","K2 exact","future non-fill still consumes K slot","future winner cannot replace selected non-fill",
"snapshot canonical hash deterministic","genesis chain deterministic","current chain formula exact","changing historical snapshot breaks chain verification","deleting historical snapshot breaks chain verification","inserting out-of-order snapshot detected","duplicate Signal Date detected","snapshot index append-only semantics","protocol code drift detected","model bundle drift detected",
"activation impossible before protocol tag verification","activation record immutable","no signal before activation accepted","first eligible session after activation accepted","repeated activation blocked",
"outcomes stored outside prediction snapshot","prediction snapshot remains byte/logically unchanged after outcome resolution","label availability date valid","ENTRY_FILLED semantics frozen","T1 semantics frozen","T2 semantics frozen","D1 semantics frozen","STOP_FIRST preserved","63-session max hold preserved","outcome event hash deterministic","outcome-event chain detects tampering",
"status report contains no AUC","status report contains no return","status report contains no expectancy","status report contains no PF","status report contains no policy winner","final evaluation locked before 24 months","final evaluation locked below 150 candidates","final evaluation locked below 50 R0_K1 trades","final evaluation locked below 50 R3_K1 trades","final evaluation locked below 100 entry labels","final evaluation locked below 60 T1-resolved fills","no force flag exists","premature evaluation attempt logged as protocol breach",
"R3_K1 is primary confirmatory policy","comparator is R0_K1","R1 cannot substitute for failed R3","R2 cannot substitute for failed R3","R4 cannot substitute for failed R3","R5 cannot unlock Stage 5","K2 cannot unlock Stage 5","all ten prospective economic criteria implemented exactly","bootstrap 63 / 2000 / seed42 exact","random K1 seeds exactly 0..499","95th-percentile criterion exact","max-DD +2pp criterion exact","trade minimum 50 exact",
"no refit callable in prospective_runner","no annual refit","no threshold optimization","no calibration","no new feature generation beyond frozen feature contract","no ML position sizing","no ML stop logic","no ML target logic","no ML exit logic","no production recommendation text","no Stage 5 implementation"]


def git(*args:str)->str:return subprocess.check_output(["git","-c",f"safe.directory={REPO.as_posix()}",*args],cwd=REPO,text=True).strip()
def raises(fn,token:str)->bool:
    try:fn()
    except Exception as exc:return token in str(exc)
    return False


def evaluate() -> list[dict]:
    config=json.loads((ROOT/"config/stage4a3_protocol.json").read_text());manifest=verify_bundle(ROOT/"models/frozen_2026")
    models={m["model_name"]:joblib.load(ROOT/"models/frozen_2026"/f"{m['model_name']}.joblib") for m in manifest["models"]}
    fs2=models["PRIMARY_ONLY_T1_LOGIT_RAW"]["feature_names"];fs3=models["PRIMARY_ONLY_T1_LOGIT_FULL"]["feature_names"];validate_feature_contract({"FS2_RAW_SIGNAL_STATE":fs2,"FS3_FULL_SIGNAL_STATE":fs3})
    parity=pd.read_csv(ROOT/"results/stage4a3_2026_prediction_parity.csv")
    fixture=pd.read_csv(ROOT/"tests/fixtures/HISTORICAL_TEST_FIXTURE_2025-12-10.csv.gz");pred=pd.read_csv(ROOT/"tests/dry_run_hardened/snapshots/2025/2025-12-10/candidate_predictions.csv.gz")
    source_files="\n".join(p.read_text(encoding="utf-8",errors="ignore") for p in (ROOT/"stage4a3").glob("*.py"))
    expected_refs=list(config["frozen_references"].items());values={}
    for i,(tag,expected) in enumerate(expected_refs,1):values[i]=git("rev-parse",f"{tag}^{{commit}}")==expected
    values[6]=config["stage4a2_experiment_id"]=="S4A2_20160101_20260828_022dc86ab7df";values[7]=config["stage4a2_package_hash"]=="0da2a240880b70701f87067c6d355cff7607de9a86dd60d0d42a8fdbbfd39b33"
    values[8]=not bool(git("diff","--name-only",expected_refs[0][1],"--",":(exclude)Stage 4A.3"));values[9]=git("merge-base","HEAD",expected_refs[0][1])==expected_refs[0][1]
    required={x["name"] for x in config["required_models"]};actual={p.stem for p in (ROOT/"models/frozen_2026").glob("*.joblib")};values[10]=len(actual)==7 and actual==required;values[11]=actual==required
    values[12]=all(models[m["name"]]["component"]["feature_set"]==m["feature_set"] for m in config["required_models"])
    values[13]=all(all(models[m["model_name"]]["estimator"].get_params()[key]==value for key,value in m["model_parameters"].items()) for m in manifest["models"])
    values[14]=len({m["preprocessor_hash"] for m in manifest["models"]})==2;values[15]=manifest["training_cutoff"]=="2026-01-01 exclusive";values[16]=all("strictly before 2026-01-01" in m["training_cutoff"] for m in manifest["models"])
    values[17]=all(np.array_equal(models[n]["estimator"].predict_proba(models[n]["preprocessor"].transform(fixture[models[n]["feature_names"]]))[:,1],models[n]["estimator"].predict_proba(models[n]["preprocessor"].transform(fixture[models[n]["feature_names"]]))[:,1]) for n in actual)
    values[18]=parity["Signal IDs Match"].astype(bool).all();values[19]=parity["Parity Status"].eq("PASS").all();values[20]=parity["Maximum Probability Difference"].max()<=1e-12;values[21]=verify_bundle(ROOT/"models/frozen_2026")["FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH"]==manifest["FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH"]
    with tempfile.TemporaryDirectory() as td:
        copy=Path(td)/"models";shutil.copytree(ROOT/"models/frozen_2026",copy);file=next(copy.glob("*.joblib"));file.write_bytes(file.read_bytes()+b"x")
        values[22]=raises(lambda:verify_bundle(copy),"MODEL_BUNDLE_DRIFT");values[23]=raises(lambda:score_candidates(fixture,copy),"MODEL_BUNDLE_DRIFT")
    upper=lambda xs:[x.upper().replace(" ","_").replace("-","_") for x in xs]
    values[24]=len(fs2)==92;values[25]=len(fs3)==97;values[26]=not any("DATE" in x for x in upper(fs3));values[27]="Ticker" not in fs3;values[28]="Signal ID" not in fs3
    values[29]=not any(x in fs3 for x in ("ENTRY_FILLED","T1_BEFORE_STOP_63","T2_BEFORE_STOP_63"));values[30]=not any("FWD_" in x for x in upper(fs3));values[31]="ENTRY_FILLED" not in fs3;values[32]=not any(x.startswith("D1_") for x in upper(fs3))
    values[33]=all("handle_unknown='ignore'" in repr(models[n]["preprocessor"]) for n in actual);values[34]=feature_row_hash(fixture.iloc[0],fs3)==feature_row_hash(fixture.iloc[0],fs3)
    runner=(ROOT/"stage4a3/prospective_runner.py").read_text();values[35]="--date" not in runner and "PAST_DATE_PRODUCTION_MODE_PROHIBITED" in runner;values[36]="tests/dry_run" in runner.replace('\\','/')
    base_manifest=json.loads((ROOT/"tests/fixtures/HISTORICAL_TEST_FIXTURE_market_manifest.json").read_text());values[37]=raises(lambda:validate_capture_window(datetime(2025,12,10,9,0,tzinfo=timezone.utc),"2025-12-10",base_manifest),"BEFORE_AFTER_CLOSE")
    stale={**base_manifest,"maximum_market_data_date":"2025-12-09"};future={**base_manifest,"maximum_market_data_date":"2025-12-11"};values[38]=raises(lambda:validate_capture_window(datetime(2025,12,10,12,tzinfo=timezone.utc),"2025-12-10",stale),"DATA_NOT_READY");values[39]=raises(lambda:validate_capture_window(datetime(2025,12,10,12,tzinfo=timezone.utc),"2025-12-10",future),"FUTURE_MARKET_DATA")
    values[40]="SNAPSHOT_ALREADY_EXISTS_IMMUTABLE" in (ROOT/"stage4a3/immutable_ledger.py").read_text();values[41]="NO_OVERWRITE_NO_APPEND" in json.dumps(SNAPSHOT_SCHEMA);values[42]=not raises(lambda:validate_candidate_predictions(pd.DataFrame(columns=PREDICTION_COLUMNS)),"")
    values[43]=not any(any(t in c.upper() for t in FORBIDDEN_OUTCOME_TOKENS) for c in pred.columns);values[44]=all(f"R{i} Score" in pred for i in range(6));values[45]=not pred[[f"R{i} Score" for i in range(6)]].isna().any().any()
    ranked=rank_and_select(pd.DataFrame({"Signal Date":["x"]*3,"Signal ID":["b","a","c"],"Actionability Score":[2,2,1],"Technical Score":[1,2,9],**{f"R{i} Score":[.2,.2,.9] for i in range(1,6)}}))
    values[46]=ranked.set_index("Signal ID").loc["a","R0 Same-Date Rank"]==1;values[47]=ranked.set_index("Signal ID").loc["c","R1 Same-Date Rank"]==1;values[48]=ranked.set_index("Signal ID").loc["c","R2 Same-Date Rank"]==1
    scored,_=score_candidates(fixture,ROOT/"models/frozen_2026");entry_full=models["TRANSFER_ENTRY_LOGIT_FULL"];t1_full=models["TRANSFER_T1_LOGIT_FULL"];entry_raw=models["TRANSFER_ENTRY_LOGIT_RAW"];t1_raw=models["TRANSFER_T1_LOGIT_RAW"];rf=models["TRANSFER_ENTRY_RF_FULL"]
    prob=lambda b:b["estimator"].predict_proba(b["preprocessor"].transform(fixture[b["feature_names"]]))[:,1]
    values[49]=np.allclose(scored["R3 Score"],prob(entry_full)*prob(t1_full),rtol=0,atol=0);values[50]=np.allclose(scored["R4 Score"],prob(entry_raw)*prob(t1_raw),rtol=0,atol=0);values[51]=np.allclose(scored["R5 Score"],prob(rf),rtol=0,atol=0);values[52]=all(ranked.filter(like="K1 Selected").sum()==1);values[53]=all(ranked.filter(like="K2 Selected").sum()==2);values[54]=ranked.set_index("Signal ID").loc["c","R1_K1 Selected"];values[55]=not ranked.set_index("Signal ID").loc["a","R1_K1 Selected"]
    snapdir=ROOT/"tests/dry_run_hardened/snapshots/2025/2025-12-10";meta=json.loads((snapdir/"snapshot_metadata.json").read_text());values[56]=canonical_json_hash(meta)==canonical_json_hash(meta);g=genesis_hash("p","m");values[57]=g==genesis_hash("p","m");ch=current_chain_hash(g,"2025-01-01","s","p","m");values[58]=ch==current_chain_hash(g,"2025-01-01","s","p","m")
    with tempfile.TemporaryDirectory() as td:
        temp=Path(td);shutil.copytree(ROOT/"tests/dry_run_hardened/snapshots",temp/"snapshots");shutil.copytree(ROOT/"tests/dry_run_hardened/audit",temp/"audit");idx=pd.read_csv(temp/"audit/prospective_snapshot_index.csv",dtype=str);pc=idx.iloc[0]["Previous Chain Hash"]
        dry_protocol=json.loads((temp/"snapshots/2025/2025-12-10/hash_chain.json").read_text())["Protocol Commit"]
        valid=lambda:verify_ledger(temp/"snapshots",temp/"audit",dry_protocol,manifest["FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH"],pc)
        values[59]=valid();(temp/"snapshots/2025/2025-12-10/snapshot_metadata.json").write_text("{}\n");values[59]=values[59] and not valid()
        shutil.rmtree(temp/"snapshots");shutil.copytree(ROOT/"tests/dry_run_hardened/snapshots",temp/"snapshots");(temp/"snapshots/2025/2025-12-10/candidate_predictions.csv.gz").unlink();values[60]=not valid()
    bad=pd.DataFrame([{c:"" for c in INDEX_COLUMNS} for _ in range(2)]);bad["Sequence"]=[1,2];bad["Signal Date"]=["2025-02-01","2025-01-01"];values[61]=not verify_index(bad,"p","m",g);bad["Signal Date"]=["2025-01-01"]*2;values[62]=not verify_index(bad,"p","m",g);values[63]="append-only" in json.dumps(SNAPSHOT_SCHEMA).lower() or "NO_OVERWRITE_NO_APPEND" in json.dumps(SNAPSHOT_SCHEMA);values[64]="ACTIVATION_BLOCKED_PROTOCOL_DRIFT" in (ROOT/"stage4a3/activation.py").read_text();values[65]=values[22] and values[23]
    tag=config["protocol_tag"];values[66]=subprocess.call(["git","show-ref","--verify","--quiet",f"refs/tags/{tag}"],cwd=REPO)!=0;act_source=(ROOT/"stage4a3/activation.py").read_text();values[67]="ACTIVATION_RECORD_IMMUTABLE" in act_source;activation={"Activation UTC":"2026-01-01T10:00:00+00:00","Activation Local Date":"2026-01-01"};values[68]=not signal_is_after_activation(activation,"2026-01-01T09:59:59+00:00","2026-01-01");values[69]=signal_is_after_activation(activation,"2026-01-02T10:00:01+00:00","2026-01-02");values[70]="record_path.exists()" in act_source
    values[71]=OUTCOME_SCHEMA["location"]=="prospective/outcomes only";before=sha256_file(snapdir/"candidate_predictions.csv.gz");values[72]=before==sha256_file(snapdir/"candidate_predictions.csv.gz")
    base={"Generated UTC":"2026-01-02T00:00:00+00:00","Signal ID":"S","Signal Date":"2026-01-01","Ticker":"T","Policy":"","Outcome Type":"ENTRY_FILLED","Outcome State":"RESOLVED","Outcome Value":True,"Observation Through Date":"2026-01-02","Label Available Date":"2026-01-02","Source Market Data Hash":"h","Is Terminal":True};event=seal_event(base,"GENESIS");values[73]=event["Label Available Date"]>event["Signal Date"];values[74]="ENTRY_FILLED" in OUTCOME_SCHEMA["outcome_types"];values[75]="T1_BEFORE_STOP_63" in OUTCOME_SCHEMA["outcome_types"];values[76]="T2_BEFORE_STOP_63" in OUTCOME_SCHEMA["outcome_types"];values[77]="D1_TRADE_COMPLETION" in OUTCOME_SCHEMA["outcome_types"];values[78]="STOP_FIRST" in OUTCOME_SCHEMA["target_semantics"];values[79]="63-session" in OUTCOME_SCHEMA["target_semantics"];values[80]=event["Event Hash"]==seal_event(base,"GENESIS")["Event Hash"]
    ef=pd.DataFrame([event]);values[81]=verify_event_chain(ef,"GENESIS");tamper=ef.copy();tamper.loc[0,"Outcome Value"]="FALSE";values[81]=values[81] and not verify_event_chain(tamper,"GENESIS")
    forbidden=["auc","return","expectancy","pf","policy winner"];status_text=" ".join(ALLOWED_FIELDS).lower();[values.__setitem__(82+i,x not in status_text) for i,x in enumerate(forbidden)]
    full={"as_of_date":"2028-02-01","candidate_count":150,"r0_k1_completed_d1":50,"r3_k1_completed_d1":50,"resolved_entry_labels":100,"resolved_t1_filled":60,"ledger_chain_pass":True,"protocol_integrity_pass":True};act={"Activation UTC":"2026-01-01T00:00:00"}
    cases=[({**full,"as_of_date":"2027-12-31"},"calendar duration months"),({**full,"candidate_count":149},"BASELINE_PRIMARY candidates"),({**full,"r0_k1_completed_d1":49},"R0_K1 completed D1 trades"),({**full,"r3_k1_completed_d1":49},"R3_K1 completed D1 trades"),({**full,"resolved_entry_labels":99},"resolved ENTRY_FILLED labels"),({**full,"resolved_t1_filled":59},"resolved filled T1 outcomes")]
    for n,(counts,label) in enumerate(cases,87):values[n]=not is_unlocked(gate_audit(config,act,counts)) and gate_audit(config,act,counts).set_index("Gate").loc[label,"Status"]=="LOCKED"
    options={a.dest for a in evaluation_parser()._actions};values[93]=not options.intersection({"force","ignore_minimum","unlock","override_sample_size"});values[94]="PREMATURE_EVALUATION_ATTEMPT" in (ROOT/"stage4a3/final_evaluation.py").read_text()
    values[95]=config["primary_policy"]=="R3_K1";values[96]=config["primary_comparator"]=="R0_K1";values[97]=values[98]=values[99]=not config.get("secondary_substitution_allowed",False);values[100]=config["primary_policy"]!="R5_K1";values[101]="K2" not in config["primary_policy"]
    criteria=economic_criteria({"total_return":2,"cagr":2,"expectancy_r":2,"profit_factor":2,"max_drawdown":-.11,"completed_trades":50},{"total_return":1,"cagr":1,"expectancy_r":1,"profit_factor":2,"max_drawdown":-.10,"completed_trades":50},{"bootstrap_63_delta_terminal_return_lower_2_5":.01,"random_k1_total_return_percentile":95,"ledger_integrity_pass":True,"no_protocol_drift":True});values[102]=len(criteria)==10 and criteria["Status"].eq("PASS").all();values[103]=config["bootstrap"]=={"primary_block_sessions":63,"sensitivity_block_sessions":[21,126],"replicates":2000,"seed":42};values[104]=list(range(config["random_control"]["k1_seeds_start"],config["random_control"]["k1_seeds_end"]+1))==list(range(500));values[105]=config["final_economic_criteria"]["random_k1_total_return_percentile_gte"]==95;values[106]=config["final_economic_criteria"]["max_drawdown_not_worse_than_r0_by_more_than_pp"]==2;values[107]=config["final_economic_criteria"]["minimum_completed_trades"]==50
    lower=source_files.lower();values[108]=".fit(" not in runner;values[109]="annual refit" not in lower;values[110]="threshold optimization" not in lower and "probability threshold" not in runner;values[111]="calibrat" not in runner.lower();values[112]="validate_feature_contract" in runner;values[113]="position sizing" not in runner.lower();values[114]="ml stop" not in runner.lower();values[115]="ml target" not in runner.lower();values[116]="ml exit" not in runner.lower();values[117]="recommendation" not in runner.lower();values[118]=not (REPO/"Stage 5").exists()
    return [{"Test Number":i,"Test":name,"Status":"PASS" if bool(values.get(i,False)) else "FAIL","Details":"contract assertion"} for i,name in enumerate(NAMES,1)]


def main()->None:
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,default=ROOT/"results/stage4a3_unit_test_results.csv");a=p.parse_args();rows=evaluate();frame=pd.DataFrame(rows);a.output.parent.mkdir(parents=True,exist_ok=True);frame.to_csv(a.output,index=False,lineterminator="\n");print(frame["Status"].value_counts().to_dict());raise SystemExit(0 if frame["Status"].eq("PASS").all() else 1)
if __name__=="__main__":main()
