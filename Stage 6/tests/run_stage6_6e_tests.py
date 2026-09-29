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
from stage6_trade_thesis.errors import TradeThesisIntegrityFailure
from stage6_thesis_review_input.review_input_store import ThesisReviewInputStore
from stage6_thesis_review_input.errors import ThesisReviewInputIntegrityFailure
from stage6_thesis_review_assessment.review_assessment_store import ThesisReviewAssessmentStore
from stage6_thesis_review_assessment.errors import ThesisReviewAssessmentIntegrityFailure
from stage6_trade_thesis_version.errors import *
from stage6_trade_thesis_version.policy import *
from stage6_trade_thesis_version.trade_thesis_version_builder import SAFETY, build_version_record, direct_inputs
from stage6_trade_thesis_version.trade_thesis_version_store import TABLES, TradeThesisVersionStore
from stage6_trade_thesis_version.trade_thesis_version_validation import WRAPPER_FIELDS, eligibility, validate_trade_thesis_v2, validate_version_record

OUT = ROOT / "results" / "stage6_6e_test_results.csv"
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


def result_count(stage):
    with (ROOT / "results" / f"stage6_{stage}_test_results.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    require(all(row["result"] == "PASS" for row in rows))
    return len(rows)


def prior_result_count():
    stages = ("1a", "1b", "1c", "2a", "2b", "2c", "2d", "2e", "2f", "3a", "3b", "3c", "3d", "3e", "3f", "3g", "3h", "3i", "4a", "4b", "4c", "4d", "4e", "5a", "5b", "5c", "5d", "6a", "6b", "6c")
    return sum(result_count(stage) for stage in stages)


def architecture_result():
    output = subprocess.check_output([sys.executable, str(ROOT / "scripts/validate_stage6_0.py")], cwd=REPO, text=True)
    return json.loads(output)


def source():
    return json.loads((ROOT / "fixtures/stage6_6a/initial_thesis_seed_examples.json").read_text(encoding="utf-8"))["examples"][0]


class EvidenceStore:
    def __init__(self, evidence):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("CREATE TABLE ingestion_records(record_id TEXT PRIMARY KEY,canonical_json TEXT NOT NULL)")
        self.connection.execute("INSERT INTO ingestion_records VALUES(?,?)", (evidence["evidence_id"], canonical_json(evidence)))
        self.connection.commit()
        self.passes = True

    def integrity_check(self):
        return {"result": "PASS" if self.passes else "FAIL"}

    def close(self):
        self.connection.close()


def evidence():
    value = {
        "schema_version": "STAGE6_EVIDENCE_V2",
        "record_kind": "EVIDENCE",
        "evidence_id": "S6EV_VERSION_REVIEW_001",
        "retrieved_timestamp_utc": "2026-09-29T11:00:00Z",
        "record_hash": "",
    }
    value["record_hash"] = canonical_hash(without(value, "record_hash"))
    return value


def assertion(snapshot, assessment):
    support = next(item for item in snapshot["direct_input_bindings"] if item["record_type"] == "STAGE6_EVIDENCE_V2")
    core = {"assessment": assessment, "reason_code": "NEW_EVIDENCE", "supporting_bindings": [support]}
    return {"assertion_id": "S6THASSERT_" + canonical_hash(core)[:24], **core}


def invalidations(thesis, support, mode):
    statuses = ["NOT_TRIGGERED"] * len(thesis["invalidation_conditions"])
    if mode == "INVALIDATION_TRIGGERED":
        statuses[0] = "TRIGGERED"
    elif mode == "INVALIDATION_NOT_EVALUATED":
        statuses[0] = "NOT_EVALUATED"
    return [
        {
            "condition_index": index,
            "condition_text": text,
            "evaluation_status": statuses[index],
            "supporting_bindings": [support] if statuses[index] == "TRIGGERED" else [],
        }
        for index, text in enumerate(thesis["invalidation_conditions"])
    ]


def make_chain(folder, name, mode, cutoff="2026-09-29T12:00:00Z"):
    path = Path(folder) / name
    path.mkdir(parents=True, exist_ok=True)
    seed_store = ThesisSeedStore(path / "seed.sqlite3")
    seed = seed_store.freeze(source())["initial_thesis_seed"]
    thesis_store = TradeThesisStore(path / "thesis.sqlite3", seed_store)
    thesis = thesis_store.materialize(seed["seed_record_id"])["trade_thesis"]
    ev = evidence()
    evidence_store = EvidenceStore(ev)
    review_store = ThesisReviewInputStore(path / "review.sqlite3", thesis_store, evidence_store=evidence_store)
    snapshot = review_store.freeze(
        thesis_id=thesis["thesis_id"], review_cutoff=cutoff, evidence_ids=[ev["evidence_id"]],
        company_effect_ids=[], market_context_id=None, historical_analogue_id=None, portfolio_context_id=None,
    )["review_input_snapshot"]
    support = next(item for item in snapshot["direct_input_bindings"] if item["record_type"] == "STAGE6_EVIDENCE_V2")
    assessment_store = ThesisReviewAssessmentStore(path / "assessment.sqlite3", review_store, thesis_store)
    assertions = [] if mode in {"INVALIDATION_TRIGGERED", "INVALIDATION_NOT_EVALUATED"} else [assertion(snapshot, mode)]
    assessment = assessment_store.assess(
        review_snapshot_id=snapshot["review_snapshot_id"],
        invalidation_assessments=invalidations(thesis, support, mode),
        change_assertions=assertions,
    )["review_assessment"]
    version_store = TradeThesisVersionStore(path / "version.sqlite3", assessment_store, review_store, thesis_store)
    return {
        "seed_store": seed_store, "thesis_store": thesis_store, "evidence_store": evidence_store,
        "review_store": review_store, "assessment_store": assessment_store, "version_store": version_store,
        "previous": thesis, "snapshot": snapshot, "assessment": assessment,
    }


def V(name="unchanged"):
    return CTX[name]["result"]["trade_thesis"]


def W(name="unchanged"):
    return CTX[name]["result"]["version_record"]


for label, actual, expected in (
    ("payload schema", SCHEMA_VERSION, "STAGE6_TRADE_THESIS_V2"),
    ("wrapper schema", WRAPPER_SCHEMA_VERSION, "STAGE6_6E_TRADE_THESIS_VERSION_RECORD_V1"),
    ("store", STORE_SCHEMA_VERSION, "STAGE6_6E_TRADE_THESIS_VERSION_STORE_V1"),
    ("processor", PROCESSOR_VERSION, "STAGE6_6E_TRADE_THESIS_VERSION_MATERIALIZER_V1"),
    ("policy", POLICY_ID, "S6THVERPOL_STAGE6_6E_V1"),
    ("contract", CONTRACT_VERSION, "STAGE6_TRADE_THESIS_VERSION_MATERIALIZATION_CONTRACT_V1"),
    ("engine", THESIS_ENGINE_VERSION, "STAGE6_THESIS_MATERIAL_CHANGE_RULES_V1"),
    ("authority", AUTHORITY, "SHADOW_ONLY"),
    ("baseline", DEVELOPMENT_BASELINE, "16346dee8270135a7f43f1140f920531d33f6cbd"),
    ("runtime", RUNTIME_SEMANTIC_COMMIT, "3b094f4167e78de7699742080e0a163e7550bc0e"),
):
    case("IDENTITY", label, lambda actual=actual, expected=expected: require(actual == expected))
case("IDENTITY", "HEAD descendant safe", lambda: require(git("merge-base", "HEAD", DEVELOPMENT_BASELINE) == DEVELOPMENT_BASELINE))
case("IDENTITY", "baseline parent", lambda: require(git("rev-parse", DEVELOPMENT_BASELINE + "^") == RUNTIME_SEMANTIC_COMMIT))
case("IDENTITY", "branch", lambda: require(git("branch", "--show-current") == "stage6-persistent-thesis"))
case("IDENTITY", "schema blob", lambda: require(git_blob(ROOT / "contracts/trade_thesis.schema.json") == TRADE_THESIS_BLOB))
case("IDENTITY", "policy hash", lambda: require(load_policy()[2] == EXPECTED_POLICY_HASH_V1))
case("IDENTITY", "contract hash", lambda: require(load_contract()[2] == EXPECTED_CONTRACT_HASH_V1))
case("IDENTITY", "fixture", lambda: require(json.loads((ROOT / "fixtures/stage6_6e/trade_thesis_version_examples.json").read_text())["fixture_version"] == "STAGE6_6E_FIXTURES_V1"))
case("REGRESSION", "Stage 6.6D 240", lambda: require(result_count("6d") == 240))
case("REGRESSION", "prior Stage 6 3032", lambda: require(prior_result_count() == 3032))
case("REGRESSION", "combined current 3272", lambda: require(prior_result_count() + result_count("6d") == 3272))
case("REGRESSION", "Stage 6.0C ten schemas", lambda: require(architecture_result()["result"] == "PASS" and architecture_result()["schemas_parsed"] == 10))

for name in ("strengthened", "unchanged", "weakened", "invalidated"):
    case("ELIGIBILITY", name, lambda name=name: require(eligibility(CTX[name]["assessment"]) == "READY_FOR_MATERIALIZATION"))
case("ELIGIBILITY", "indeterminate", lambda: require(eligibility(CTX["indeterminate"]["assessment"]) == "WITHHELD_INDETERMINATE"))
case("ELIGIBILITY", "withheld response", lambda: require(CTX["indeterminate"]["result"] == {"status": "WITHHELD_INDETERMINATE", "version_record": None, "trade_thesis": None}))
for table in ("trade_thesis_version_records", "trade_thesis_version_dependencies", "trade_thesis_version_audits"):
    case("ELIGIBILITY", "withheld zero " + table, lambda table=table: require(CTX["indeterminate"]["version_store"].connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0))

expected_statuses = {
    "strengthened": ("THESIS_STRENGTHENED", "THESIS_STRENGTHENED_REVIEW"),
    "unchanged": ("THESIS_UNCHANGED", "THESIS_REVIEWED_UNCHANGED"),
    "weakened": ("THESIS_WEAKENED", "THESIS_WEAKENED_REVIEW"),
    "invalidated": ("THESIS_INVALIDATED", "THESIS_INVALIDATED_REVIEW"),
}
for name, (status, change_type) in expected_statuses.items():
    case("STATUS", name + " status", lambda name=name, status=status: require(V(name)["thesis_status"] == status))
    case("STATUS", name + " change", lambda name=name, change_type=change_type: require(V(name)["change_history"][-1]["change_type"] == change_type))
    case("STATUS", name + " valid", lambda name=name: require(validate_version_record(W(name), CTX[name]["previous"], CTX[name]["snapshot"], CTX[name]["assessment"], CTX[name]["version_store"].policy_hash, CTX[name]["version_store"].contract_hash) == W(name)))

case("VERSION", "stable thesis ID", lambda: require(V()["thesis_id"] == CTX["unchanged"]["previous"]["thesis_id"]))
case("VERSION", "version two", lambda: require(V()["version"] == 2))
case("VERSION", "previous one", lambda: require(CTX["unchanged"]["previous"]["version"] == 1))
case("VERSION", "engine", lambda: require(V()["thesis_engine_version"] == THESIS_ENGINE_VERSION))
case("VERSION", "runtime commit", lambda: require(V()["code_commit"] == RUNTIME_SEMANTIC_COMMIT))
case("VERSION", "test-fix commit prohibited", lambda: require(V()["code_commit"] != DEVELOPMENT_BASELINE))
case("VERSION", "decision cutoff", lambda: require(V()["decision_cutoff"] == CTX["unchanged"]["assessment"]["review_cutoff"]))
case("VERSION", "previous hash", lambda: require(V()["previous_version_hash"] == CTX["unchanged"]["previous"]["record_hash"]))
case("VERSION", "last review date", lambda: require(V()["last_review_date"] == V()["decision_cutoff"][:10]))
case("VERSION", "CLOSED prohibited", lambda: require(V()["thesis_status"] != "CLOSED"))

case("INPUTS", "exact three", lambda: require(len(V()["input_records"]) == 3))
case("INPUTS", "canonical order", lambda: require(V()["input_records"] == direct_inputs(CTX["unchanged"]["previous"], CTX["unchanged"]["snapshot"], CTX["unchanged"]["assessment"])))
for index, kind in enumerate((PREVIOUS_SCHEMA, SNAPSHOT_SCHEMA, ASSESSMENT_SCHEMA)):
    case("INPUTS", kind, lambda index=index, kind=kind: require(V()["input_records"][index]["record_type"] == kind))
for forbidden in sorted({"STAGE6_EVIDENCE_V2", "STAGE6_EVENT_COMPANY_EFFECT_V1", "STAGE6_MARKET_CONTEXT_V2", "STAGE6_HISTORICAL_ANALOGUE_V2", "STAGE6_PORTFOLIO_CONTEXT_V2"}):
    case("INPUTS", "no direct " + forbidden, lambda forbidden=forbidden: require(forbidden not in {item["record_type"] for item in V()["input_records"]}))

preserved = (
    "thesis_id", "recommendation_id", "ticker", "entry_date", "holding_horizon", "entry_rationale",
    "supporting_evidence", "known_risks", "initial_entry_range", "fill_references", "aggregate_fill",
    "initial_stop", "current_stop", "initial_target", "current_target", "invalidation_conditions",
)
for field in preserved:
    case("PRESERVE", field, lambda field=field: require(V()[field] == CTX["unchanged"]["previous"][field]))
case("PRESERVE", "rationale ordering", lambda: require(canonical_json(V()["entry_rationale"]) == canonical_json(CTX["unchanged"]["previous"]["entry_rationale"])))
case("PRESERVE", "risk ordering", lambda: require(canonical_json(V()["known_risks"]) == canonical_json(CTX["unchanged"]["previous"]["known_risks"])))
case("PRESERVE", "invalidation ordering", lambda: require(canonical_json(V()["invalidation_conditions"]) == canonical_json(CTX["unchanged"]["previous"]["invalidation_conditions"])))

case("HISTORY", "previous unchanged", lambda: require(V()["change_history"][:-1] == CTX["unchanged"]["previous"]["change_history"]))
case("HISTORY", "length two", lambda: require(len(V()["change_history"]) == 2))
case("HISTORY", "versions", lambda: require([item["version"] for item in V()["change_history"]] == [1, 2]))
for field, expected in (
    ("version", 2), ("changed_at_utc", None), ("decision_cutoff", None),
    ("change_type", "THESIS_REVIEWED_UNCHANGED"), ("reason", "NO_MATERIAL_CHANGE"),
    ("evidence_ids", None), ("input_records", None),
):
    case("HISTORY", field, lambda field=field, expected=expected: require(V()["change_history"][-1][field] == (CTX["unchanged"]["assessment"]["review_cutoff"] if field in {"changed_at_utc", "decision_cutoff"} else CTX["unchanged"]["assessment"]["review_evidence_ids"] if field == "evidence_ids" else V()["input_records"] if field == "input_records" else expected)))

case("HASH", "payload", lambda: require(V()["record_hash"] == canonical_hash(without(V(), "record_hash"))))
case("HASH", "wrapper ID", lambda: require(W()["version_record_id"] == "S6THVER_" + canonical_hash(without(W(), "version_record_id", "record_hash"))[:24]))
case("HASH", "wrapper", lambda: require(W()["record_hash"] == canonical_hash(without(W(), "record_hash"))))
case("HASH", "deterministic replay", lambda: require(build_version_record(CTX["unchanged"]["previous"], CTX["unchanged"]["snapshot"], CTX["unchanged"]["assessment"], CTX["unchanged"]["version_store"].policy_hash, CTX["unchanged"]["version_store"].contract_hash) == W()))
case("HASH", "history tamper", lambda: expect(TradeThesisVersionIntegrityFailure, lambda: validate_trade_thesis_v2(changed(V(), ["change_history", 1, "reason"], "OTHER"), CTX["unchanged"]["previous"], CTX["unchanged"]["snapshot"], CTX["unchanged"]["assessment"])))
case("CHAIN", "thesis ID mismatch", lambda: expect(TradeThesisIntegrityFailure, lambda: validate_trade_thesis_v2(V(), changed(CTX["unchanged"]["previous"], ["thesis_id"], "OTHER"), CTX["unchanged"]["snapshot"], CTX["unchanged"]["assessment"])))
case("CHAIN", "thesis hash mismatch", lambda: expect(TradeThesisIntegrityFailure, lambda: validate_trade_thesis_v2(V(), changed(CTX["unchanged"]["previous"], ["record_hash"], "0" * 64), CTX["unchanged"]["snapshot"], CTX["unchanged"]["assessment"])))
case("CHAIN", "snapshot ID mismatch", lambda: expect(ThesisReviewInputIntegrityFailure, lambda: validate_trade_thesis_v2(V(), CTX["unchanged"]["previous"], changed(CTX["unchanged"]["snapshot"], ["review_snapshot_id"], "OTHER"), CTX["unchanged"]["assessment"])))
case("CHAIN", "snapshot hash mismatch", lambda: expect(ThesisReviewInputIntegrityFailure, lambda: validate_trade_thesis_v2(V(), CTX["unchanged"]["previous"], changed(CTX["unchanged"]["snapshot"], ["record_hash"], "0" * 64), CTX["unchanged"]["assessment"])))
case("CHAIN", "assessment cutoff mismatch", lambda: expect(ThesisReviewAssessmentIntegrityFailure, lambda: validate_trade_thesis_v2(V(), CTX["unchanged"]["previous"], CTX["unchanged"]["snapshot"], changed(CTX["unchanged"]["assessment"], ["review_cutoff"], "2026-09-30T12:00:00Z"))))

for field in sorted(SAFETY):
    case("SAFETY", field, lambda field=field: require(W()[field] == SAFETY[field]))
for forbidden in ("BUY", "SELL", "HOLD", "EXIT", "REDUCE", "ADD", "REPLACE", "CLOSED"):
    case("BOUNDARY", forbidden, lambda forbidden=forbidden: require(forbidden not in canonical_json(W())))
for forbidden in ("proposed_stop", "proposed_target", "trailing_stop", "risk_reward", "quantity_change", "replacement_action", "concentration_action", "correlation_action"):
    case("BOUNDARY", forbidden, lambda forbidden=forbidden: require(forbidden not in canonical_json(W())))

case("STORE", "created", lambda: require(CTX["unchanged"]["result"]["status"] == "CREATED"))
case("STORE", "integrity", lambda: require(CTX["unchanged"]["version_store"].integrity_check()["result"] == "PASS"))
case("STORE", "idempotent", lambda: require(CTX["unchanged"]["version_store"].materialize(CTX["unchanged"]["assessment"]["assessment_id"])["status"] == "IDEMPOTENT_SUCCESS"))
case("STORE", "five dependencies", lambda: require(CTX["unchanged"]["version_store"].connection.execute("SELECT count(*) FROM trade_thesis_version_dependencies").fetchone()[0] == 5))
case("STORE", "one audit", lambda: require(CTX["unchanged"]["version_store"].connection.execute("SELECT count(*) FROM trade_thesis_version_audits").fetchone()[0] == 1))
case("STORE", "unique thesis version", lambda: require(CTX["unchanged"]["version_store"].connection.execute("SELECT thesis_id,version FROM trade_thesis_version_records").fetchone()[1] == 2))
case("STORE", "same ID across stores", lambda: require(CTX["unchanged"]["thesis_store"].connection.execute("SELECT thesis_id FROM trade_thesis_records").fetchone()[0] == CTX["unchanged"]["version_store"].connection.execute("SELECT thesis_id FROM trade_thesis_version_records").fetchone()[0]))
case("STORE", "SQLite", lambda: require(CTX["unchanged"]["version_store"].connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"))
case("STORE", "foreign keys", lambda: require(CTX["unchanged"]["version_store"].connection.execute("PRAGMA foreign_key_check").fetchall() == []))
case("STORE", "update API", lambda: expect(Stage6TradeThesisVersionError, lambda: CTX["unchanged"]["version_store"].update_record()))
case("STORE", "restart", lambda: require(CTX["restart_factory"]() == "PASS"))
case("STORE", "same thesis/version conflict", lambda: expect(TradeThesisVersionConflict, CTX["conflict_factory"]))
for table in TABLES:
    case("APPEND_ONLY", table + " update", lambda table=table: expect(sqlite3.DatabaseError, lambda: CTX["unchanged"]["version_store"].connection.execute(f"UPDATE {table} SET rowid=rowid")))
    case("APPEND_ONLY", table + " delete", lambda table=table: expect(sqlite3.DatabaseError, lambda: CTX["unchanged"]["version_store"].connection.execute(f"DELETE FROM {table}")))
case("STORE", "trigger pairs", lambda: require(all(len(CTX["unchanged"]["version_store"].connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)).fetchall()) == 2 for table in TABLES)))

for field in sorted(WRAPPER_FIELDS):
    case("WRAPPER_REJECT", field, lambda field=field: expect(TradeThesisVersionIntegrityFailure, lambda: validate_version_record({key: value for key, value in W().items() if key != field}, CTX["unchanged"]["previous"], CTX["unchanged"]["snapshot"], CTX["unchanged"]["assessment"])))
case("WRAPPER_REJECT", "extra", lambda: expect(TradeThesisVersionIntegrityFailure, lambda: validate_version_record(W() | {"extra": 1}, CTX["unchanged"]["previous"], CTX["unchanged"]["snapshot"], CTX["unchanged"]["assessment"])))

def imports():
    found = set()
    for path in (ROOT / "stage6_trade_thesis_version").glob("*.py"):
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
for token in ("datetime.now", "utcnow", "rev-parse", "current head"):
    case("STATIC", "no runtime " + token, lambda token=token: require(token not in "\n".join(path.read_text(encoding="utf-8").lower() for path in (ROOT / "stage6_trade_thesis_version").glob("*.py"))))


def tamper(table, statement):
    chain = make_chain(CTX["temp"], "tamper_" + table, "NON_MATERIAL")
    store = chain["version_store"]
    try:
        store.materialize(chain["assessment"]["assessment_id"])
        store.connection.execute(f"DROP TRIGGER protect_{table}_update")
        store.connection.execute(statement)
        store.connection.commit()
        return store.integrity_check()
    finally:
        for key in ("version_store", "assessment_store", "review_store", "evidence_store", "thesis_store", "seed_store"):
            chain[key].close()


for table, statement in (
    ("trade_thesis_version_records", "UPDATE trade_thesis_version_records SET canonical_json='{}'"),
    ("trade_thesis_version_dependencies", "UPDATE trade_thesis_version_dependencies SET record_hash='" + ("0" * 64) + "'"),
    ("trade_thesis_version_audits", "UPDATE trade_thesis_version_audits SET canonical_json='{}'"),
    ("trade_thesis_version_policies", "UPDATE trade_thesis_version_policies SET canonical_json='{}'"),
    ("trade_thesis_version_contracts", "UPDATE trade_thesis_version_contracts SET canonical_json='{}'"),
):
    case("TAMPER", table, lambda table=table, statement=statement: expect(TradeThesisVersionIntegrityFailure, lambda: tamper(table, statement)))


def main():
    temp = tempfile.TemporaryDirectory(prefix="stage6_6e_")
    CTX["temp"] = temp.name
    modes = {
        "strengthened": "SUPPORTIVE_MATERIAL",
        "unchanged": "NON_MATERIAL",
        "weakened": "ADVERSE_MATERIAL",
        "invalidated": "INVALIDATION_TRIGGERED",
        "indeterminate": "INVALIDATION_NOT_EVALUATED",
    }
    for name, mode in modes.items():
        chain = make_chain(temp.name, name, mode)
        chain["result"] = chain["version_store"].materialize(chain["assessment"]["assessment_id"])
        CTX[name] = chain
    def restart():
        chain = CTX["unchanged"]
        reopened = TradeThesisVersionStore(chain["version_store"].database, chain["assessment_store"], chain["review_store"], chain["thesis_store"])
        try:
            return reopened.integrity_check()["result"]
        finally:
            reopened.close()
    CTX["restart_factory"] = restart
    def conflict():
        chain = CTX["unchanged"]
        snapshot = chain["review_store"].freeze(
            thesis_id=chain["previous"]["thesis_id"], review_cutoff="2026-09-29T13:00:00Z",
            evidence_ids=["S6EV_VERSION_REVIEW_001"], company_effect_ids=[], market_context_id=None,
            historical_analogue_id=None, portfolio_context_id=None,
        )["review_input_snapshot"]
        support = next(item for item in snapshot["direct_input_bindings"] if item["record_type"] == "STAGE6_EVIDENCE_V2")
        assessment = chain["assessment_store"].assess(
            review_snapshot_id=snapshot["review_snapshot_id"],
            invalidation_assessments=invalidations(chain["previous"], support, "NON_MATERIAL"),
            change_assertions=[assertion(snapshot, "NON_MATERIAL")],
        )["review_assessment"]
        return chain["version_store"].materialize(assessment["assessment_id"])
    CTX["conflict_factory"] = conflict
    # Closed-field tests need the now-created canonical payload fields.
    for field in sorted(V()):
        case("PAYLOAD_REJECT", field, lambda field=field: expect(TradeThesisVersionIntegrityFailure, lambda: validate_trade_thesis_v2({key: value for key, value in V().items() if key != field}, CTX["unchanged"]["previous"], CTX["unchanged"]["snapshot"], CTX["unchanged"]["assessment"])))
    case("PAYLOAD_REJECT", "extra", lambda: expect(TradeThesisVersionIntegrityFailure, lambda: validate_trade_thesis_v2(V() | {"extra": 1}, CTX["unchanged"]["previous"], CTX["unchanged"]["snapshot"], CTX["unchanged"]["assessment"])))
    rows = []
    failed = 0
    for index, (group, name, function) in enumerate(CASES, 1):
        try:
            function()
            result, detail = "PASS", ""
        except Exception as exc:
            failed += 1
            result, detail = "FAIL", f"{type(exc).__name__}: {exc}"
        rows.append((index, group, name, result, detail))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("test_id", "test_group", "test_name", "result", "detail"))
        writer.writerows(rows)
    total = len(rows)
    print(f"Stage 6.6E: {total - failed}/{total} PASS" if not failed else f"Stage 6.6E: {total - failed}/{total} PASS, {failed} FAIL")
    for row in rows:
        if row[3] == "FAIL":
            print(row)
    for chain in CTX.values():
        if isinstance(chain, dict):
            for key in ("version_store", "assessment_store", "review_store", "evidence_store", "thesis_store", "seed_store"):
                if key in chain:
                    try:
                        chain[key].close()
                    except Exception:
                        pass
    temp.cleanup()
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
