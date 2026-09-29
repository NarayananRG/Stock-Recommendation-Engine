import ast
import csv
import json
import sqlite3
import subprocess
import sys
import tempfile

from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from stage6_ingestion.canonical import canonical_hash, canonical_json, without
from stage6_thesis_seed.thesis_seed_store import ThesisSeedStore
from stage6_trade_thesis.trade_thesis_store import TradeThesisStore
from stage6_thesis_review_input.review_input_store import ThesisReviewInputStore
from stage6_thesis_review_assessment.review_assessment_store import ThesisReviewAssessmentStore
from stage6_trade_thesis_version.trade_thesis_version_store import TradeThesisVersionStore
from stage6_recursive_thesis.errors import *
from stage6_recursive_thesis.policy import *
from stage6_recursive_thesis.recursive_review_builder import ASSESSMENT_SAFETY, REVIEW_SAFETY, build_assessment, build_review_snapshot
from stage6_recursive_thesis.recursive_review_validation import ASSESSMENT_FIELDS, REVIEW_FIELDS, validate_assessment, validate_review_snapshot, validate_structured
from stage6_recursive_thesis.recursive_thesis_builder import VERSION_SAFETY, build_version_wrapper, version_inputs
from stage6_recursive_thesis.recursive_thesis_store import TABLES, RecursiveThesisStore
from stage6_recursive_thesis.recursive_thesis_validation import WRAPPER_FIELDS, PRESERVED, validate_recursive_thesis, validate_version_wrapper

OUT = ROOT / "results/stage6_6f_test_results.csv"
CASES = []
CTX = {}


def case(group, name, function):
    CASES.append((group, name, function))


def require(value, message="assertion failed"):
    if not value:
        raise AssertionError(message)


def expect(error, function, contains=None):
    try:
        function()
    except error as exc:
        if contains:
            require(contains in str(exc))
        return
    raise AssertionError(f"expected {error}")


def changed(value, path, replacement):
    result = deepcopy(value)
    current = result
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = replacement
    return result


def git(*args):
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def source():
    return json.loads((ROOT / "fixtures/stage6_6a/initial_thesis_seed_examples.json").read_text(encoding="utf-8"))["examples"][0]


def result_count(stage):
    with (ROOT / "results" / f"stage6_{stage}_test_results.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    require(all(row["result"] == "PASS" for row in rows))
    return len(rows)


def prior_count():
    stages = ("1a", "1b", "1c", "2a", "2b", "2c", "2d", "2e", "2f", "3a", "3b", "3c", "3d", "3e", "3f", "3g", "3h", "3i", "4a", "4b", "4c", "4d", "4e", "5a", "5b", "5c", "5d", "6a", "6b", "6c", "6d")
    return sum(result_count(stage) for stage in stages)


def architecture_result():
    output = subprocess.check_output([sys.executable, str(ROOT / "scripts/validate_stage6_0.py")], cwd=REPO, text=True)
    return json.loads(output)


class EvidenceStore:
    def __init__(self, values):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("CREATE TABLE ingestion_records(record_id TEXT PRIMARY KEY,canonical_json TEXT NOT NULL)")
        self.connection.executemany("INSERT INTO ingestion_records VALUES(?,?)", [(value["evidence_id"], canonical_json(value)) for value in values])
        self.connection.commit()
        self.passes = True

    def integrity_check(self):
        return {"result": "PASS" if self.passes else "FAIL"}

    def close(self):
        self.connection.close()


def evidence(identity, retrieved):
    value = {"schema_version": "STAGE6_EVIDENCE_V2", "record_kind": "EVIDENCE", "evidence_id": identity, "retrieved_timestamp_utc": retrieved, "record_hash": ""}
    value["record_hash"] = canonical_hash(without(value, "record_hash"))
    return value


def support(snapshot, identity):
    return next(item for item in snapshot["direct_input_bindings"] if item["record_id"] == identity)


def assertion(binding, assessment):
    core = {"assessment": assessment, "reason_code": "NEW_EVIDENCE", "supporting_bindings": [binding]}
    return {"assertion_id": "S6THRECURASSERT_" + canonical_hash(core)[:24], **core}


def assessment6d(binding, assessment):
    core = {"assessment": assessment, "reason_code": "NEW_EVIDENCE", "supporting_bindings": [binding]}
    return {"assertion_id": "S6THASSERT_" + canonical_hash(core)[:24], **core}


def invalidations(thesis, binding=None, mode="NOT_TRIGGERED"):
    statuses = ["NOT_TRIGGERED"] * len(thesis["invalidation_conditions"])
    if mode in {"TRIGGERED", "NOT_EVALUATED"}:
        statuses[0] = mode
    return [{"condition_index": index, "condition_text": text, "evaluation_status": statuses[index], "supporting_bindings": [binding] if statuses[index] == "TRIGGERED" else []} for index, text in enumerate(thesis["invalidation_conditions"])]


def request(source_type, record_id, cutoff, evidence_id, mode):
    current = CTX["v2"] if source_type == "STAGE6_6E" else (CTX["v3"] if record_id == CTX["r3"]["version_record"]["version_record_id"] else CTX["v4"])
    binding = {"record_type": "STAGE6_EVIDENCE_V2", "record_id": evidence_id, "record_hash": CTX["evidence_by_id"][evidence_id]["record_hash"]}
    assertions = [] if mode == "NOT_EVALUATED" else [assertion(binding, mode)]
    return {"current_thesis_source": source_type, "current_version_record_id": record_id, "review_cutoff": cutoff, "evidence_ids": [evidence_id], "company_effect_ids": [], "invalidation_assessments": invalidations(current, binding, "NOT_EVALUATED" if mode == "NOT_EVALUATED" else "NOT_TRIGGERED"), "change_assertions": assertions}


def bootstrap(folder):
    path = Path(folder)
    seed_store = ThesisSeedStore(path / "seed.sqlite3")
    seed = seed_store.freeze(source())["initial_thesis_seed"]
    thesis_store = TradeThesisStore(path / "thesis.sqlite3", seed_store)
    v1 = thesis_store.materialize(seed["seed_record_id"])["trade_thesis"]
    values = [
        evidence("S6EV_R1", "2026-09-29T11:00:00Z"),
        evidence("S6EV_R2", "2026-09-29T12:30:00Z"),
        evidence("S6EV_R3", "2026-09-29T13:30:00Z"),
        evidence("S6EV_R4", "2026-09-29T14:30:00Z"),
        evidence("S6EV_FUTURE", "2026-09-29T16:30:00Z"),
    ]
    evidence_store = EvidenceStore(values)
    review_store = ThesisReviewInputStore(path / "review.sqlite3", thesis_store, evidence_store=evidence_store)
    snapshot = review_store.freeze(thesis_id=v1["thesis_id"], review_cutoff="2026-09-29T12:00:00Z", evidence_ids=["S6EV_R1"], company_effect_ids=[])["review_input_snapshot"]
    binding = support(snapshot, "S6EV_R1")
    assessment_store = ThesisReviewAssessmentStore(path / "assessment.sqlite3", review_store, thesis_store)
    assessment = assessment_store.assess(review_snapshot_id=snapshot["review_snapshot_id"], invalidation_assessments=invalidations(v1), change_assertions=[assessment6d(binding, "NON_MATERIAL")])["review_assessment"]
    version_store = TradeThesisVersionStore(path / "v2.sqlite3", assessment_store, review_store, thesis_store)
    v2_result = version_store.materialize(assessment["assessment_id"])
    recursive_store = RecursiveThesisStore(path / "recursive.sqlite3", version_store, evidence_store=evidence_store)
    return {"seed_store": seed_store, "thesis_store": thesis_store, "evidence_store": evidence_store, "review_store": review_store, "assessment_store": assessment_store, "version_store": version_store, "recursive_store": recursive_store, "v1": v1, "v2_result": v2_result, "evidence_by_id": {item["evidence_id"]: item for item in values}}


for label, actual, expected in (
    ("review schema", REVIEW_SCHEMA, "STAGE6_RECURSIVE_THESIS_REVIEW_INPUT_V1"),
    ("assessment schema", ASSESSMENT_SCHEMA, "STAGE6_RECURSIVE_THESIS_REVIEW_ASSESSMENT_V1"),
    ("wrapper", WRAPPER_SCHEMA, "STAGE6_6F_RECURSIVE_TRADE_THESIS_VERSION_RECORD_V1"),
    ("store", STORE_SCHEMA, "STAGE6_6F_RECURSIVE_THESIS_STORE_V1"),
    ("processor", PROCESSOR, "STAGE6_6F_RECURSIVE_THESIS_REVIEW_ENGINE_V1"),
    ("policy", POLICY_ID, "S6THRECPOL_STAGE6_6F_V1"),
    ("contract", CONTRACT_VERSION, "STAGE6_RECURSIVE_THESIS_REVIEW_CONTRACT_V1"),
    ("semantics", SEMANTICS, "STAGE6_THESIS_MATERIAL_CHANGE_RULES_V1"),
    ("semantic commit", SEMANTIC_COMMIT, "3b094f4167e78de7699742080e0a163e7550bc0e"),
    ("baseline", BASELINE, "11f90c3263476f9b396b2beefebcd4f3ddb147b7"),
    ("authority", AUTHORITY, "SHADOW_ONLY"),
):
    case("IDENTITY", label, lambda actual=actual, expected=expected: require(actual == expected))
case("IDENTITY", "baseline ancestry", lambda: require(git("merge-base", "HEAD", BASELINE) == BASELINE))
case("IDENTITY", "baseline parent", lambda: require(git("rev-parse", BASELINE + "^") == "16346dee8270135a7f43f1140f920531d33f6cbd"))
case("IDENTITY", "branch", lambda: require(git("branch", "--show-current") == "stage6-persistent-thesis"))
case("IDENTITY", "trade thesis blob", lambda: require(git_blob(ROOT / "contracts/trade_thesis.schema.json") == THESIS_BLOB))
case("IDENTITY", "policy hash", lambda: require(load_policy()[2] == EXPECTED_POLICY_HASH))
case("IDENTITY", "contract hash", lambda: require(load_contract()[2] == EXPECTED_CONTRACT_HASH))
case("IDENTITY", "fixture", lambda: require(json.loads((ROOT / "fixtures/stage6_6f/recursive_thesis_examples.json").read_text())["fixture_version"] == "STAGE6_6F_FIXTURES_V1"))
case("REGRESSION", "Stage 6.6E 259", lambda: require(result_count("6e") == 259))
case("REGRESSION", "prior 3272", lambda: require(prior_count() == 3272))
case("REGRESSION", "combined 3531", lambda: require(prior_count() + result_count("6e") == 3531))
case("REGRESSION", "Stage 6.0C", lambda: require(architecture_result()["result"] == "PASS" and architecture_result()["schemas_parsed"] == 10))
case("SOURCE", "enum", lambda: require(SOURCE_TYPES == {"STAGE6_6E", "STAGE6_6F"}))
case("SOURCE", "explicit V2", lambda: require(CTX["r3"]["version_record"]["current_thesis_source"] == "STAGE6_6E"))
case("SOURCE", "explicit V3", lambda: require(CTX["r4"]["version_record"]["current_thesis_source"] == "STAGE6_6F"))
case("SOURCE", "bad enum", lambda: expect(Stage6RecursiveThesisError, lambda: CTX["store"].review(**request("OTHER", CTX["v2_record_id"], "2026-09-29T12:45:00Z", "S6EV_R2", "NON_MATERIAL"))))
case("SOURCE", "missing record", lambda: expect(Stage6RecursiveThesisError, lambda: CTX["store"].review(**request("STAGE6_6F", "", "2026-09-29T15:30:00Z", "S6EV_R4", "NON_MATERIAL"))))

case("LIFECYCLE", "V2 to V3", lambda: require(CTX["r3"]["status"] == "CREATED" and CTX["v3"]["version"] == 3))
case("LIFECYCLE", "V3 to V4", lambda: require(CTX["r4"]["status"] == "CREATED" and CTX["v4"]["version"] == 4))
case("LIFECYCLE", "V4 indeterminate", lambda: require(CTX["ri"]["status"] == "WITHHELD_INDETERMINATE"))
case("LIFECYCLE", "V5 absent", lambda: require(CTX["store"].connection.execute("SELECT count(*) FROM recursive_thesis_versions WHERE version=5").fetchone()[0] == 0))
case("LIFECYCLE", "indeterminate snapshot persisted", lambda: require(CTX["store"].connection.execute("SELECT count(*) FROM recursive_review_snapshots WHERE review_snapshot_id=?", (CTX["ri"]["review_snapshot"]["review_snapshot_id"],)).fetchone()[0] == 1))
case("LIFECYCLE", "indeterminate assessment persisted", lambda: require(CTX["store"].connection.execute("SELECT count(*) FROM recursive_review_assessments WHERE assessment_id=?", (CTX["ri"]["assessment"]["assessment_id"],)).fetchone()[0] == 1))
case("LIFECYCLE", "stable thesis ID", lambda: require(CTX["v2"]["thesis_id"] == CTX["v3"]["thesis_id"] == CTX["v4"]["thesis_id"]))
case("LIFECYCLE", "V3 previous hash", lambda: require(CTX["v3"]["previous_version_hash"] == CTX["v2"]["record_hash"]))
case("LIFECYCLE", "V4 previous hash", lambda: require(CTX["v4"]["previous_version_hash"] == CTX["v3"]["record_hash"]))
case("LIFECYCLE", "V3 history", lambda: require([item["version"] for item in CTX["v3"]["change_history"]] == [1, 2, 3]))
case("LIFECYCLE", "V4 history", lambda: require([item["version"] for item in CTX["v4"]["change_history"]] == [1, 2, 3, 4]))
case("LIFECYCLE", "old V4 history", lambda: require(CTX["v4"]["change_history"][:-1] == CTX["v3"]["change_history"]))
case("LIFECYCLE", "semantic commit V3", lambda: require(CTX["v3"]["code_commit"] == SEMANTIC_COMMIT))
case("LIFECYCLE", "semantic commit V4", lambda: require(CTX["v4"]["code_commit"] == SEMANTIC_COMMIT))
case("LIFECYCLE", "V3 valid", lambda: require(validate_version_wrapper(CTX["r3"]["version_record"], "STAGE6_6E", CTX["v2_record_id"], CTX["v2"], CTX["r3"]["review_snapshot"], CTX["r3"]["assessment"], CTX["store"].policy_hash, CTX["store"].contract_hash)))
case("LIFECYCLE", "V4 valid", lambda: require(validate_version_wrapper(CTX["r4"]["version_record"], "STAGE6_6F", CTX["r3"]["version_record"]["version_record_id"], CTX["v3"], CTX["r4"]["review_snapshot"], CTX["r4"]["assessment"], CTX["store"].policy_hash, CTX["store"].contract_hash)))
case("LIFECYCLE", "invalidated explicit review", lambda: require(CTX["invalidated_v3"]["thesis_status"] == "THESIS_INVALIDATED" and CTX["invalidated_v4"]["version"] == 4))
case("LIFECYCLE", "invalidated not closed", lambda: require(CTX["invalidated_v3"]["thesis_status"] != "CLOSED"))
case("LIFECYCLE", "no resurrection rule", lambda: require(CTX["invalidated_v4"]["thesis_status"] == "THESIS_UNCHANGED"))

for version in ("v3", "v4"):
    for field in PRESERVED:
        case("PRESERVE", version + " " + field, lambda version=version, field=field: require(CTX[version][field] == CTX["v2"][field]))
    case("PRESERVE", version + " stop", lambda version=version: require(CTX[version]["current_stop"] == CTX["v2"]["current_stop"]))
    case("PRESERVE", version + " target", lambda version=version: require(CTX[version]["current_target"] == CTX["v2"]["current_target"]))

for result_name in ("r3", "r4"):
    case("INPUTS", result_name + " three", lambda result_name=result_name: require(len(CTX[result_name]["trade_thesis"]["input_records"]) == 3))
    case("INPUTS", result_name + " history equal", lambda result_name=result_name: require(CTX[result_name]["trade_thesis"]["change_history"][-1]["input_records"] == CTX[result_name]["trade_thesis"]["input_records"]))
    for forbidden in sorted(SUPPORT_TYPES):
        case("INPUTS", result_name + " no transitive " + forbidden, lambda result_name=result_name, forbidden=forbidden: require(forbidden not in {item["record_type"] for item in CTX[result_name]["trade_thesis"]["input_records"]}))

case("PIT", "zero evidence", lambda: require(CTX["store"]._evidence([], CTX["v2"]["decision_cutoff"], "2026-09-29T13:00:00Z") == []))
case("PIT", "new evidence", lambda: require(CTX["store"]._evidence(["S6EV_R2"], CTX["v2"]["decision_cutoff"], "2026-09-29T13:00:00Z")[0]["evidence_id"] == "S6EV_R2"))
case("PIT", "old evidence rejected", lambda: expect(RecursiveThesisIntegrityFailure, lambda: CTX["store"]._evidence(["S6EV_R1"], CTX["v2"]["decision_cutoff"], "2026-09-29T13:00:00Z")))
case("PIT", "future evidence rejected", lambda: expect(RecursiveThesisIntegrityFailure, lambda: CTX["store"]._evidence(["S6EV_FUTURE"], CTX["v4"]["decision_cutoff"], "2026-09-29T15:00:00Z")))
case("PIT", "equal cutoff rejected", lambda: expect(RecursiveThesisIntegrityFailure, lambda: CTX["store"].review(**request("STAGE6_6F", CTX["r4"]["version_record"]["version_record_id"], CTX["v4"]["decision_cutoff"], "S6EV_R4", "NON_MATERIAL"))))
case("PIT", "earlier cutoff rejected", lambda: expect(RecursiveThesisIntegrityFailure, lambda: CTX["store"].review(**request("STAGE6_6F", CTX["r4"]["version_record"]["version_record_id"], "2026-09-29T13:30:00Z", "S6EV_R3", "NON_MATERIAL"))))
case("VERSION", "bool rejected", lambda: expect(RecursiveThesisIntegrityFailure, lambda: validate_recursive_thesis(CTX["v3"], changed(CTX["v2"], ["version"], True), CTX["r3"]["review_snapshot"], CTX["r3"]["assessment"])))
case("VERSION", "skip rejected", lambda: expect(RecursiveThesisIntegrityFailure, lambda: validate_recursive_thesis(changed(CTX["v3"], ["version"], 4), CTX["v2"], CTX["r3"]["review_snapshot"], CTX["r3"]["assessment"])))
case("VERSION", "broken previous hash", lambda: expect(RecursiveThesisIntegrityFailure, lambda: validate_recursive_thesis(changed(CTX["v3"], ["previous_version_hash"], "0" * 64), CTX["v2"], CTX["r3"]["review_snapshot"], CTX["r3"]["assessment"])))
case("VERSION", "altered prior history", lambda: expect(RecursiveThesisIntegrityFailure, lambda: validate_recursive_thesis(changed(CTX["v4"], ["change_history", 1, "reason"], "OTHER"), CTX["v3"], CTX["r4"]["review_snapshot"], CTX["r4"]["assessment"])))
case("VERSION", "duplicate history", lambda: expect(RecursiveThesisIntegrityFailure, lambda: validate_recursive_thesis(changed(CTX["v4"], ["change_history", 2, "version"], 2), CTX["v3"], CTX["r4"]["review_snapshot"], CTX["r4"]["assessment"])))

case("RULES", "strengthened", lambda: require(CTX["v3"]["thesis_status"] == "THESIS_STRENGTHENED"))
case("RULES", "weakened", lambda: require(CTX["v4"]["thesis_status"] == "THESIS_WEAKENED"))
case("RULES", "indeterminate no target", lambda: require(CTX["ri"]["assessment"]["target_thesis_status"] is None))
for name, statuses, assertions, expected in (
    ("invalidation", ["TRIGGERED", "NOT_TRIGGERED"], ["SUPPORTIVE_MATERIAL"], "THESIS_INVALIDATED"),
    ("unevaluated", ["NOT_EVALUATED", "NOT_TRIGGERED"], ["SUPPORTIVE_MATERIAL"], None),
    ("assertion indeterminate", ["NOT_TRIGGERED", "NOT_TRIGGERED"], ["INDETERMINATE"], None),
    ("conflict", ["NOT_TRIGGERED", "NOT_TRIGGERED"], ["SUPPORTIVE_MATERIAL", "ADVERSE_MATERIAL"], None),
    ("adverse", ["NOT_TRIGGERED", "NOT_TRIGGERED"], ["ADVERSE_MATERIAL"], "THESIS_WEAKENED"),
    ("supportive", ["NOT_TRIGGERED", "NOT_TRIGGERED"], ["SUPPORTIVE_MATERIAL"], "THESIS_STRENGTHENED"),
    ("non-material", ["NOT_TRIGGERED", "NOT_TRIGGERED"], ["NON_MATERIAL"], "THESIS_UNCHANGED"),
    ("empty", ["NOT_TRIGGERED", "NOT_TRIGGERED"], [], "THESIS_UNCHANGED"),
):
    case("RULE_REPLAY", name, lambda statuses=statuses, assertions=assertions, expected=expected: require(CTX["rule_factory"](statuses, assertions)["target_thesis_status"] == expected))

for field in sorted(REVIEW_SAFETY):
    case("REVIEW_SAFETY", field, lambda field=field: require(CTX["r3"]["review_snapshot"][field] == REVIEW_SAFETY[field]))
for field in sorted(ASSESSMENT_SAFETY):
    case("ASSESSMENT_SAFETY", field, lambda field=field: require(CTX["r3"]["assessment"][field] == ASSESSMENT_SAFETY[field]))
for field in sorted(VERSION_SAFETY):
    case("VERSION_SAFETY", field, lambda field=field: require(CTX["r3"]["version_record"][field] == VERSION_SAFETY[field]))

case("HASH", "snapshot ID", lambda: require(CTX["r3"]["review_snapshot"]["review_snapshot_id"] == "S6THRECURIN_" + canonical_hash(without(CTX["r3"]["review_snapshot"], "review_snapshot_id", "record_hash"))[:24]))
case("HASH", "assessment ID", lambda: require(CTX["r3"]["assessment"]["assessment_id"] == "S6THRECURASS_" + canonical_hash(without(CTX["r3"]["assessment"], "assessment_id", "record_hash"))[:24]))
case("HASH", "wrapper ID", lambda: require(CTX["r3"]["version_record"]["version_record_id"] == "S6THRECURVER_" + canonical_hash(without(CTX["r3"]["version_record"], "version_record_id", "record_hash"))[:24]))
for name, record in (("snapshot", lambda: CTX["r3"]["review_snapshot"]), ("assessment", lambda: CTX["r3"]["assessment"]), ("wrapper", lambda: CTX["r3"]["version_record"]), ("thesis", lambda: CTX["v3"])):
    case("HASH", name, lambda record=record: require(record()["record_hash"] == canonical_hash(without(record(), "record_hash"))))

case("STORE", "integrity", lambda: require(CTX["store"].integrity_check()["result"] == "PASS"))
case("STORE", "versions two", lambda: require(CTX["store"].connection.execute("SELECT count(*) FROM recursive_thesis_versions").fetchone()[0] == 2))
case("STORE", "idempotent V3", lambda: require(CTX["store"].review(**CTX["req3"])["status"] == "IDEMPOTENT_SUCCESS"))
case("STORE", "idempotent indeterminate", lambda: require(CTX["store"].review(**CTX["reqi"])["status"] == "WITHHELD_INDETERMINATE"))
case("STORE", "fork prohibited", lambda: expect(RecursiveThesisConflict, CTX["fork_factory"]))
case("STORE", "logical conflict", lambda: expect(RecursiveThesisConflict, CTX["logical_conflict_factory"]))
case("STORE", "restart", lambda: require(CTX["restart_factory"]() == "PASS"))
case("STORE", "SQLite", lambda: require(CTX["store"].connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"))
case("STORE", "foreign keys", lambda: require(CTX["store"].connection.execute("PRAGMA foreign_key_check").fetchall() == []))
case("STORE", "update API", lambda: expect(Stage6RecursiveThesisError, lambda: CTX["store"].update_record()))
case("STORE", "source integrity", lambda: expect(RecursiveThesisIntegrityFailure, CTX["source_integrity_failure_factory"]))
for table in TABLES:
    case("APPEND_ONLY", table + " update", lambda table=table: expect(sqlite3.DatabaseError, lambda: CTX["store"].connection.execute(f"UPDATE {table} SET rowid=rowid")))
    case("APPEND_ONLY", table + " delete", lambda table=table: expect(sqlite3.DatabaseError, lambda: CTX["store"].connection.execute(f"DELETE FROM {table}")))
case("STORE", "trigger pairs", lambda: require(all(len(CTX["store"].connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)).fetchall()) == 2 for table in TABLES)))

for table, statement in (
    ("recursive_review_snapshots", "UPDATE recursive_review_snapshots SET canonical_json='{}'"),
    ("recursive_review_assessments", "UPDATE recursive_review_assessments SET canonical_json='{}'"),
    ("recursive_thesis_versions", "UPDATE recursive_thesis_versions SET canonical_json='{}'"),
    ("recursive_version_dependencies", "UPDATE recursive_version_dependencies SET record_hash='" + ("0" * 64) + "'"),
    ("recursive_version_audits", "UPDATE recursive_version_audits SET canonical_json='{}'"),
    ("recursive_thesis_policies", "UPDATE recursive_thesis_policies SET canonical_json='{}'"),
    ("recursive_thesis_contracts", "UPDATE recursive_thesis_contracts SET canonical_json='{}'"),
):
    case("TAMPER", table, lambda table=table, statement=statement: expect(RecursiveThesisIntegrityFailure, lambda: CTX["tamper_factory"](table, statement)))

for forbidden in ("BUY", "SELL", "HOLD", "EXIT", "ADD", "REDUCE", "REPLACE", "CLOSED", "proposed_stop", "proposed_target", "trailing_stop", "technical_stop", "quantity_change", "portfolio_threshold", "expected_return", "confidence_score", "conviction_score"):
    case("BOUNDARY", forbidden, lambda forbidden=forbidden: require(forbidden not in canonical_json(CTX["r4"]["version_record"])))

def imports():
    found = set()
    for path in (ROOT / "stage6_recursive_thesis").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
    return found


for token in ("requests", "urllib", "httpx", "aiohttp", "socket", "selenium", "yfinance", "gdelt", "openai", "anthropic", "transformers", "torch", "tensorflow", "sklearn"):
    case("STATIC", "no " + token, lambda token=token: require(not any(name == token or name.startswith(token + ".") for name in imports())))
case("STATIC", "no Stage5 import", lambda: require(not any("stage5" in name.lower() for name in imports())))
for token in ("datetime.now", "utcnow", "rev-parse", "max(version)", "order by version desc", "limit 1"):
    case("STATIC", "no " + token, lambda token=token: require(token not in "\n".join(path.read_text(encoding="utf-8").lower() for path in (ROOT / "stage6_recursive_thesis").glob("*.py"))))


def main():
    temp = tempfile.TemporaryDirectory(prefix="stage6_6f_")
    boot = bootstrap(temp.name)
    CTX.update(boot)
    CTX["store"] = boot["recursive_store"]
    CTX["v2"] = boot["v2_result"]["trade_thesis"]
    CTX["v2_record_id"] = boot["v2_result"]["version_record"]["version_record_id"]
    req3 = request("STAGE6_6E", CTX["v2_record_id"], "2026-09-29T13:00:00Z", "S6EV_R2", "SUPPORTIVE_MATERIAL")
    r3 = CTX["store"].review(**req3); CTX["req3"] = req3; CTX["r3"] = r3; CTX["v3"] = r3["trade_thesis"]
    req4 = request("STAGE6_6F", r3["version_record"]["version_record_id"], "2026-09-29T14:00:00Z", "S6EV_R3", "ADVERSE_MATERIAL")
    r4 = CTX["store"].review(**req4); CTX["req4"] = req4; CTX["r4"] = r4; CTX["v4"] = r4["trade_thesis"]
    reqi = request("STAGE6_6F", r4["version_record"]["version_record_id"], "2026-09-29T15:00:00Z", "S6EV_R4", "NOT_EVALUATED")
    CTX["reqi"] = reqi; CTX["ri"] = CTX["store"].review(**reqi)
    invalid_store = RecursiveThesisStore(Path(temp.name) / "invalid_recursive.sqlite3", CTX["version_store"], evidence_store=CTX["evidence_store"])
    invalid_req = request("STAGE6_6E", CTX["v2_record_id"], "2026-09-29T12:50:00Z", "S6EV_R2", "NON_MATERIAL")
    invalid_req["invalidation_assessments"] = invalidations(CTX["v2"], {"record_type": "STAGE6_EVIDENCE_V2", "record_id": "S6EV_R2", "record_hash": CTX["evidence_by_id"]["S6EV_R2"]["record_hash"]}, "TRIGGERED")
    invalid_req["change_assertions"] = []
    invalid_r3 = invalid_store.review(**invalid_req); invalid_v3 = invalid_r3["trade_thesis"]
    binding_r3 = {"record_type": "STAGE6_EVIDENCE_V2", "record_id": "S6EV_R3", "record_hash": CTX["evidence_by_id"]["S6EV_R3"]["record_hash"]}
    invalid_r4 = invalid_store.review(current_thesis_source="STAGE6_6F", current_version_record_id=invalid_r3["version_record"]["version_record_id"], review_cutoff="2026-09-29T13:50:00Z", evidence_ids=["S6EV_R3"], company_effect_ids=[], invalidation_assessments=invalidations(invalid_v3), change_assertions=[assertion(binding_r3, "NON_MATERIAL")])
    CTX["invalid_store"] = invalid_store; CTX["invalidated_v3"] = invalid_v3; CTX["invalidated_v4"] = invalid_r4["trade_thesis"]
    def rules(statuses, assessments):
        snapshot = r3["review_snapshot"]; current = CTX["v2"]; b = support(snapshot, "S6EV_R2")
        inv = [{"condition_index": i, "condition_text": text, "evaluation_status": statuses[i], "supporting_bindings": [b] if statuses[i] == "TRIGGERED" else []} for i, text in enumerate(current["invalidation_conditions"])]
        ass = [assertion(b, value) for value in assessments]
        return build_assessment(current=current, snapshot=snapshot, invalidation_assessments=inv, change_assertions=ass, policy_hash=CTX["store"].policy_hash, contract_hash=CTX["store"].contract_hash)
    CTX["rule_factory"] = rules
    CTX["fork_factory"] = lambda: CTX["store"].review(**request("STAGE6_6E", CTX["v2_record_id"], "2026-09-29T12:45:00Z", "S6EV_R2", "NON_MATERIAL"))
    logical = request("STAGE6_6E", CTX["v2_record_id"], "2026-09-29T13:00:00Z", "S6EV_R2", "NOT_EVALUATED"); logical["evidence_ids"] = []
    logical["invalidation_assessments"] = invalidations(CTX["v2"], None, "NOT_EVALUATED")
    CTX["logical_conflict_factory"] = lambda: CTX["store"].review(**logical)
    def restart():
        reopened = RecursiveThesisStore(CTX["store"].database, CTX["version_store"], evidence_store=CTX["evidence_store"])
        try:
            return reopened.integrity_check()["result"]
        finally:
            reopened.close()
    CTX["restart_factory"] = restart
    def source_integrity_failure():
        original = CTX["version_store"].integrity_check
        CTX["version_store"].integrity_check = lambda: {"result": "FAIL"}
        try:
            return CTX["store"].integrity_check()
        finally:
            CTX["version_store"].integrity_check = original
    CTX["source_integrity_failure_factory"] = source_integrity_failure
    def tamper(table, statement):
        path = Path(temp.name) / ("tamper_" + table + ".sqlite3")
        path.write_bytes(CTX["store"].connection.serialize())
        copied = RecursiveThesisStore(path, CTX["version_store"], evidence_store=CTX["evidence_store"])
        try:
            copied.connection.execute(f"DROP TRIGGER protect_{table}_update")
            copied.connection.execute(statement)
            copied.connection.commit()
            return copied.integrity_check()
        finally:
            copied.close()
    CTX["tamper_factory"] = tamper
    for field in sorted(REVIEW_FIELDS):
        case("REVIEW_REJECT", field, lambda field=field: expect(RecursiveThesisIntegrityFailure, lambda: validate_review_snapshot({key: value for key, value in r3["review_snapshot"].items() if key != field}, CTX["v2"])))
    for field in sorted(ASSESSMENT_FIELDS):
        case("ASSESSMENT_REJECT", field, lambda field=field: expect(RecursiveThesisIntegrityFailure, lambda: validate_assessment({key: value for key, value in r3["assessment"].items() if key != field}, CTX["v2"], r3["review_snapshot"])))
    for field in sorted(WRAPPER_FIELDS):
        case("WRAPPER_REJECT", field, lambda field=field: expect(RecursiveThesisIntegrityFailure, lambda: validate_version_wrapper({key: value for key, value in r3["version_record"].items() if key != field}, "STAGE6_6E", CTX["v2_record_id"], CTX["v2"], r3["review_snapshot"], r3["assessment"])))
    rows = []
    failed = 0
    for index, (group, name, function) in enumerate(CASES, 1):
        try:
            function(); result, detail = "PASS", ""
        except Exception as exc:
            failed += 1; result, detail = "FAIL", f"{type(exc).__name__}: {exc}"
        rows.append((index, group, name, result, detail))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n"); writer.writerow(("test_id", "test_group", "test_name", "result", "detail")); writer.writerows(rows)
    total = len(rows)
    print(f"Stage 6.6F: {total - failed}/{total} PASS" if not failed else f"Stage 6.6F: {total - failed}/{total} PASS, {failed} FAIL")
    for row in rows:
        if row[3] == "FAIL": print(row)
    invalid_store.close()
    for key in ("recursive_store", "version_store", "assessment_store", "review_store", "evidence_store", "thesis_store", "seed_store"):
        try: boot[key].close()
        except Exception: pass
    temp.cleanup()
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
