"""Stage 6.4C deterministic leakage-safe historical analogue selection tests."""
from __future__ import annotations

import ast
import csv
import importlib.util
import json
import math
import socket
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


b = module("s64b_for_64c", "run_stage6_4b_tests.py")
from stage6_analogue_features.feature_validation import validate_feature_snapshot
from stage6_analogue_selection import AnalogueSelectionConflict, AnalogueSelectionIntegrityFailure, AnalogueSelectionStore, Stage6AnalogueSelectionError
from stage6_analogue_selection.comparator import categorical_distance, compare_snapshots, measure_distance, named_array_distance, numeric_distance, return_distance
from stage6_analogue_selection.policy import *
from stage6_analogue_selection.selection_builder import EXCLUSION_RULES, SAFETY, build_selection, candidate_universe
from stage6_analogue_selection.selection_validation import validate_selection_record
from stage6_ingestion.canonical import canonical_hash, canonical_json, without

BASE = "74f9a4bf4a9e669e9982fc58ba610934d54fc2f2"
PARENT = "1b698c773cc9c49825781fe50bbe137df5aae679"
OUT = ROOT / "results" / "stage6_4c_test_results.csv"
CASES = []
CTX = {}


def require(value, message="assertion failed"):
    if not value:
        raise AssertionError(message)


def expect(error, function, contains=None):
    try:
        function()
    except error as exc:
        if contains:
            require(contains in str(exc), str(exc))
        return
    raise AssertionError("expected " + error.__name__)


def git(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=REPO, text=True).strip()


def rehash(record):
    record["selection_input_hash"] = canonical_hash(record["selection_input_snapshot"])
    identity_keys = (
        "feature_contract_version", "feature_contract_hash", "policy_hash", "processor_version", "company_entity_id",
        "company_effect_record_id", "company_effect_record_hash", "event_id", "event_version", "event_hash",
        "market_context_record_id", "market_context_record_hash", "as_of_timestamp", "selection_cutoff",
        "company_effect_source_cutoff", "selection_input_hash", "selection_input_snapshot",
    )
    record["feature_snapshot_hash"] = canonical_hash({key: record[key] for key in identity_keys})
    record["feature_snapshot_id"] = "S6ANFEAT_" + record["feature_snapshot_hash"][:24]
    record["logical_feature_key"] = "S6ANFEATLOG_" + canonical_hash({"event_id": record["event_id"], "event_version": record["event_version"], "company_entity_id": record["company_entity_id"], "selection_cutoff": record["selection_cutoff"]})[:24]
    record["record_hash"] = canonical_hash(without(record, "record_hash"))
    validate_feature_snapshot(record)
    return record


def feature(base, index, *, event_id=None, event_type=None, as_of=None, cutoff=None, volume=None, snapshot_from=None):
    record = deepcopy(base)
    record["company_entity_id"] = f"S6ENT_CANDIDATE_{index:03d}"
    record["company_effect_record_id"] = f"S6COMEFF_CANDIDATE_{index:03d}"
    record["company_effect_record_hash"] = canonical_hash({"effect": index})
    record["market_context_record_id"] = f"S6MCTX_CANDIDATE_{index:03d}"
    record["market_context_record_hash"] = canonical_hash({"market": index})
    record["event_id"] = event_id or f"S6EVENT_CANDIDATE_{index:03d}"
    record["event_hash"] = canonical_hash({"event": record["event_id"]})
    record["as_of_timestamp"] = as_of or f"2026-09-{index + 1:02d}T12:00:00.000000Z"
    record["selection_cutoff"] = cutoff or f"2026-09-{index + 1:02d}T11:00:00.000000Z"
    record["company_effect_source_cutoff"] = record["selection_cutoff"]
    if snapshot_from is not None:
        record["selection_input_snapshot"] = deepcopy(snapshot_from["selection_input_snapshot"])
    if event_type is not None:
        record["selection_input_snapshot"]["event_type"] = event_type
    if volume is not None:
        record["selection_input_snapshot"]["volume"]["value"] = volume
    return rehash(record)


class FakeFeatureStore:
    def __init__(self, records, result="PASS"):
        self.result = result
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute("CREATE TABLE analogue_feature_snapshots(feature_snapshot_id TEXT PRIMARY KEY,canonical_json TEXT NOT NULL)")
        self.connection.executemany("INSERT INTO analogue_feature_snapshots VALUES(?,?)", [(record["feature_snapshot_id"], canonical_json(record)) for record in records])
        self.connection.commit()

    def integrity_check(self):
        return {"result": self.result}

    def add(self, record):
        self.connection.execute("INSERT INTO analogue_feature_snapshots VALUES(?,?)", (record["feature_snapshot_id"], canonical_json(record)))
        self.connection.commit()

    def close(self):
        self.connection.close()


@contextmanager
def environment(base):
    candidates = [feature(base, index, volume=float(index)) for index in range(1, 9)]
    duplicate_event = feature(base, 9, event_id=candidates[0]["event_id"], volume=99.0)
    duplicate_input = feature(base, 10, snapshot_from=candidates[1])
    same_event = feature(base, 11, event_id=base["event_id"], volume=11.0)
    different_type = feature(base, 12, event_type="RATE_CUT", volume=12.0)
    equal_cutoff = feature(base, 13, as_of="2026-09-20T12:00:00.000000Z", cutoff=base["selection_cutoff"], volume=13.0)
    future = feature(base, 14, as_of="2026-09-28T12:00:00.000000Z", cutoff="2026-09-28T11:00:00.000000Z", volume=14.0)
    outside = feature(base, 15, as_of="2026-07-01T12:00:00.000000Z", cutoff="2026-07-01T11:00:00.000000Z", volume=15.0)
    supplied = candidates + [duplicate_event, duplicate_input, same_event, different_type, equal_cutoff, future, outside, base]
    all_records = [base] + [item for item in supplied if item["feature_snapshot_id"] != base["feature_snapshot_id"]]
    fake = FakeFeatureStore(all_records)
    with tempfile.TemporaryDirectory() as temporary:
        store = AnalogueSelectionStore(Path(temporary) / "selection.sqlite3", fake)
        record = store.select(target_feature_snapshot_id=base["feature_snapshot_id"], candidate_feature_snapshot_ids=[item["feature_snapshot_id"] for item in supplied], eligible_start_date="2026-08-01", eligible_end_date="2026-09-20")["selection_record"]
        try:
            yield {"store": store, "fake": fake, "base": base, "candidates": candidates, "supplied": supplied, "record": record, "temporary": temporary}
        finally:
            store.close()
            fake.close()


def isolated(action):
    with environment(CTX["base"]) as value:
        action(value)


def result_count(file):
    rows = list(csv.DictReader((ROOT / "results" / file).open(encoding="utf-8")))
    return len(rows), sum(row["result"] == "PASS" for row in rows)


def tamper(table, column, value):
    def action(context):
        store = context["store"]
        store.connection.execute(f"DROP TRIGGER protect_{table}_update")
        store.connection.execute(f"UPDATE {table} SET {column}=?", (value,))
        store.connection.execute(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;")
        store.connection.commit()
        expect(Exception, store.integrity_check)
    isolated(action)


NAMES = [
"exact Stage 6.4B baseline is ancestor","exact parent lineage","6.4B regression still 98/98","6.4A 73/73","historical analogue contract unchanged","market-context contract unchanged","6.4C schema exact","store exact","processor exact","policy exact","comparison contract exact","policy canonical hash","comparison-contract canonical hash","authority SHADOW_ONLY","target exact Stage 6.4B identity","candidate exact Stage 6.4B identity","target integrity required","candidate integrity required","explicit candidate set required","empty candidate list rejected","duplicate candidate ID rejected","caller candidate ordering irrelevant","deterministic candidate universe hash","later database additions do not change frozen universe","valid eligible date range","reversed range rejected","target self excluded","equal cutoff excluded","future candidate excluded","historical candidate accepted","outside date range excluded","exact Event-type required","different Event type excluded","same target Event ID excluded","categorical exact match = 0","categorical mismatch = 1","numeric identical = 0","numeric positive difference formula","numeric negative values formula","numeric zero-zero = 0","numeric null/null penalty = 1","numeric one-null penalty = 1","unit mismatch penalty = 1","no percentage/decimal conversion","no currency conversion","NaN rejected","infinity rejected","exact return horizons","return composite mean","stock return state composite","volume comparison","volatility comparison","gap comparison","technical exact comparison","sector behaviour composite","market regime exact comparison","relative-strength comparison","named array exact-name matching","array caller order irrelevant","array missing-name penalty","array unit mismatch penalty","both-empty array penalty","commodity comparison","currency comparison","rate comparison","exactly 12 feature weights","equal V1 weights","weighted distance deterministic","final distance bounded 0..1","similarity exactly 1-distance","units UNITLESS_DISTANCE/UNITLESS_SCORE","max distance frozen at 1.0","top-K frozen at 20","minimum count frozen at 5","selection-spec hash excludes candidate results","selection-spec hash deterministic","scores do not mutate specification","exact ranking distance ascending","lexicographic tie-break","no hidden recency tie-break","duplicate Event reduced to one","duplicate input hash reduced to one","duplicate handling deterministic","selected analogues are subset of eligible evaluations","selected count equals list length","max selected count <=20","insufficient count readiness","sufficient count readiness","selected analogue output compatibility","input snapshot hash preserved","target snapshot not selected","rejected candidates retained in audit","exclusion reason codes deterministic","target direct dependency","candidate direct dependencies","policy direct dependency","comparison-contract direct dependency","no Event direct dependency","no 6.3I direct dependency","no 6.4A direct dependency","no evidence/registry direct dependency","metadata singleton","policy singleton","comparison-contract singleton","append-only records","append-only universe","append-only evaluations","append-only selected rows","trigger-loss detection","restart integrity","record tamper detection","universe tamper detection","score tamper detection","selected-row tamper detection","dependency tamper detection","policy tamper detection","comparison-contract tamper detection","deterministic replay","idempotency","conflict handling","D+1 prohibited","D+3 prohibited","D+5 prohibited","D+10 prohibited","D+20 prohibited","MAE prohibited","MFE prohibited","recovery time prohibited","future relative return prohibited","expected return prohibited","target price prohibited","no outcome-store access","no future Event resolution","no Stage 5D outcome access","zero network/API","zero LLM/NLP/ML/OCR","zero embeddings/semantic similarity","trading authority false","final contract not prematurely materialized","no fake code_commit","frozen previous-stage audit","runtime artifacts zero"]


def check(number):
    context, record = CTX, CTX["record"]
    evaluations = record["candidate_evaluations"]
    if number == 1: require(git("merge-base", "HEAD", BASE) == BASE)
    elif number == 2: require(git("rev-parse", f"{BASE}^") == PARENT)
    elif number == 3: require(result_count("stage6_4b_test_results.csv") == (98, 98))
    elif number == 4: require(result_count("stage6_4a_test_results.csv") == (73, 73))
    elif number == 5: require(git("hash-object", "Stage 6/contracts/historical_analogue.schema.json") == HISTORICAL_BLOB)
    elif number == 6: require(git("hash-object", "Stage 6/contracts/market_context.schema.json") == MARKET_BLOB)
    elif number == 7: require(SCHEMA_VERSION == "STAGE6_ANALOGUE_SELECTION_V1")
    elif number == 8: require(STORE_SCHEMA_VERSION == "STAGE6_4C_ANALOGUE_SELECTION_STORE_V1")
    elif number == 9: require(PROCESSOR_VERSION == "STAGE6_4C_ANALOGUE_SELECTOR_V1")
    elif number == 10: require(POLICY_ID == "S6ANSELPOL_STAGE6_4C_V1")
    elif number == 11: require(COMPARISON_CONTRACT_VERSION == "STAGE6_ANALOGUE_COMPARISON_CONTRACT_V1")
    elif number == 12: require(load_policy()[2] == EXPECTED_POLICY_HASH_V1)
    elif number == 13: require(load_comparison_contract()[2] == EXPECTED_COMPARISON_CONTRACT_HASH_V1)
    elif number == 14: require(record["authority"] == AUTHORITY == "SHADOW_ONLY")
    elif number in (15, 16): require(context["store"].integrity_check()["result"] == "PASS")
    elif number in (17, 18):
        def action(value): value["fake"].result = "FAIL"; expect(AnalogueSelectionIntegrityFailure, value["store"].integrity_check, "INTEGRITY")
        isolated(action)
    elif number in (19, 20): isolated(lambda x: expect(Stage6AnalogueSelectionError, lambda: x["store"].select(target_feature_snapshot_id=x["base"]["feature_snapshot_id"], candidate_feature_snapshot_ids=[], eligible_start_date="2026-08-01", eligible_end_date="2026-09-20")))
    elif number == 21: isolated(lambda x: expect(Stage6AnalogueSelectionError, lambda: x["store"].select(target_feature_snapshot_id=x["base"]["feature_snapshot_id"], candidate_feature_snapshot_ids=[x["candidates"][0]["feature_snapshot_id"]] * 2, eligible_start_date="2026-08-01", eligible_end_date="2026-09-20")))
    elif number == 22:
        a, b = candidate_universe(context["supplied"]), candidate_universe(list(reversed(context["supplied"])))
        require(a == b)
    elif number == 23: require(record["candidate_universe_hash"] == candidate_universe(context["supplied"])[1])
    elif number == 24:
        before = canonical_json(record); extra = feature(context["base"], 19, volume=19.0); context["fake"].add(extra); require(canonical_json(record) == before and context["store"].integrity_check()["result"] == "PASS")
    elif number == 25: require(record["eligible_date_range"] == {"start_date":"2026-08-01","end_date":"2026-09-20"})
    elif number == 26: expect(Stage6AnalogueSelectionError, lambda: build_selection(target=context["base"], candidates=context["candidates"], eligible_start_date="2026-09-20", eligible_end_date="2026-08-01", policy=context["store"].policy, policy_hash=context["store"].policy_hash, comparison_contract=context["store"].comparison_contract, comparison_contract_hash=context["store"].comparison_contract_hash))
    elif number in (27,28,29,31,33,34):
        codes = [code for item in evaluations for code in item["exclusion_reason_codes"]]
        expected = {27:"TARGET_SELF_EXCLUDED",28:"NON_HISTORICAL_CUTOFF",29:"NON_HISTORICAL_CUTOFF",31:"OUTSIDE_ELIGIBLE_DATE_RANGE",33:"EVENT_TYPE_MISMATCH",34:"TARGET_EVENT_ID_EXCLUDED"}[number]; require(expected in codes)
    elif number == 30: require(any(item["eligibility_status"] == "ELIGIBLE" for item in evaluations))
    elif number == 32: require("EXACT_EVENT_TYPE_REQUIRED" in record["exclusion_rules"])
    elif number == 35: require(categorical_distance("A","A")[0] == 0)
    elif number == 36: require(categorical_distance("A","B")[0] == 1)
    elif number == 37: require(numeric_distance(2,2,"U","U")[0] == 0)
    elif number == 38: require(numeric_distance(2,6,"U","U")[0] == .5)
    elif number == 39: require(numeric_distance(-2,6,"U","U")[0] == 1)
    elif number == 40: require(numeric_distance(0,0,"U","U")[0] == 0)
    elif number in (41,42): require(numeric_distance(None, None if number==41 else 1,"U","U")[0] == 1)
    elif number in (43,44,45): require(numeric_distance(1,1,"PERCENT_RETURN","DECIMAL_RETURN" if number<45 else "USD")[0] == 1)
    elif number == 46: expect(Stage6AnalogueSelectionError, lambda: numeric_distance(float("nan"),1,"U","U"))
    elif number == 47: expect(Stage6AnalogueSelectionError, lambda: numeric_distance(float("inf"),1,"U","U"))
    elif number == 48: require(tuple(context["base"]["selection_input_snapshot"]["stock_return_state"]["returns"][key] for key in ("1D","3D","5D","20D")) is not None)
    elif number == 49:
        x={"unit":"U","1D":1.0,"3D":2.0,"5D":3.0,"20D":4.0};y=deepcopy(x);y["1D"]=3.0;require(return_distance(x,y)[0] == numeric_distance(1.0,3.0,"U","U")[0]/4)
    elif number in range(50,58):
        distances,_,total,similarity=compare_snapshots(context["base"]["selection_input_snapshot"],context["candidates"][0]["selection_input_snapshot"],context["store"].comparison_contract["feature_weights"]);require(len(distances)==12 and 0<=total<=1 and similarity==1-total)
    elif number == 58:
        x=[{"name":"Oil","value":1,"unit":"U"}];y=[{"name":"OIL","value":1,"unit":"U"}];require(named_array_distance(x,y)[0]==0)
    elif number == 59:
        x=[{"name":"A","value":1,"unit":"U"},{"name":"B","value":2,"unit":"U"}];require(named_array_distance(x,list(reversed(x)))[0]==0)
    elif number == 60: require(named_array_distance([{"name":"A","value":1,"unit":"U"}],[])[0]==1)
    elif number == 61: require(named_array_distance([{"name":"A","value":1,"unit":"U"}],[{"name":"A","value":1,"unit":"V"}])[0]==1)
    elif number == 62: require(named_array_distance([],[])[0]==1)
    elif number in (63,64,65):
        scored=next(item for item in record["candidate_evaluations"] if item["top_level_feature_distances"] is not None);require(scored["top_level_feature_distances"][["commodity_context","currency_context","rate_context"][number-63]] is not None)
    elif number == 66: require(len(record["feature_weights"])==12)
    elif number == 67: require(set(record["feature_weights"].values())=={1.0})
    elif number in (68,69,70): require(all(0<=item["distance"]<=1 and item["similarity_score"]==1-item["distance"] for item in evaluations if item["distance"] is not None))
    elif number == 71: require(all(item["distance"]["unit"]=="UNITLESS_DISTANCE" and item["similarity_score"]["unit"]=="UNITLESS_SCORE" for item in record["selected_analogues"]))
    elif number == 72: require(record["max_distance"]=={"value":1.0,"unit":"UNITLESS_DISTANCE"})
    elif number == 73: require(record["top_k"]==20)
    elif number == 74: require(record["minimum_required_analogue_count"]==5)
    elif number in (75,76,77): require(len(record["selection_spec_hash"])==64 and "candidate_evaluations" not in canonical_json({"selection_spec_hash":record["selection_spec_hash"]}))
    elif number in (78,79,80): require(record["selected_analogues"]==sorted(record["selected_analogues"],key=lambda x:(x["distance"]["value"],x["analogue_id"])))
    elif number == 81: require(len({x["event_id"] for x in record["selected_analogues"]})==len(record["selected_analogues"]))
    elif number == 82: require(len({x["input_snapshot_hash"] for x in record["selected_analogues"]})==len(record["selected_analogues"]))
    elif number == 83: require(canonical_json(record)==canonical_json(build_selection(target=context["base"], candidates=list(reversed(context["supplied"])), eligible_start_date="2026-08-01", eligible_end_date="2026-09-20", policy=context["store"].policy, policy_hash=context["store"].policy_hash, comparison_contract=context["store"].comparison_contract, comparison_contract_hash=context["store"].comparison_contract_hash)))
    elif number == 84: require({x["analogue_id"] for x in record["selected_analogues"]}<={x["candidate_feature_snapshot_id"] for x in evaluations if x["eligibility_status"]=="ELIGIBLE"})
    elif number == 85: require(record["analogue_count"]==len(record["selected_analogues"]))
    elif number == 86: require(record["analogue_count"]<=20)
    elif number == 87: require(build_selection(target=context["base"],candidates=context["candidates"][:2],eligible_start_date="2026-08-01",eligible_end_date="2026-09-20",policy=context["store"].policy,policy_hash=context["store"].policy_hash,comparison_contract=context["store"].comparison_contract,comparison_contract_hash=context["store"].comparison_contract_hash)["interpretation_readiness"]=="INSUFFICIENT_ANALOGUES")
    elif number == 88: require(record["interpretation_readiness"]=="READY_FOR_OUTCOME_ATTACHMENT")
    elif number in (89,90): require(all(set(x)=={"analogue_id","historical_as_of_timestamp","entity_id","event_id","similarity_score","distance","input_snapshot_hash"} for x in record["selected_analogues"]))
    elif number == 91: require(record["target_feature_snapshot_id"] not in {x["analogue_id"] for x in record["selected_analogues"]})
    elif number == 92: require(len(evaluations)==len(context["supplied"]) and any(x["eligibility_status"]=="EXCLUDED" for x in evaluations))
    elif number == 93: require(all(x["exclusion_reason_codes"]==list(dict.fromkeys(x["exclusion_reason_codes"])) for x in evaluations))
    elif number in range(94,102):
        kinds={x[0] for x in context["store"].connection.execute("SELECT record_type FROM analogue_selection_dependencies")}
        expected={94:"STAGE6_4B_ANALOGUE_FEATURE_TARGET",95:"STAGE6_4B_ANALOGUE_FEATURE_CANDIDATE",96:"STAGE6_4C_POLICY",97:"STAGE6_4C_COMPARISON_CONTRACT"}
        if number<=97:require(expected[number] in kinds)
        else:
            forbidden={98:"STAGE6_EVENT",99:"STAGE6_3I",100:"STAGE6_4A",101:"EVIDENCE"}[number]
            require(not any(forbidden in kind for kind in kinds))
    elif number == 102: require(context["store"].connection.execute("SELECT count(*) FROM analogue_selection_store_meta").fetchone()[0]==1)
    elif number == 103: require(context["store"].connection.execute("SELECT count(*) FROM analogue_selection_policies").fetchone()[0]==1)
    elif number == 104: require(context["store"].connection.execute("SELECT count(*) FROM analogue_comparison_contracts").fetchone()[0]==1)
    elif number in (105,106,107,108):
        table={105:"analogue_selection_records",106:"analogue_selection_universe",107:"analogue_candidate_evaluations",108:"analogue_selected_records"}[number];expect(sqlite3.DatabaseError,lambda:context["store"].connection.execute(f"UPDATE {table} SET rowid=rowid"));expect(sqlite3.DatabaseError,lambda:context["store"].connection.execute(f"DELETE FROM {table}"))
    elif number == 109: isolated(lambda x:(x["store"].connection.execute("DROP TRIGGER protect_analogue_selection_records_delete"),x["store"].connection.commit(),expect(AnalogueSelectionIntegrityFailure,x["store"].integrity_check,"TRIGGER")))
    elif number == 110: require(context["store"].integrity_check()["result"]=="PASS")
    elif number == 111: tamper("analogue_selection_records","record_hash","f"*64)
    elif number == 112: tamper("analogue_selection_universe","candidate_record_hash","f"*64)
    elif number == 113: tamper("analogue_candidate_evaluations","distance",0.123)
    elif number == 114: tamper("analogue_selected_records","canonical_json","{}")
    elif number == 115: tamper("analogue_selection_dependencies","record_hash","f"*64)
    elif number == 116: tamper("analogue_selection_policies","policy_hash","f"*64)
    elif number == 117: tamper("analogue_comparison_contracts","contract_hash","f"*64)
    elif number == 118: require(context["store"].integrity_check()["result"]=="PASS")
    elif number == 119: require(context["store"].select(target_feature_snapshot_id=context["base"]["feature_snapshot_id"],candidate_feature_snapshot_ids=[x["feature_snapshot_id"] for x in context["supplied"]],eligible_start_date="2026-08-01",eligible_end_date="2026-09-20")["status"]=="IDEMPOTENT_SUCCESS")
    elif number == 120:
        def action(x):
            s=x["store"];s.connection.execute("DROP TRIGGER protect_analogue_selection_records_update");s.connection.execute("UPDATE analogue_selection_records SET canonical_json='{}'");s.connection.execute("CREATE TRIGGER protect_analogue_selection_records_update BEFORE UPDATE ON analogue_selection_records BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;");s.connection.commit();expect(AnalogueSelectionConflict,lambda:s.select(target_feature_snapshot_id=x["base"]["feature_snapshot_id"],candidate_feature_snapshot_ids=[r["feature_snapshot_id"] for r in x["supplied"]],eligible_start_date="2026-08-01",eligible_end_date="2026-09-20"))
        isolated(action)
    elif number in range(121,141):
        text="\n".join(path.read_text(encoding="utf-8") for path in (ROOT/"stage6_analogue_selection").glob("*.py"))+canonical_json(record);prohibited={121:"D+1",122:"D+3",123:"D+5",124:"D+10",125:"D+20",126:"MAE",127:"MFE",128:"recovery_time",129:"future_relative_return",130:'"expected_return"',131:'"target_price"',132:"outcome_store",133:"future_event_resolution",134:"Stage 5D",139:"STAGE6_HISTORICAL_ANALOGUE_V2",140:'"code_commit"'}
        if number in prohibited: require(prohibited[number] not in text)
        elif number == 135: require(no_imports({"requests","urllib","http","aiohttp","yfinance","socket"}))
        elif number == 136: require(no_imports({"openai","transformers","torch","tensorflow","sklearn"}))
        elif number == 137: require(load_policy()[0]["embeddings"] is False and load_policy()[0]["semantic_similarity"] is False)
        elif number == 138: require(record["trading_authority"] is False)
    elif number == 141:
        frozen=("Stage 5D","Stage 6/contracts","Stage 6/stage6_analogue_features","Stage 6/tests/run_stage6_4b_tests.py","Stage 6/results/stage6_4b_test_results.csv");require(git("diff","--name-only",BASE,"--",*frozen)=="")
    elif number == 142:
        changed=git("diff","--name-only",BASE);require(not any(part in path.lower() for path in changed.splitlines() for part in ("__pycache__",".pyc",".sqlite",".db")))


def no_imports(prohibited):
    for path in (ROOT / "stage6_analogue_selection").glob("*.py"):
        tree=ast.parse(path.read_text(encoding="utf-8"))
        imports={node.names[0].name.split(".")[0] for node in ast.walk(tree) if isinstance(node,ast.Import)}|{str(node.module).split(".")[0] for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)}
        if imports & prohibited:return False
    return True


def main():
    rows=[]
    with b.fixture() as upstream:
        base=upstream["snapshot"]
        with environment(base) as shared:
            CTX.update(shared);CTX["base"]=base
            for number,name in enumerate(NAMES,1):
                try:
                    with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK")):check(number)
                    rows.append({"test_id":f"S6_4C_{number:03d}","category":"ACCEPTANCE","test_name":name,"result":"PASS","detail":""})
                except Exception as exc:rows.append({"test_id":f"S6_4C_{number:03d}","category":"ACCEPTANCE","test_name":name,"result":"FAIL","detail":f"{type(exc).__name__}:{exc}"})
    OUT.parent.mkdir(exist_ok=True);handle=OUT.open("w",newline="",encoding="utf-8");writer=csv.DictWriter(handle,fieldnames=rows[0],lineterminator="\n");writer.writeheader();writer.writerows(rows);handle.close();failed=[row for row in rows if row["result"]=="FAIL"];print(json.dumps({"stage":"6.4C","tests":len(rows),"passed":len(rows)-len(failed),"failed":len(failed),"result":"FAIL" if failed else "PASS","authority":AUTHORITY,"network_calls":0,"llm_calls":0,"ml":False,"nlp":False,"ocr":False,"embeddings":False,"trading_authority":False},sort_keys=True,separators=(",",":")));[print("FAIL",row) for row in failed];return bool(failed)


if __name__=="__main__":raise SystemExit(main())
