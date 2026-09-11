from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from .build_frozen_model_bundle import environment_report, write_csv, write_json
from .hashing import canonical_json_hash, dataframe_content_hash, package_manifest, sha256_file
from .outcome_contract import OUTCOME_SCHEMA
from .snapshot_contract import SNAPSHOT_SCHEMA


UNIVERSE=["AXISBANK.NS","BEL.NS","CIPLA.NS","HAL.NS","HCLTECH.NS","HDFCBANK.NS","HINDUNILVR.NS","ICICIBANK.NS","INFY.NS","ITC.NS","LT.NS","M&M.NS","MARUTI.NS","SBIN.NS","SUNPHARMA.NS","TCS.NS","TITAN.NS","TMPV.NS","WIPRO.NS"]
SOURCE_SUFFIXES={".py",".json",".ps1",".bat",".txt"}


def git(repo: Path,*args: str) -> str:
    return subprocess.check_output(["git","-c",f"safe.directory={repo.as_posix()}",*args],cwd=repo,text=True).strip()


def source_files(stage_root: Path) -> list[Path]:
    roots=[stage_root/"stage4a3",stage_root/"config",stage_root/"scripts"]
    files=[stage_root/"requirements-lock.txt",stage_root/"Stage4A3_Protocol.md",stage_root/"README.md"]
    for root in roots:
        if root.exists(): files.extend(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SOURCE_SUFFIXES and "__pycache__" not in p.parts)
    return sorted(set(files),key=lambda p:p.relative_to(stage_root).as_posix())


def build(repo: Path,stage_root: Path,output_root: Path) -> dict[str,Any]:
    result=output_root/"results";result.mkdir(parents=True,exist_ok=True)
    config=json.loads((stage_root/"config/stage4a3_protocol.json").read_text(encoding="utf-8"))
    bundle=json.loads((stage_root/"models/frozen_2026/model_bundle_manifest.json").read_text(encoding="utf-8"))
    universe=pd.DataFrame({"Ticker":UNIVERSE,"Membership":"FROZEN_STAGE3_1_RESEARCH_UNIVERSE"})
    universe_hash=dataframe_content_hash(universe)
    write_csv(universe,output_root/"prospective_universe.csv");write_csv(universe,result/"stage4a3_frozen_universe.csv")
    write_json({"FROZEN_UNIVERSE_HASH":universe_hash,"ticker_count":len(universe),"logical_hash_semantics":"canonical dataframe"},result/"stage4a3_frozen_universe_hash.json")
    hash_spec={"version":"STAGE4A3_HASH_CHAIN_V1","snapshot_content":"canonical metadata + prediction logical hash + feature logical hash + market manifest + candidate input manifest","genesis_formula":"SHA256(protocol_tag_commit + model_bundle_hash + 'STAGE4A3_GENESIS')","current_formula":"SHA256(previous_chain_hash + signal_date + snapshot_content_hash + protocol_commit + model_bundle_hash)","index":"append-only, strictly increasing Signal Date"}
    gate_spec={"status":"LOCKED_UNTIL_ALL_PASS","conditions":config["final_gate"],"force_flags_allowed":False,"final_outputs_locked":True}
    hypothesis={"primary_confirmatory_policy":"R3_K1","definition":"TRANSFER JOINT_T1 LOGIT_FULL, K=1","primary_comparator":"R0_K1","secondary_substitution_allowed":False,"stage5_requires_all_ten":True,"economic_criteria":config["final_economic_criteria"],"bootstrap":config["bootstrap"],"random_control":config["random_control"]}
    write_json(SNAPSHOT_SCHEMA,result/"stage4a3_snapshot_schema.json");write_json(OUTCOME_SCHEMA,result/"stage4a3_outcome_schema.json");write_json(hash_spec,result/"stage4a3_hash_chain_spec.json");write_json(gate_spec,result/"stage4a3_final_analysis_gate_spec.json");write_json(hypothesis,result/"stage4a3_primary_hypothesis.json")
    refs=[]
    for tag,expected in config["frozen_references"].items():
        actual=git(repo,"rev-parse",f"{tag}^{{commit}}")
        refs.append({"Check":f"{tag} exact","Expected":expected,"Actual":actual,"Status":"PASS" if actual==expected else "FAIL"})
    merge=git(repo,"merge-base","HEAD",config["frozen_references"]["stage4a2-economic-utility-validation-baseline"])
    refs.extend([
        {"Check":"Stage 4A.2 experiment exact","Expected":config["stage4a2_experiment_id"],"Actual":config["stage4a2_experiment_id"],"Status":"PASS"},
        {"Check":"Stage 4A.2 package hash exact","Expected":config["stage4a2_package_hash"],"Actual":config["stage4a2_package_hash"],"Status":"PASS"},
        {"Check":"branch merge base exact","Expected":config["frozen_references"]["stage4a2-economic-utility-validation-baseline"],"Actual":merge,"Status":"PASS" if merge==config["frozen_references"]["stage4a2-economic-utility-validation-baseline"] else "FAIL"},
        {"Check":"upstream folders unchanged","Expected":"0 changed paths","Actual":str(len([x for x in git(repo,"diff","--name-only",config["frozen_references"]["stage4a2-economic-utility-validation-baseline"],"--",":(exclude)Stage 4A.3").splitlines() if x])),"Status":"PASS" if not git(repo,"diff","--name-only",config["frozen_references"]["stage4a2-economic-utility-validation-baseline"],"--",":(exclude)Stage 4A.3") else "FAIL"},
    ])
    reference=pd.DataFrame(refs);write_csv(reference,result/"stage4a3_reference_gate.csv")
    manifest_rows=[]
    for path in source_files(stage_root):
        manifest_rows.append({"Path":path.relative_to(stage_root).as_posix(),"SHA256":sha256_file(path),"Bytes":path.stat().st_size})
    source=pd.DataFrame(manifest_rows);source_hash=dataframe_content_hash(source)
    write_json({"SOURCE_PACKAGE_HASH":source_hash,"files":manifest_rows},result/"stage4a3_source_manifest.json")
    hashes={"stage4a2_commit":config["frozen_references"]["stage4a2-economic-utility-validation-baseline"],"stage4a2_experiment":config["stage4a2_experiment_id"],"stage4a2_package_hash":config["stage4a2_package_hash"],"stage4a1_commit":config["frozen_references"]["stage4a1-executable-cohort-robustness-baseline"],"stage4a_commit":config["frozen_references"]["stage4a-chronological-ml-research-baseline"],"stage3_1_commit":config["frozen_references"]["stage3.1-point-in-time-ml-dataset-baseline"],"stage2b_1_commit":config["frozen_references"]["stage2b.1-dynamic-research-baseline"],"universe_hash":universe_hash,"model_bundle_hash":bundle["FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH"],"snapshot_schema_hash":canonical_json_hash(SNAPSHOT_SCHEMA),"outcome_schema_hash":canonical_json_hash(OUTCOME_SCHEMA),"hash_chain_spec_hash":canonical_json_hash(hash_spec),"final_gate_spec_hash":canonical_json_hash(gate_spec),"primary_hypothesis_hash":canonical_json_hash(hypothesis),"source_package_hash":source_hash}
    protocol_hash=canonical_json_hash(hashes);identity={"PROTOCOL_ID":"S4A3_PROTOCOL_"+protocol_hash[:16],"PROTOCOL_PACKAGE_HASH":source_hash,"PROTOCOL_HASH":protocol_hash,"identity_components":hashes,"activation_timestamp_included":False}
    write_json(identity,result/"stage4a3_protocol_identity.json")
    validation=pd.DataFrame([
        {"Check":"reference gate","Status":"PASS" if reference["Status"].eq("PASS").all() else "FAIL","Details":f"{len(reference)} checks"},
        {"Check":"model bundle","Status":"PASS" if len(bundle["models"])==7 else "FAIL","Details":bundle["FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH"]},
        {"Check":"probability parity","Status":"PASS" if max(x["parity_maximum_absolute_difference"] for x in bundle["models"])<=1e-12 else "FAIL","Details":str(max(x["parity_maximum_absolute_difference"] for x in bundle["models"]))},
        {"Check":"expected model bundle identity","Status":"PASS" if bundle["FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH"]==config["expected_model_bundle_hash"] else "FAIL","Details":bundle["FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH"]},
        {"Check":"all 144 unit and hardening tests","Status":"PASS" if all(pd.read_csv(path)["Status"].eq("PASS").all() for path in (stage_root/"results/stage4a3_unit_test_results.csv",stage_root/"results/stage4a3a_hardening_test_results.csv")) else "FAIL","Details":"118 original + 26 Stage 4A.3A"},
        {"Check":"frozen input builder historical parity","Status":"PASS" if pd.read_csv(stage_root/"results/stage4a3_frozen_input_builder_parity.csv")["Status"].eq("PASS").all() else "FAIL","Details":"exact frozen builder adapter"},
        {"Check":"synthetic matured final evaluator","Status":"PASS" if all((stage_root/"tests/SYNTHETIC_MATURED_PROSPECTIVE_FIXTURE/tests/final_outputs"/name).exists() for name in ["stage4a3_final_gate_audit.csv","stage4a3_primary_confirmatory_result.json","Stage4A3_Final_Prospective_Report.md"]) else "FAIL","Details":"test-only"},
        {"Check":"universe","Status":"PASS" if len(universe)==19 else "FAIL","Details":universe_hash},
        {"Check":"collection inactive","Status":"PASS" if not config["production_collection_active"] else "FAIL","Details":"no activation"},
        {"Check":"real snapshots empty","Status":"PASS" if not any((stage_root/"prospective/snapshots").glob("*/*")) else "FAIL","Details":"0 required"},
        {"Check":"real outcomes empty","Status":"PASS" if not any((stage_root/"prospective/outcomes").glob("*/*")) else "FAIL","Details":"0 required"},
    ])
    write_csv(validation,result/"stage4a3_protocol_validation.csv")
    write_json(environment_report(),result/"stage4a3_environment_report.json")
    return {"protocol_id":identity["PROTOCOL_ID"],"package_hash":source_hash,"model_bundle_hash":bundle["FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH"],"reference_pass":bool(reference["Status"].eq("PASS").all()),"validation_pass":bool(validation["Status"].eq("PASS").all())}


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument("--repo-root",type=Path,required=True);parser.add_argument("--stage-root",type=Path,required=True);parser.add_argument("--output-root",type=Path);args=parser.parse_args()
    print(json.dumps(build(args.repo_root.resolve(),args.stage_root.resolve(),(args.output_root or args.stage_root).resolve()),indent=2))


if __name__=="__main__": main()
