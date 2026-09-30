import argparse,csv,json,subprocess,sys
from datetime import datetime,timezone,timedelta
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json,without
from .errors import ActivationBlocked,ProspectiveIntegrityFailure
from .policy import *
from .protocol import verify_configuration

def _now_utc():return datetime.now(timezone.utc).replace(microsecond=0)
def _git(repo,*args):
 git_dir=repo/"_git" if (repo/"_git").exists() else repo/".git";command=["git",f"--git-dir={git_dir}",f"--work-tree={repo}",*args]
 return subprocess.check_output(command,cwd=repo,text=True,stderr=subprocess.STDOUT).strip()
def _require_repository(repo):
 if _git(repo,"branch","--show-current")!=BRANCH:raise ActivationBlocked("ACTIVATION_BRANCH_INVALID")
 if _git(repo,"status","--porcelain"):raise ActivationBlocked("ACTIVATION_WORKTREE_NOT_CLEAN")
 if _git(repo,"merge-base","HEAD",BASELINE)!=BASELINE:raise ActivationBlocked("ACTIVATION_ANCESTRY_INVALID")
 if _git(repo,"rev-list","-n","1",CONTROL_TAG)!=CONTROL_COMMIT:raise ActivationBlocked("STAGE5D_CONTROL_TAG_INVALID")
 try:subprocess.check_call(["git",f"--git-dir={repo/('_git' if (repo/'_git').exists() else '.git')}",f"--work-tree={repo}","diff","--quiet",CONTROL_COMMIT,"HEAD","--","Stage 5D"],cwd=repo)
 except subprocess.CalledProcessError as exc:raise ActivationBlocked("STAGE5D_SUBTREE_CHANGED") from exc
 result=verify_configuration()
 if result["result"]!="PASS":raise ActivationBlocked("PROSPECTIVE_CONFIGURATION_INVALID")
 test_file=repo/"Stage 6/results/stage6_8a_test_results.csv"
 if not test_file.exists():raise ActivationBlocked("STAGE6_8A_TEST_EVIDENCE_MISSING")
 rows=list(csv.DictReader(test_file.open(encoding="utf-8")))
 if len(rows)<280 or any(x.get("result")!="PASS" for x in rows):raise ActivationBlocked("STAGE6_8A_TESTS_NOT_PASSING")
 validator=subprocess.run([sys.executable,str(repo/"Stage 6/scripts/validate_stage6_0.py")],cwd=repo,capture_output=True,text=True)
 if validator.returncode or '"result": "PASS"' not in validator.stdout or '"schemas_parsed": 10' not in validator.stdout:raise ActivationBlocked("STAGE6_0C_VALIDATION_FAILED")
 return result,_git(repo,"rev-parse","HEAD")
def verify_activation_record(path):
 value=json.loads(Path(path).read_text(encoding="utf-8"))
 if value.get("schema_version")!=ACTIVATION_SCHEMA or value.get("record_hash")!=canonical_hash(without(value,"record_hash")) or value.get("activation_id")!="S6PROSACT_"+canonical_hash(without(value,"activation_id","record_hash"))[:24]:raise ProspectiveIntegrityFailure("ACTIVATION_RECORD_INVALID")
 if (value.get("protocol_id"),value.get("protocol_hash"),value.get("policy_id"),value.get("policy_hash"),value.get("contract_id"),value.get("contract_hash"),value.get("stage6_7_closure_baseline"),value.get("branch"),value.get("stage5d5_control_commit"),value.get("authority"),value.get("trading_authority"))!=(PROTOCOL_ID,EXPECTED_PROTOCOL_HASH,POLICY_ID,EXPECTED_POLICY_HASH,CONTRACT_VERSION,EXPECTED_CONTRACT_HASH,BASELINE,BRANCH,CONTROL_COMMIT,AUTHORITY,False):raise ProspectiveIntegrityFailure("ACTIVATION_BINDING_INVALID")
 return value
def activation_status(runtime_dir):
 path=Path(runtime_dir)/"activation_record.json"
 return {"status":"NOT_ACTIVATED"} if not path.exists() else {"status":"ACTIVE","activation":verify_activation_record(path)}
def activate(repo_root,runtime_dir):
 repo=Path(repo_root).resolve();runtime=Path(runtime_dir).resolve();path=runtime/"activation_record.json"
 if path.exists():verify_activation_record(path);raise ActivationBlocked("ACTIVATION_ALREADY_EXISTS")
 config,head=_require_repository(repo);now=_now_utc();date_ist=now.astimezone(timezone(timedelta(hours=5,minutes=30))).date().isoformat()
 value={"schema_version":ACTIVATION_SCHEMA,"activation_id":"","protocol_id":PROTOCOL_ID,"protocol_hash":config["protocol_hash"],"policy_id":POLICY_ID,"policy_hash":config["policy_hash"],"contract_id":CONTRACT_VERSION,"contract_hash":config["contract_hash"],"stage6_7_closure_baseline":BASELINE,"stage6_8a_activation_head":head,"branch":BRANCH,"stage5d5_control_tag":CONTROL_TAG,"stage5d5_control_commit":CONTROL_COMMIT,"stage5d_subtree_verification":"PASS","stage6_7b_schema":SHADOW_SCHEMA,"stage6_7b_policy_id":SHADOW_POLICY,"stage6_7b_policy_hash":SHADOW_POLICY_HASH,"stage6_7b_contract_id":SHADOW_CONTRACT,"stage6_7b_contract_hash":SHADOW_CONTRACT_HASH,"stage6_7b_decision_engine_version":SHADOW_ENGINE,"stage6_7b_decision_code_hash":SHADOW_CODE_HASH,"activated_at_utc":now.isoformat().replace("+00:00","Z"),"activation_date_ist":date_ist,"minimum_completed_control_sessions":MINIMUM_SESSIONS,"performance_based_early_stopping":"PROHIBITED","authority":AUTHORITY,"trading_authority":False,"record_hash":""}
 value["activation_id"]="S6PROSACT_"+canonical_hash(without(value,"activation_id","record_hash"))[:24];value["record_hash"]=canonical_hash(without(value,"record_hash"));runtime.mkdir(parents=True,exist_ok=True)
 with path.open("x",encoding="utf-8",newline="\n") as handle:handle.write(json.dumps(value,sort_keys=True,indent=2)+"\n")
 return {"status":"ACTIVE","activation":value}
def main(argv=None):
 parser=argparse.ArgumentParser(description="Activate the audited Stage 6 prospective shadow-validation protocol exactly once.");parser.add_argument("--repo-root",required=True);parser.add_argument("--runtime-dir",required=True);args=parser.parse_args(argv)
 try:print(json.dumps(activate(args.repo_root,args.runtime_dir),sort_keys=True));return 0
 except Exception as exc:print(json.dumps({"status":"BLOCKED","error":str(exc)},sort_keys=True));return 1
if __name__=="__main__":raise SystemExit(main())
