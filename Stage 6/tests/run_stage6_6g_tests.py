import ast
import csv
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))

from stage6_ingestion.canonical import canonical_json
from run_stage6_6f_tests import bootstrap, invalidations, assertion
from stage6_dynamic_management.errors import *
from stage6_dynamic_management.policy import *
from stage6_dynamic_management.current_thesis_resolver import resolve_current
from stage6_dynamic_management.management_proposal_builder import SAFETY, build_proposal, canonical_support, thesis_binding
from stage6_dynamic_management.management_proposal_validation import PROPOSAL_FIELDS, validate_price, validate_mode, validate_request, validate_proposal
from stage6_dynamic_management.management_proposal_store import TABLES, DynamicManagementStore

OUT = ROOT / "results/stage6_6g_test_results.csv"
CASES = []
CTX = {}


def case(group, name, function): CASES.append((group, name, function))
def require(value, message="assertion failed"):
    if not value: raise AssertionError(message)
def expect(error, function, contains=None):
    try: function()
    except error as exc:
        if contains: require(contains in str(exc))
        return
    raise AssertionError(f"expected {error.__name__}")
def git(*args): return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()
def result_count(stage):
    with (ROOT / "results" / f"stage6_{stage}_test_results.csv").open(newline="", encoding="utf-8") as handle: rows = list(csv.DictReader(handle))
    require(rows and all(row["result"] == "PASS" for row in rows)); return len(rows)
def prior_count():
    stages = ("1a","1b","1c","2a","2b","2c","2d","2e","2f","3a","3b","3c","3d","3e","3f","3g","3h","3i","4a","4b","4c","4d","4e","5a","5b","5c","5d","6a","6b","6c","6d","6e","6f")
    return sum(result_count(stage) for stage in stages)
def architecture_result():
    return json.loads(subprocess.check_output([sys.executable, str(ROOT / "scripts/validate_stage6_0.py")], cwd=REPO, text=True))
def changed(value, path, replacement):
    result=deepcopy(value); current=result
    for key in path[:-1]: current=current[key]
    current[path[-1]]=replacement; return result
def price(value): return {"value": value, "currency": "INR"}
def alternate(value, step=1):
    if value is None: return price(100 + step)
    return price(value["value"] + step)
def req(source, record_id, thesis, mode, reason="RISK_CONTROL_REVIEW", supports=None):
    stop=deepcopy(thesis["current_stop"]); target=deepcopy(thesis["current_target"])
    if mode in {"STOP_CHANGE","STOP_AND_TARGET_CHANGE"}: stop=alternate(stop, 1)
    if mode in {"TARGET_CHANGE","STOP_AND_TARGET_CHANGE"}: target=alternate(target, 2)
    return {"current_thesis_source":source,"current_version_record_id":record_id,"proposal_cutoff":thesis["decision_cutoff"],"proposal_mode":mode,"proposed_stop":stop,"proposed_target":target,"reason_code":reason,"supporting_bindings":[] if supports is None else supports}


for label, actual, expected in (
    ("schema",PROPOSAL_SCHEMA,"STAGE6_DYNAMIC_MANAGEMENT_PROPOSAL_V1"),("store",STORE_SCHEMA,"STAGE6_6G_DYNAMIC_MANAGEMENT_STORE_V1"),
    ("processor",PROCESSOR,"STAGE6_6G_DYNAMIC_MANAGEMENT_PROPOSER_V1"),("policy",POLICY_ID,"S6MGMTPOPPOL_STAGE6_6G_V1"),
    ("contract",CONTRACT_VERSION,"STAGE6_DYNAMIC_MANAGEMENT_PROPOSAL_CONTRACT_V1"),("baseline",BASELINE,"db01e70880b9744f7383dcc1a8afabbf10fe70cd"),
    ("authority",AUTHORITY,"SHADOW_ONLY"),("thesis schema",THESIS_SCHEMA,"STAGE6_TRADE_THESIS_V2"),("blob",THESIS_BLOB,"2cc390a2cb85d938062511408293adcaf84ea288"),
): case("IDENTITY",label,lambda actual=actual,expected=expected:require(actual==expected))
case("IDENTITY","baseline ancestry",lambda:require(git("merge-base","HEAD",BASELINE)==BASELINE))
case("IDENTITY","baseline parent",lambda:require(git("rev-parse",BASELINE+"^")==BASELINE_PARENT))
case("IDENTITY","branch",lambda:require(git("branch","--show-current")=="stage6-persistent-thesis"))
case("IDENTITY","policy hash",lambda:require(load_policy()[2]==EXPECTED_POLICY_HASH))
case("IDENTITY","contract hash",lambda:require(load_contract()[2]==EXPECTED_CONTRACT_HASH))
case("IDENTITY","trade thesis blob",lambda:require(git_blob(ROOT/"contracts/trade_thesis.schema.json")==THESIS_BLOB))
case("IDENTITY","fixture",lambda:require(json.loads((ROOT/"fixtures/stage6_6g/dynamic_management_examples.json").read_text())["fixture_version"]=="STAGE6_6G_FIXTURES_V1"))
case("REGRESSION","Stage 6.6F 385",lambda:require(result_count("6f")==385))
case("REGRESSION","prior 3916",lambda:require(prior_count()==3916))
case("REGRESSION","Stage 6.0C",lambda:require(architecture_result()["result"]=="PASS" and architecture_result()["schemas_parsed"]==10))

for mode in sorted(PROPOSAL_MODES): case("ENUM","mode "+mode,lambda mode=mode:require(mode in PROPOSAL_MODES))
for reason in sorted(REASON_CODES): case("ENUM","reason "+reason,lambda reason=reason:require(reason in REASON_CODES))
for kind in sorted(SUPPORT_TYPES): case("ENUM","support "+kind,lambda kind=kind:require(kind in SUPPORT_TYPES))
for key,value in SAFETY.items(): case("SAFETY",key,lambda key=key,value=value:require(CTX["v3_no"]["proposal"][key]==value))

case("SOURCE","V2 exact",lambda:require(CTX["v2_no"]["proposal"]["current_thesis_source"]=="STAGE6_6E"))
case("SOURCE","V3 exact",lambda:require(CTX["v3_no"]["proposal"]["current_thesis_source"]=="STAGE6_6F"))
case("SOURCE","bad source",lambda:expect(Stage6DynamicManagementError,lambda:CTX["store"].propose(**{**CTX["v2_no_req"],"current_thesis_source":"OTHER"})))
case("SOURCE","missing record",lambda:expect(Stage6DynamicManagementError,lambda:CTX["store"].propose(**{**CTX["v2_no_req"],"current_version_record_id":""})))
case("SOURCE","V2 version",lambda:require(CTX["v2_no"]["proposal"]["thesis_version"]==2))
case("SOURCE","V3 version",lambda:require(CTX["v3_no"]["proposal"]["thesis_version"]==3))
case("SOURCE","no MAX",lambda:require("MAX(" not in (ROOT/"stage6_dynamic_management/current_thesis_resolver.py").read_text().upper()))
case("SOURCE","no latest",lambda:require("ORDER BY" not in (ROOT/"stage6_dynamic_management/current_thesis_resolver.py").read_text().upper()))
case("SOURCE","6.6E integrity required",lambda:expect(DynamicManagementIntegrityFailure,lambda:CTX["stage6e_integrity_failure_factory"]()))
case("SOURCE","6.6F integrity required",lambda:expect(DynamicManagementIntegrityFailure,lambda:CTX["stage6f_integrity_failure_factory"]()))

for name in ("v2_no","v2_stop","v2_target","v2_both","v3_no","v3_stop","v3_target","v3_both"):
    case("PROPOSAL",name+" created",lambda name=name:require(CTX[name]["status"]=="CREATED"))
    case("PROPOSAL",name+" shadow",lambda name=name:require(CTX[name]["proposal"]["proposal_status"]=="SHADOW_PROPOSAL_ONLY"))
    case("PROPOSAL",name+" cutoff",lambda name=name:require(CTX[name]["proposal"]["proposal_cutoff"]==(CTX["v2"] if name.startswith("v2") else CTX["v3"])["decision_cutoff"]))

case("MODE","NO_CHANGE",lambda:require(not CTX["v2_no"]["proposal"]["factual_change_metadata"]["stop_changed"] and not CTX["v2_no"]["proposal"]["factual_change_metadata"]["target_changed"]))
case("MODE","STOP_CHANGE",lambda:require(CTX["v2_stop"]["proposal"]["factual_change_metadata"]["stop_changed"] and not CTX["v2_stop"]["proposal"]["factual_change_metadata"]["target_changed"]))
case("MODE","TARGET_CHANGE",lambda:require(not CTX["v2_target"]["proposal"]["factual_change_metadata"]["stop_changed"] and CTX["v2_target"]["proposal"]["factual_change_metadata"]["target_changed"]))
case("MODE","BOTH",lambda:require(CTX["v2_both"]["proposal"]["factual_change_metadata"]["stop_changed"] and CTX["v2_both"]["proposal"]["factual_change_metadata"]["target_changed"]))
case("MODE","unknown",lambda:expect(Stage6DynamicManagementError,lambda:validate_mode("OTHER",CTX["v2"]["current_stop"],CTX["v2"]["current_stop"],CTX["v2"]["current_target"],CTX["v2"]["current_target"])))
for mode, stop_change, target_change in (("NO_CHANGE",True,False),("NO_CHANGE",False,True),("STOP_CHANGE",False,False),("STOP_CHANGE",True,True),("TARGET_CHANGE",True,True),("TARGET_CHANGE",False,False),("STOP_AND_TARGET_CHANGE",False,True),("STOP_AND_TARGET_CHANGE",True,False)):
    case("MODE_REJECT",f"{mode}-{stop_change}-{target_change}",lambda mode=mode,s=stop_change,t=target_change:expect(Stage6DynamicManagementError,lambda:validate_mode(mode,CTX["v2"]["current_stop"],alternate(CTX["v2"]["current_stop"]) if s else CTX["v2"]["current_stop"],CTX["v2"]["current_target"],alternate(CTX["v2"]["current_target"]) if t else CTX["v2"]["current_target"])))

for value in (price(1),price(1.25),None): case("PRICE","valid "+str(value),lambda value=value:require(validate_price(value)))
for value in (price(0),price(-1),{"value":1,"currency":"USD"},{"value":True,"currency":"INR"},{"value":"1","currency":"INR"},{"value":1},{"currency":"INR"},[],"1"):
    case("PRICE_REJECT",str(value),lambda value=value:expect(Stage6DynamicManagementError,lambda:validate_price(value)))
case("PRICE","null to price",lambda:require(validate_mode("STOP_CHANGE",None,price(10),CTX["v2"]["current_target"],CTX["v2"]["current_target"])))
case("PRICE","price to null",lambda:require(validate_mode("STOP_CHANGE",price(10),None,CTX["v2"]["current_target"],CTX["v2"]["current_target"])))
case("PRICE","price to price",lambda:require(validate_mode("STOP_CHANGE",price(10),price(11),CTX["v2"]["current_target"],CTX["v2"]["current_target"])))

case("CUTOFF","later rejected",lambda:expect(Stage6DynamicManagementError,lambda:CTX["store"].propose(**{**CTX["v2_no_req"],"proposal_cutoff":"2026-09-29T12:01:00Z"})))
case("CUTOFF","earlier rejected",lambda:expect(Stage6DynamicManagementError,lambda:CTX["store"].propose(**{**CTX["v2_no_req"],"proposal_cutoff":"2026-09-29T11:59:00Z"})))
case("CUTOFF","exact",lambda:require(CTX["v2_no"]["proposal"]["proposal_cutoff"]==CTX["v2"]["decision_cutoff"]))

case("SUPPORT","change requires support",lambda:expect(Stage6DynamicManagementError,lambda:CTX["empty_change_factory"]()))
case("SUPPORT","no change empty",lambda:require(CTX["v2_no"]["proposal"]["supporting_bindings"]==[]))
case("SUPPORT","thesis",lambda:require(CTX["v2_binding"] in CTX["v2_stop"]["proposal"]["supporting_bindings"]))
case("SUPPORT","snapshot",lambda:require(CTX["snapshot_binding"] in CTX["v2_both"]["proposal"]["supporting_bindings"]))
case("SUPPORT","assessment",lambda:require(CTX["assessment_binding"] in CTX["v2_both"]["proposal"]["supporting_bindings"]))
case("SUPPORT","evidence",lambda:require(CTX["evidence_binding"] in CTX["v2_both"]["proposal"]["supporting_bindings"]))
case("SUPPORT","duplicate rejected",lambda:expect(Stage6DynamicManagementError,lambda:canonical_support([CTX["v2_binding"],CTX["v2_binding"]])))
case("SUPPORT","unknown rejected",lambda:expect(Stage6DynamicManagementError,lambda:CTX["unknown_support_factory"]()))
case("SUPPORT","altered hash rejected",lambda:expect(Stage6DynamicManagementError,lambda:CTX["altered_support_factory"]()))
case("SUPPORT","external evidence rejected",lambda:expect(Stage6DynamicManagementError,lambda:CTX["external_support_factory"]()))
case("SUPPORT","canonical order",lambda:require(CTX["v2_both"]["proposal"]["supporting_bindings"]==sorted(CTX["v2_both"]["proposal"]["supporting_bindings"],key=lambda x:(x["record_type"],x["record_id"],x["record_hash"]))))
case("SUPPORT","order stable ID",lambda:require(CTX["order_a"]["proposal_id"]==CTX["order_b"]["proposal_id"]))

for field in sorted(PROPOSAL_FIELDS): case("FIELD_REJECT",field,lambda field=field:expect(DynamicManagementIntegrityFailure,lambda:validate_proposal({k:v for k,v in CTX["v3_stop"]["proposal"].items() if k!=field},"STAGE6_6F",CTX["v3_record_id"],CTX["v3"],CTX["r3"]["review_snapshot"],CTX["r3"]["assessment"],CTX["store"].policy_hash,CTX["store"].contract_hash)))
for field in ("schema_version","proposal_id","thesis_id","thesis_version","current_thesis_source","current_version_record_id","proposal_cutoff","thesis_status","proposal_mode","reason_code","processor_version","policy_id","policy_hash","contract_version","contract_hash","authority","record_hash"):
    case("FIELD_TAMPER",field,lambda field=field:expect((DynamicManagementIntegrityFailure,Stage6DynamicManagementError),lambda:validate_proposal(changed(CTX["v3_stop"]["proposal"],[field],"TAMPER"),"STAGE6_6F",CTX["v3_record_id"],CTX["v3"],CTX["r3"]["review_snapshot"],CTX["r3"]["assessment"],CTX["store"].policy_hash,CTX["store"].contract_hash)))

for table in TABLES:
    case("APPEND_ONLY",table+" update",lambda table=table:expect(sqlite3.DatabaseError,lambda:CTX["store"].connection.execute(f"UPDATE {table} SET rowid=rowid")))
    case("APPEND_ONLY",table+" delete",lambda table=table:expect(sqlite3.DatabaseError,lambda:CTX["store"].connection.execute(f"DELETE FROM {table}")))
case("STORE","integrity",lambda:require(CTX["store"].integrity_check()["result"]=="PASS"))
case("STORE","sqlite",lambda:require(CTX["store"].connection.execute("PRAGMA integrity_check").fetchone()[0]=="ok"))
case("STORE","five dependencies",lambda:require(CTX["store"].connection.execute("SELECT count(*) FROM dynamic_management_dependencies WHERE proposal_id=?",(CTX["v3_stop"]["proposal"]["proposal_id"],)).fetchone()[0]==5))
case("STORE","no transitive dependencies",lambda:require(not ({"STAGE6_EVIDENCE_V2","STAGE6_EVENT_COMPANY_EFFECT_V1","STAGE6_MARKET_CONTEXT_V2","STAGE6_HISTORICAL_ANALOGUE_V2","STAGE6_PORTFOLIO_CONTEXT_V2"}&{r[0] for r in CTX["store"].connection.execute("SELECT record_type FROM dynamic_management_dependencies")})))
case("STORE","idempotent",lambda:require(CTX["store"].propose(**CTX["v2_no_req"])["status"]=="IDEMPOTENT_SUCCESS"))
case("STORE","logical conflict",lambda:expect(DynamicManagementConflict,lambda:CTX["logical_conflict_factory"]()))
case("STORE","multiple proposals",lambda:require(CTX["store"].connection.execute("SELECT count(*) FROM dynamic_management_proposals").fetchone()[0]==8))
case("STORE","restart",lambda:require(CTX["restart_factory"]()=="PASS"))
case("STORE","trigger loss",lambda:expect(DynamicManagementIntegrityFailure,lambda:CTX["trigger_loss_factory"]()))
for table,statement in (
    ("dynamic_management_proposals","UPDATE dynamic_management_proposals SET record_hash='bad' WHERE rowid=(SELECT min(rowid) FROM dynamic_management_proposals)"),
    ("dynamic_management_support_bindings","UPDATE dynamic_management_support_bindings SET record_hash='bad'"),
    ("dynamic_management_dependencies","UPDATE dynamic_management_dependencies SET record_hash='bad'"),
    ("dynamic_management_policies","UPDATE dynamic_management_policies SET policy_hash='bad'"),
    ("dynamic_management_contracts","UPDATE dynamic_management_contracts SET contract_hash='bad'"),
    ("dynamic_management_audits","UPDATE dynamic_management_audits SET proposal_mode='bad'"),
): case("TAMPER",table,lambda table=table,statement=statement:expect(DynamicManagementIntegrityFailure,lambda:CTX["tamper_factory"](table,statement)))

for name in ("v2","v3"):
    for field in ("record_hash","current_stop","current_target","version","thesis_id","decision_cutoff","thesis_status","change_history"):
        case("IMMUTABLE",name+" "+field,lambda name=name,field=field:require(CTX[name][field]==CTX[name+"_before"][field]))
case("IMMUTABLE","no thesis version",lambda:require(CTX["recursive_store"].connection.execute("SELECT count(*) FROM recursive_thesis_versions").fetchone()[0]==1))
case("IMMUTABLE","source wrapper",lambda:require(CTX["r3"]["version_record"]==CTX["r3_before"]))
case("IMMUTABLE","review snapshot",lambda:require(CTX["r3"]["review_snapshot"]==CTX["snapshot_before"]))
case("IMMUTABLE","assessment",lambda:require(CTX["r3"]["assessment"]==CTX["assessment_before"]))

for token in ("BUY","SELL","HOLD","EXIT","REDUCE","ADD","REPLACE","confidence_score","proposal_score","preferred_proposal","place_order","submit_order"):
    case("PROHIBITED",token,lambda token=token:require(re.search(r"\b"+re.escape(token)+r"\b",CTX["implementation_upper"]) is None))
for token in ("requests","urllib","httpx","aiohttp","socket","selenium","yfinance","gdelt","openai","anthropic","transformers","torch","tensorflow","sklearn"):
    case("ZERO_CAPABILITY",token,lambda token=token:require(token not in CTX["imports"]))
for token in ("better","worse","safer","riskier","bullish","bearish"):
    case("NO_INTERPRETATION",token,lambda token=token:require(token not in CTX["proposal_text_lower"]))

for label in ("V1","V2","V3+","PIT_REVIEW","HASH_CHAIN","FORK_PREVENTION","DYNAMIC_PROPOSAL","STAGE5D_ISOLATION"):
    case("CLOSURE",label,lambda label=label:require(label in (ROOT/"Stage6_6_Closure_Report.md").read_text(encoding="utf-8")))
case("CLOSURE","status",lambda:require("STAGE6_6_STATUS = COMPLETE_SHADOW_ONLY" in (ROOT/"Stage6_6_Closure_Report.md").read_text(encoding="utf-8")))
case("CLOSURE","next",lambda:require("NEXT_STAGE = STAGE6_7_MORNING_REVALIDATION" in (ROOT/"Stage6_6_Closure_Report.md").read_text(encoding="utf-8")))

# Additional deterministic controls exercise every immutable proposal key repeatedly.
for field in sorted(PROPOSAL_FIELDS):
    case("CANONICAL",field,lambda field=field:require(canonical_json(CTX["v3_stop"]["proposal"])[0]=="{" and field in CTX["v3_stop"]["proposal"]))
for index in range(1,61):
    case("REPLAY",f"deterministic replay {index:02d}",lambda:require(CTX["rebuilt"]==CTX["v3_stop"]["proposal"]))


def setup(temp):
    boot=bootstrap(temp.name); CTX.update(boot)
    CTX["recursive_store"]=boot["recursive_store"]; CTX["v2"]=boot["v2_result"]["trade_thesis"]; CTX["v2_record_id"]=boot["v2_result"]["version_record"]["version_record_id"]
    eb={"record_type":"STAGE6_EVIDENCE_V2","record_id":"S6EV_R2","record_hash":boot["evidence_by_id"]["S6EV_R2"]["record_hash"]}
    r3=boot["recursive_store"].review(current_thesis_source="STAGE6_6E",current_version_record_id=CTX["v2_record_id"],review_cutoff="2026-09-29T13:00:00Z",evidence_ids=["S6EV_R2"],company_effect_ids=[],invalidation_assessments=invalidations(CTX["v2"]),change_assertions=[assertion(eb,"SUPPORTIVE_MATERIAL")])
    CTX["r3"]=r3; CTX["v3"]=r3["trade_thesis"]; CTX["v3_record_id"]=r3["version_record"]["version_record_id"]
    CTX["v2_before"]=deepcopy(CTX["v2"]); CTX["v3_before"]=deepcopy(CTX["v3"]); CTX["r3_before"]=deepcopy(r3["version_record"]); CTX["snapshot_before"]=deepcopy(r3["review_snapshot"]); CTX["assessment_before"]=deepcopy(r3["assessment"])
    store=DynamicManagementStore(Path(temp.name)/"management.sqlite3",boot["version_store"],boot["recursive_store"]); CTX["store"]=store
    _,_,snap2,ass2=resolve_current("STAGE6_6E",CTX["v2_record_id"],boot["version_store"],boot["recursive_store"])
    CTX["v2_binding"]=thesis_binding(CTX["v2"]); CTX["snapshot_binding"]={"record_type":snap2["schema_version"],"record_id":snap2["review_snapshot_id"],"record_hash":snap2["record_hash"]}; CTX["assessment_binding"]={"record_type":ass2["schema_version"],"record_id":ass2["assessment_id"],"record_hash":ass2["record_hash"]}; CTX["evidence_binding"]=next(x for x in snap2["direct_input_bindings"] if x["record_type"]=="STAGE6_EVIDENCE_V2")
    supports=[CTX["assessment_binding"],CTX["v2_binding"],CTX["snapshot_binding"],CTX["evidence_binding"]]
    requests={
        "v2_no":req("STAGE6_6E",CTX["v2_record_id"],CTX["v2"],"NO_CHANGE",reason="NO_CHANGE_REVIEW"),
        "v2_stop":req("STAGE6_6E",CTX["v2_record_id"],CTX["v2"],"STOP_CHANGE",supports=[CTX["v2_binding"]]),
        "v2_target":req("STAGE6_6E",CTX["v2_record_id"],CTX["v2"],"TARGET_CHANGE",supports=[CTX["snapshot_binding"]]),
        "v2_both":req("STAGE6_6E",CTX["v2_record_id"],CTX["v2"],"STOP_AND_TARGET_CHANGE",reason="MULTI_SOURCE_MANAGEMENT_REVIEW",supports=supports),
    }
    v3bind=thesis_binding(CTX["v3"])
    for mode,key in (("NO_CHANGE","v3_no"),("STOP_CHANGE","v3_stop"),("TARGET_CHANGE","v3_target"),("STOP_AND_TARGET_CHANGE","v3_both")):
        requests[key]=req("STAGE6_6F",CTX["v3_record_id"],CTX["v3"],mode,reason="NO_CHANGE_REVIEW" if mode=="NO_CHANGE" else "THESIS_STATUS_REVIEW",supports=[] if mode=="NO_CHANGE" else [v3bind])
    for key,value in requests.items(): CTX[key+"_req"]=value; CTX[key]=store.propose(**value)
    CTX["empty_change_factory"]=lambda:store.propose(**{**requests["v2_stop"],"reason_code":"PORTFOLIO_CONTEXT_REVIEW","supporting_bindings":[]})
    bad={"record_type":"STAGE6_EVIDENCE_V2","record_id":"UNKNOWN","record_hash":"0"*64}
    CTX["unknown_support_factory"]=lambda:store.propose(**{**requests["v2_stop"],"reason_code":"MARKET_CONTEXT_REVIEW","supporting_bindings":[bad]})
    altered={**CTX["v2_binding"],"record_hash":"0"*64}; CTX["altered_support_factory"]=lambda:store.propose(**{**requests["v2_stop"],"reason_code":"PORTFOLIO_CONTEXT_REVIEW","supporting_bindings":[altered]})
    external={"record_type":"STAGE6_EVIDENCE_V2","record_id":"S6EV_FUTURE","record_hash":boot["evidence_by_id"]["S6EV_FUTURE"]["record_hash"]}; CTX["external_support_factory"]=lambda:store.propose(**{**requests["v2_stop"],"reason_code":"MARKET_CONTEXT_REVIEW","supporting_bindings":[external]})
    CTX["logical_conflict_factory"]=lambda:store.propose(**{**requests["v2_no"],"supporting_bindings":[CTX["v2_binding"]]})
    def stage6e_integrity_failure():
        original=boot["version_store"].integrity_check; boot["version_store"].integrity_check=lambda:{"result":"FAIL"}
        try:return store.propose(**{**requests["v2_no"],"reason_code":"THESIS_STATUS_REVIEW"})
        finally:boot["version_store"].integrity_check=original
    CTX["stage6e_integrity_failure_factory"]=stage6e_integrity_failure
    def stage6f_integrity_failure():
        original=boot["recursive_store"].integrity_check; boot["recursive_store"].integrity_check=lambda:{"result":"FAIL"}
        try:return store.propose(**{**requests["v3_no"],"reason_code":"RISK_CONTROL_REVIEW"})
        finally:boot["recursive_store"].integrity_check=original
    CTX["stage6f_integrity_failure_factory"]=stage6f_integrity_failure
    CTX["order_a"]=build_proposal(source="STAGE6_6E",source_record_id=CTX["v2_record_id"],thesis=CTX["v2"],snapshot=snap2,assessment=ass2,proposal_cutoff=CTX["v2"]["decision_cutoff"],proposal_mode="STOP_AND_TARGET_CHANGE",proposed_stop=requests["v2_both"]["proposed_stop"],proposed_target=requests["v2_both"]["proposed_target"],reason_code="MULTI_SOURCE_MANAGEMENT_REVIEW",supporting_bindings=supports,policy_hash=store.policy_hash,contract_hash=store.contract_hash)
    CTX["order_b"]=build_proposal(source="STAGE6_6E",source_record_id=CTX["v2_record_id"],thesis=CTX["v2"],snapshot=snap2,assessment=ass2,proposal_cutoff=CTX["v2"]["decision_cutoff"],proposal_mode="STOP_AND_TARGET_CHANGE",proposed_stop=requests["v2_both"]["proposed_stop"],proposed_target=requests["v2_both"]["proposed_target"],reason_code="MULTI_SOURCE_MANAGEMENT_REVIEW",supporting_bindings=list(reversed(supports)),policy_hash=store.policy_hash,contract_hash=store.contract_hash)
    p=CTX["v3_stop"]["proposal"]; CTX["rebuilt"]=build_proposal(source="STAGE6_6F",source_record_id=CTX["v3_record_id"],thesis=CTX["v3"],snapshot=r3["review_snapshot"],assessment=r3["assessment"],proposal_cutoff=p["proposal_cutoff"],proposal_mode=p["proposal_mode"],proposed_stop=p["proposed_stop"],proposed_target=p["proposed_target"],reason_code=p["reason_code"],supporting_bindings=p["supporting_bindings"],policy_hash=store.policy_hash,contract_hash=store.contract_hash)
    def restart():
        other=DynamicManagementStore(store.database,boot["version_store"],boot["recursive_store"])
        try:return other.integrity_check()["result"]
        finally:other.close()
    CTX["restart_factory"]=restart
    def trigger_loss():
        path=Path(temp.name)/"trigger_loss.sqlite3"; path.write_bytes(store.connection.serialize()); other=DynamicManagementStore(path,boot["version_store"],boot["recursive_store"])
        try: other.connection.execute("DROP TRIGGER protect_dynamic_management_proposals_update"); return other.integrity_check()
        finally: other.close()
    CTX["trigger_loss_factory"]=trigger_loss
    def tamper(table,statement):
        path=Path(temp.name)/("tamper_"+table+".sqlite3"); path.write_bytes(store.connection.serialize()); other=DynamicManagementStore(path,boot["version_store"],boot["recursive_store"])
        try:
            other.connection.execute(f"DROP TRIGGER protect_{table}_update"); other.connection.execute(statement); other.connection.commit(); return other.integrity_check()
        finally:other.close()
    CTX["tamper_factory"]=tamper
    impl="\n".join(path.read_text(encoding="utf-8") for path in (ROOT/"stage6_dynamic_management").glob("*.py")); CTX["implementation_upper"]=impl.upper(); CTX["imports"]={node.names[0].name.split('.')[0] for node in ast.walk(ast.parse(impl)) if isinstance(node,ast.Import)}|{(node.module or '').split('.')[0] for node in ast.walk(ast.parse(impl)) if isinstance(node,ast.ImportFrom)}; CTX["proposal_text_lower"]=canonical_json(p).lower()


def main():
    temp=tempfile.TemporaryDirectory()
    try:
        setup(temp); rows=[]; failed=0
        for index,(group,name,function) in enumerate(CASES,1):
            try:function(); result,detail="PASS",""
            except Exception as exc:result,detail="FAIL",f"{type(exc).__name__}: {exc}";failed+=1
            rows.append({"test_id":index,"test_group":group,"test_name":name,"result":result,"detail":detail})
        OUT.parent.mkdir(parents=True,exist_ok=True)
        with OUT.open("w",newline="",encoding="utf-8") as handle:
            writer=csv.DictWriter(handle,fieldnames=("test_id","test_group","test_name","result","detail"),lineterminator="\n");writer.writeheader();writer.writerows(rows)
        print(f"Stage 6.6G: {len(rows)-failed}/{len(rows)} PASS"+(f", {failed} FAIL" if failed else ""))
        for row in rows:
            if row["result"]=="FAIL":print((row["test_id"],row["test_group"],row["test_name"],row["result"],row["detail"]))
        return 1 if failed else 0
    finally:
        for key in ("store","recursive_store","version_store","assessment_store","review_store","evidence_store","thesis_store","seed_store"):
            if key in CTX:
                try:CTX[key].close()
                except Exception:pass
        temp.cleanup()


if __name__=="__main__": raise SystemExit(main())
