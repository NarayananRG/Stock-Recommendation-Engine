"""Deterministic, socket-free Stage 6.1B acceptance and adversarial tests."""
from __future__ import annotations

import ast
import csv
import json
import socket
import ssl
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest import mock


STAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE_ROOT.parent
sys.path.insert(0, str(STAGE_ROOT))

from stage6_connectors.live_registries import (
    REGISTRY_REVIEWED_AT_UTC, SEBI_ENTITY_ID, SEBI_SOURCE_ID, build_live_registries,
)
from stage6_connectors.policy import (
    EndpointPolicyError, SEBI_RSS_URL, validate_endpoint, validate_redirect,
)
from stage6_connectors.sebi_rss import SebiRssConnector
from stage6_connectors.transport import ControlledHttpsTransport, TransportFailure, TransportResponse
from stage6_ingestion.canonical import canonical_json, sha256_bytes
from stage6_ingestion.errors import IntegrityFailure, ResolutionError
from stage6_ingestion.evidence_store import AUTHORITY, IngestionStore
from stage6_ingestion.registry import build_entity_registry, build_source_registry


BASELINE_TAG = "stage6-1a-ingestion-foundation-baseline"
BASELINE_COMMIT = "d5012decd2ff92ab088648b651d6285be17e8cc3"
ARCHITECTURE_TAG = "stage6-decision-intelligence-architecture-baseline-v2"
PRODUCTION_TAG = "stage5d5-live-paper-runner-baseline"
RESULT_PATH = STAGE_ROOT / "results" / "stage6_1b_test_results.csv"
FIXTURE_PATH = STAGE_ROOT / "fixtures" / "stage6_1b" / "valid_sebi_rss.xml"
VALID_RSS = FIXTURE_PATH.read_bytes()
OBSERVED = "2026-09-25T15:00:00Z"
RETRIEVED = "2026-09-25T15:00:01Z"
CHECKS: list[tuple[str, str, object]] = []


def check(category: str, name: str):
    def register(function):
        CHECKS.append((category, name, function))
        return function
    return register


def require(condition: object, message: str = "assertion failed") -> None:
    if not condition:
        raise AssertionError(message)


def expect(error: type[BaseException], function, contains: str | None = None) -> BaseException:
    try:
        function()
    except error as exc:
        if contains is not None:
            require(contains in str(exc), f"expected {contains!r} in {exc!r}")
        return exc
    raise AssertionError(f"expected {error.__name__}")


class FakeTransport:
    def __init__(self, response: TransportResponse | None = None, failure: TransportFailure | None = None):
        self.response = response or good_response()
        self.failure = failure
        self.request_count = 0

    def fetch(self) -> TransportResponse:
        self.request_count += 1
        if self.failure:
            raise self.failure
        return self.response


def good_response(*, body: bytes = VALID_RSS, content_type: str = "application/rss+xml; charset=UTF-8",
                  status: int = 200, retrieved: str = RETRIEVED, truncated: bool = False) -> TransportResponse:
    return TransportResponse(status=status, headers={"content-type": content_type}, body=body,
                             retrieved_timestamp_utc=retrieved, truncated=truncated)


@contextmanager
def live_store(*, source_registry: dict | None = None, entity_registry: dict | None = None):
    registries = build_live_registries()
    source = source_registry or registries["source_v1"]
    entity = entity_registry or registries["entity_v1"]
    with tempfile.TemporaryDirectory(prefix="stage6_1b_test_") as folder:
        root = Path(folder)
        with IngestionStore(root / "store.sqlite3", root / "raw") as store:
            store.import_registry(entity)
            store.import_registry(source)
            yield store, root, source, entity


def acquire(store: IngestionStore, source: dict, entity: dict, transport: FakeTransport,
            observed: str = OBSERVED) -> dict:
    return SebiRssConnector(store, transport).acquire(
        source_registry_snapshot_id=source["registry_snapshot_id"],
        entity_registry_snapshot_id=entity["registry_snapshot_id"],
        observed_timestamp_utc=observed,
    )


def source_registry_with(**changes) -> dict:
    records = deepcopy(build_live_registries()["source_v1"]["sources"])
    records[0].update(changes)
    return build_source_registry(records, REGISTRY_REVIEWED_AT_UTC)


def source_v2(*, changed: bool) -> dict:
    prior = build_live_registries()["source_v1"]
    records = deepcopy(prior["sources"])
    if changed:
        records[0]["source_record_version"] = 2
        records[0]["previous_version_hash"] = records[0]["record_hash"]
        records[0]["availability_notes"] = "Official endpoint re-reviewed for Stage 6.1B V2 test."
        records[0]["reviewed_at_utc"] = "2026-09-26T00:00:00Z"
    return build_source_registry(records, "2026-09-26T00:00:00Z", prior)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()


@check("IDENTITY", "Stage 6.1A baseline is in HEAD ancestry")
def _(): subprocess.check_call(["git", "merge-base", "--is-ancestor", BASELINE_COMMIT, "HEAD"], cwd=REPO_ROOT)

@check("IDENTITY", "authority remains SHADOW_ONLY")
def _(): require(AUTHORITY == "SHADOW_ONLY")

@check("LIVE_REGISTRY", "live registry construction deterministic")
def _(): require(build_live_registries() == build_live_registries())

@check("LIVE_REGISTRY", "SEBI source authority and machine-feed policy exact")
def _():
    source = build_live_registries()["source_v1"]["sources"][0]
    require((source["source_id"], source["authority_level"], source["publisher_type"],
             source["access_method"], source["machine_endpoint_type"]) ==
            (SEBI_SOURCE_ID, "PRIMARY_OFFICIAL", "REGULATOR", "MACHINE_FEED", "RSS_ATOM"))

@check("LIVE_REGISTRY", "SEBI source terms review rationale committed")
def _():
    notes = build_live_registries()["source_v1"]["sources"][0]["terms_notes"]
    require("official SEBI RSS documentation" in notes and "open method" in notes)

@check("LIVE_REGISTRY", "SEBI regulator entity has no ticker mappings")
def _():
    entity = build_live_registries()["entity_v1"]["entities"][0]
    require(entity["entity_id"] == SEBI_ENTITY_ID and entity["entity_type"] == "REGULATOR" and entity["ticker_mappings"] == [])

@check("LIVE_REGISTRY", "live and synthetic fixture identities remain separate")
def _():
    registries = build_live_registries()
    require("S6FIX" not in canonical_json(registries))

@check("ACQUISITION", "valid SEBI RSS creates retrieved evidence")
def _():
    with live_store() as (store, _, source, entity):
        result = acquire(store, source, entity, FakeTransport())
        require(result["outcome"] == "RETRIEVED" and result["record"]["record_kind"] == "EVIDENCE")

@check("ACQUISITION", "exact response bytes are preserved")
def _():
    with live_store() as (store, _, source, entity):
        record = acquire(store, source, entity, FakeTransport())["record"]
        require(store.raw_store.path_for(record["raw_payload_hash"]).read_bytes() == VALID_RSS)

@check("ACQUISITION", "raw payload hash is deterministic SHA-256")
def _():
    with live_store() as (store, _, source, entity):
        record = acquire(store, source, entity, FakeTransport())["record"]
        require(record["raw_payload_hash"] == sha256_bytes(VALID_RSS))

@check("ACQUISITION", "source and authority binding are exact")
def _():
    with live_store() as (store, _, source, entity):
        record = acquire(store, source, entity, FakeTransport())["record"]
        require(record["source_id"] == SEBI_SOURCE_ID and record["authority_level"] == "PRIMARY_OFFICIAL")

@check("ACQUISITION", "only unambiguous SEBI regulator entity is bound")
def _():
    with live_store() as (store, _, source, entity):
        require(acquire(store, source, entity, FakeTransport())["record"]["entity_ids"] == [SEBI_ENTITY_ID])

@check("ACQUISITION", "RSS item link and attachment are never fetched")
def _():
    with live_store() as (store, _, source, entity):
        transport = FakeTransport(); acquire(store, source, entity, transport); require(transport.request_count == 1)


def _approval_blocked(changes: dict) -> None:
    source = source_registry_with(**changes)
    with live_store(source_registry=source) as (store, _, source, entity):
        transport = FakeTransport()
        expect(ResolutionError, lambda: acquire(store, source, entity, transport), "SOURCE_NOT_APPROVED_FOR_AUTOMATION")
        require(transport.request_count == 0)


for _label, _changes in [
    ("disabled source", {"enabled": False}),
    ("unverified source", {"verification_status": "PENDING_REVIEW"}),
    ("prohibited automation", {"automation_allowed_status": "PROHIBITED"}),
    ("unknown automation", {"automation_allowed_status": "UNKNOWN"}),
    ("pending terms review", {"licensing_or_terms_status": "PENDING_REVIEW"}),
]:
    check("APPROVAL_BEFORE_NETWORK", f"{_label} blocks transport")(
        lambda changes=_changes: _approval_blocked(changes))


@check("APPROVAL_BEFORE_NETWORK", "wrong source record hash fails before transport")
def _():
    with live_store() as (store, _, source, entity):
        row = store.connection.execute("SELECT canonical_json FROM registry_snapshots WHERE registry_kind='SOURCE'").fetchone()
        bad = json.loads(row[0]); bad["sources"][0]["source_name"] = "tampered"
        store.connection.execute("DROP TRIGGER protect_registry_snapshots_update")
        store.connection.execute("UPDATE registry_snapshots SET canonical_json=? WHERE registry_kind='SOURCE'", (canonical_json(bad),)); store.connection.commit()
        transport = FakeTransport()
        expect(IntegrityFailure, lambda: acquire(store, source, entity, transport), "REGISTRY_RECORD_HASH_MISMATCH")
        require(transport.request_count == 0)

@check("APPROVAL_BEFORE_NETWORK", "wrong registry hash fails before transport")
def _():
    with live_store() as (store, _, source, entity):
        row = store.connection.execute("SELECT canonical_json FROM registry_snapshots WHERE registry_kind='SOURCE'").fetchone()
        bad = json.loads(row[0]); bad["registry_hash"] = "0" * 64
        store.connection.execute("DROP TRIGGER protect_registry_snapshots_update")
        store.connection.execute("UPDATE registry_snapshots SET canonical_json=? WHERE registry_kind='SOURCE'", (canonical_json(bad),)); store.connection.commit()
        transport = FakeTransport()
        expect(IntegrityFailure, lambda: acquire(store, source, entity, transport), "REGISTRY_HASH_MISMATCH")
        require(transport.request_count == 0)

@check("APPROVAL_BEFORE_NETWORK", "future registry snapshot fails before transport")
def _():
    source = build_live_registries()["source_v1"]
    with live_store() as (store, _, source, entity):
        transport = FakeTransport()
        expect(IntegrityFailure, lambda: acquire(store, source, entity, transport, observed="2026-09-25T14:00:00Z"), "REGISTRY_SNAPSHOT_FROM_FUTURE")
        require(transport.request_count == 0)

@check("APPROVAL_BEFORE_NETWORK", "missing SEBI entity fails before transport")
def _():
    empty_entity = build_entity_registry([], REGISTRY_REVIEWED_AT_UTC)
    with live_store(entity_registry=empty_entity) as (store, _, source, entity):
        transport = FakeTransport()
        expect(ResolutionError, lambda: acquire(store, source, entity, transport), "ENTITY_NOT_FOUND")
        require(transport.request_count == 0)

@check("NETWORK_POLICY", "fixed HTTPS endpoint accepted")
def _(): require(validate_endpoint(SEBI_RSS_URL) == SEBI_RSS_URL)

for _label, _url, _error in [
    ("HTTP rejected", "http://www.sebi.gov.in/sebirss.xml", "HTTPS_REQUIRED"),
    ("localhost rejected", "https://localhost/sebirss.xml", "ENDPOINT_HOST_PROHIBITED"),
    ("IPv4 rejected", "https://127.0.0.1/sebirss.xml", "ENDPOINT_HOST_PROHIBITED"),
    ("IPv6 rejected", "https://[::1]/sebirss.xml", "ENDPOINT_HOST_PROHIBITED"),
    ("file URL rejected", "file:///sebirss.xml", "HTTPS_REQUIRED"),
    ("FTP rejected", "ftp://www.sebi.gov.in/sebirss.xml", "HTTPS_REQUIRED"),
    ("arbitrary host rejected", "https://attacker.example/sebirss.xml", "ENDPOINT_HOST_PROHIBITED"),
    ("wrong path rejected", "https://www.sebi.gov.in/other.xml", "ENDPOINT_PATH_PROHIBITED"),
    ("unexpected port rejected", "https://www.sebi.gov.in:8443/sebirss.xml", "ENDPOINT_PORT_PROHIBITED"),
    ("query substitution rejected", "https://www.sebi.gov.in/sebirss.xml?url=evil", "ENDPOINT_SUFFIX_PROHIBITED"),
]:
    check("NETWORK_POLICY", _label)(lambda url=_url, error=_error: expect(EndpointPolicyError, lambda: validate_endpoint(url), error))

@check("NETWORK_POLICY", "cross-host redirect rejected")
def _(): expect(EndpointPolicyError, lambda: validate_redirect(SEBI_RSS_URL, "https://attacker.example/sebirss.xml"), "ENDPOINT_HOST_PROHIBITED")

@check("NETWORK_POLICY", "redirect downgrade rejected")
def _(): expect(EndpointPolicyError, lambda: validate_redirect(SEBI_RSS_URL, "http://www.sebi.gov.in/sebirss.xml"), "HTTPS_REQUIRED")


class FakeHttpResponse:
    def __init__(self, status: int, body: bytes = b"", headers: list[tuple[str, str]] | None = None):
        self.status = status; self.body = body; self.offset = 0; self.headers = headers or []
    def getheaders(self): return self.headers
    def read(self, size=-1):
        if self.offset >= len(self.body): return b""
        end = len(self.body) if size < 0 else min(len(self.body), self.offset + size)
        chunk = self.body[self.offset:end]; self.offset = end; return chunk


class FakeConnection:
    def __init__(self, response): self.response = response
    def request(self, *_args, **_kwargs): return None
    def getresponse(self): return self.response
    def close(self): return None


@check("NETWORK_POLICY", "redirect limit fails closed")
def _():
    response = FakeHttpResponse(302, headers=[("Location", SEBI_RSS_URL)])
    transport = ControlledHttpsTransport(max_redirects=0, connection_factory=lambda *_args, **_kwargs: FakeConnection(response))
    expect(TransportFailure, transport.fetch, "REDIRECT_LIMIT_EXCEEDED")

@check("NETWORK_POLICY", "oversized body fails closed while bounded")
def _():
    response = FakeHttpResponse(200, body=b"12345", headers=[("Content-Type", "application/xml")])
    transport = ControlledHttpsTransport(max_bytes=4, connection_factory=lambda *_args, **_kwargs: FakeConnection(response))
    expect(TransportFailure, transport.fetch, "RESPONSE_SIZE_LIMIT_EXCEEDED")


for _label, _code in [("timeout", "TIMEOUT"), ("DNS failure", "DNS_FAILURE"), ("TLS failure", "TLS_FAILURE")]:
    @check("FAILURE_SEMANTICS", f"{_label} becomes failed acquisition attempt")
    def _(code=_code):
        with live_store() as (store, _, source, entity):
            result = acquire(store, source, entity, FakeTransport(failure=TransportFailure(code)))
            require(result["record"]["record_kind"] == "ACQUISITION_ATTEMPT" and result["record"]["retrieval_status"] == "FAILED")


for _status, _expected in [(404, "NOT_FOUND"), (401, "ACCESS_DENIED"), (403, "ACCESS_DENIED"), (500, "FAILED")]:
    @check("FAILURE_SEMANTICS", f"HTTP {_status} maps to {_expected} acquisition attempt")
    def _(status=_status, expected=_expected):
        with live_store() as (store, _, source, entity):
            result = acquire(store, source, entity, FakeTransport(good_response(status=status)))
            require(result["record"]["record_kind"] == "ACQUISITION_ATTEMPT" and result["record"]["retrieval_status"] == expected)


for _label, _response, _reason in [
    ("malformed XML quarantined", good_response(body=b"<rss><broken>"), "MALFORMED_XML"),
    ("HTML WAF response quarantined", good_response(body=b"<html><title>Access denied</title></html>", content_type="text/html"), "CONTENT_TYPE_REJECTED"),
    ("incorrect content type quarantined", good_response(content_type="application/json"), "CONTENT_TYPE_REJECTED"),
    ("truncated payload quarantined", good_response(truncated=True), "TRUNCATED_PAYLOAD"),
    ("DTD declaration quarantined", good_response(body=b'<!DOCTYPE rss SYSTEM "https://attacker.example/x"><rss><channel/></rss>'), "XML_EXTERNAL_OR_ENTITY_DECLARATION_REJECTED"),
]:
    @check("QUARANTINE", _label)
    def _(response=_response, reason=_reason):
        with live_store() as (store, _, source, entity):
            result = acquire(store, source, entity, FakeTransport(response))
            require(result["outcome"] == "QUARANTINED" and result["reason"] == reason)
            require(store.raw_store.path_for(result["record"]["raw_payload_hash"]).read_bytes() == response.body)

@check("TIMESTAMPS", "missing feed publication timestamp remains null")
def _():
    body = b'<?xml version="1.0"?><rss version="2.0"><channel><title>SEBI</title></channel></rss>'
    with live_store() as (store, _, source, entity):
        result = acquire(store, source, entity, FakeTransport(good_response(body=body)))
        require(result["outcome"] == "RETRIEVED" and result["record"]["publication_timestamp_utc"] is None)

@check("TIMESTAMPS", "future publisher timestamp is quarantined and never substituted")
def _():
    body = b'<rss version="2.0"><channel><title>SEBI</title><lastBuildDate>Fri, 25 Sep 2026 16:00:00 +0000</lastBuildDate></channel></rss>'
    with live_store() as (store, _, source, entity):
        result = acquire(store, source, entity, FakeTransport(good_response(body=body)))
        require(result["outcome"] == "QUARANTINED" and result["reason"] == "PUBLISHER_TIMESTAMP_FROM_FUTURE")
        require(result["record"]["publication_timestamp_utc"] is None)

@check("TIMESTAMPS", "qualified channel pubDate is preferred over timezone-less lastBuildDate")
def _():
    body = (b'<rss version="2.0"><channel><title>SEBI</title>'
            b'<lastBuildDate>25 Sep 2026 20:00:02</lastBuildDate>'
            b'<pubDate>25 Sep 2026 20:00:02 +0530</pubDate></channel></rss>')
    with live_store() as (store, _, source, entity):
        result = acquire(store, source, entity, FakeTransport(good_response(body=body)))
        require(result["outcome"] == "RETRIEVED")
        require(result["record"]["publication_timestamp_utc"] == "2026-09-25T14:30:02.000000Z")

@check("INTEGRITY", "raw payload tamper detected")
def _():
    with live_store() as (store, _, source, entity):
        record = acquire(store, source, entity, FakeTransport())["record"]
        store.raw_store.path_for(record["raw_payload_hash"]).write_bytes(b"tampered")
        expect(IntegrityFailure, store.integrity_check, "RAW_PAYLOAD_HASH_MISMATCH")

@check("INTEGRITY", "store closes reopens and verifies")
def _():
    registries = build_live_registries()
    with tempfile.TemporaryDirectory(prefix="stage6_1b_restart_") as folder:
        root = Path(folder); db = root / "store.sqlite3"; raw = root / "raw"
        with IngestionStore(db, raw) as store:
            store.import_registry(registries["entity_v1"]); store.import_registry(registries["source_v1"])
            acquire(store, registries["source_v1"], registries["entity_v1"], FakeTransport())
        with IngestionStore(db, raw) as store: require(store.integrity_check()["result"] == "PASS")

@check("INTEGRITY", "connector evidence cannot be overwritten")
def _():
    with live_store() as (store, _, source, entity):
        record = acquire(store, source, entity, FakeTransport())["record"]
        expect(sqlite3.IntegrityError,
               lambda: store.connection.execute("UPDATE ingestion_records SET retrieval_status='FAILED' WHERE record_id=?", (record["evidence_id"],)),
               "IMMUTABLE_TABLE_UPDATE")

@check("INTEGRITY", "connector registry snapshots cannot be overwritten")
def _():
    with live_store() as (store, _, source, entity):
        expect(sqlite3.IntegrityError,
               lambda: store.connection.execute("UPDATE registry_snapshots SET registry_version=9 WHERE snapshot_id=?", (source["registry_snapshot_id"],)),
               "IMMUTABLE_TABLE_UPDATE")

@check("INTEGRITY", "exact connector retry cannot overwrite raw payload object")
def _():
    with live_store() as (store, _, source, entity):
        first = acquire(store, source, entity, FakeTransport())["record"]
        path = store.raw_store.path_for(first["raw_payload_hash"]); before = path.read_bytes()
        acquire(store, source, entity, FakeTransport())
        require(path.read_bytes() == before == VALID_RSS)

@check("IDEMPOTENCY", "exact retry is idempotent")
def _():
    with live_store() as (store, _, source, entity):
        first = acquire(store, source, entity, FakeTransport()); second = acquire(store, source, entity, FakeTransport())
        require(first["record"]["evidence_id"] == second["record"]["evidence_id"] and second["status"] == "IDEMPOTENT_SUCCESS")

@check("IDEMPOTENCY", "changed retrieved timestamp creates later immutable observation")
def _():
    with live_store() as (store, _, source, entity):
        first = acquire(store, source, entity, FakeTransport())
        later = FakeTransport(good_response(retrieved="2026-09-25T15:00:02Z"))
        second = acquire(store, source, entity, later)
        require(first["record"]["evidence_id"] != second["record"]["evidence_id"])

@check("IDEMPOTENCY", "changed payload creates distinct immutable observation")
def _():
    with live_store() as (store, _, source, entity):
        first = acquire(store, source, entity, FakeTransport())
        changed = VALID_RSS.replace(b"Synthetic regulatory publication", b"Changed synthetic publication")
        second = acquire(store, source, entity, FakeTransport(good_response(body=changed)))
        require(first["record"]["evidence_id"] != second["record"]["evidence_id"])

@check("IDEMPOTENCY", "changed registry snapshot changes evidence binding")
def _():
    registries = build_live_registries(); successor = source_v2(changed=False)
    with live_store() as (store, _, source, entity):
        store.import_registry(successor)
        result = acquire(store, successor, entity, FakeTransport(good_response(retrieved="2026-09-26T01:00:01Z")), observed="2026-09-26T01:00:00Z")
        require(result["record"]["source_registry_snapshot_id"] == successor["registry_snapshot_id"])

@check("IDEMPOTENCY", "changed source record version changes evidence binding")
def _():
    successor = source_v2(changed=True)
    with live_store() as (store, _, source, entity):
        store.import_registry(successor)
        result = acquire(store, successor, entity, FakeTransport(good_response(retrieved="2026-09-26T01:00:01Z")), observed="2026-09-26T01:00:00Z")
        require(result["record"]["source_record_version"] == 2)

@check("BOUNDARY", "connector import has no network side effect")
def _():
    source = (STAGE_ROOT / "stage6_connectors" / "__init__.py").read_text(encoding="utf-8")
    require("fetch(" not in source and "run_live(" not in source)

@check("BOUNDARY", "connector contains no BUY SELL ranking ML or broker path")
def _():
    text = "\n".join(path.read_text(encoding="utf-8").casefold() for path in (STAGE_ROOT / "stage6_connectors").glob("*.py"))
    for prohibited in ("place_order", "cancel_order", "rank_securities", "sentiment_score", "ml_model"):
        require(prohibited not in text)
    tree = ast.parse((STAGE_ROOT / "stage6_connectors" / "sebi_rss.py").read_text(encoding="utf-8"))
    string_values = {node.value.casefold() for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    require(not ({"buy", "sell", "hold"} & string_values))

@check("BOUNDARY", "only fixed SEBI host appears in connector URLs")
def _():
    text = "\n".join(path.read_text(encoding="utf-8") for path in (STAGE_ROOT / "stage6_connectors").glob("*.py"))
    require("nseindia" not in text.casefold() and "yahoo" not in text.casefold() and "gdelt" not in text.casefold())

@check("BOUNDARY", "Stage 6.1A ingestion foundation unchanged")
def _(): require(git("diff", "--name-only", BASELINE_COMMIT, "--", "Stage 6/stage6_ingestion") == "")

@check("BOUNDARY", "frozen Stage 6 architecture unchanged")
def _():
    paths = ["Stage 6/contracts", "Stage 6/policy", "Stage 6/Stage6_Master_Architecture.md", "Stage 6/results/stage6_0_architecture_contract.json", "Stage 6/scripts/validate_stage6_0.py"]
    require(git("diff", "--name-only", ARCHITECTURE_TAG, "--", *paths) == "")

@check("BOUNDARY", "Stage 5D unchanged")
def _(): require(git("diff", "--name-only", PRODUCTION_TAG, "--", "Stage 5D") == "")


def main() -> int:
    rows: list[dict[str, str]] = []
    for number, (category, name, function) in enumerate(CHECKS, 1):
        try:
            with mock.patch.object(socket, "socket", side_effect=AssertionError("OFFLINE_TEST_NETWORK_USED")):
                function()
            rows.append({"test_id": f"S6_1B_{number:03d}", "category": category, "test_name": name, "result": "PASS", "detail": ""})
        except Exception as exc:
            rows.append({"test_id": f"S6_1B_{number:03d}", "category": category, "test_name": name, "result": "FAIL", "detail": f"{type(exc).__name__}:{exc}"})
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULT_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["test_id", "category", "test_name", "result", "detail"], lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    failed = [row for row in rows if row["result"] != "PASS"]
    print(json.dumps({"stage": "6.1B", "tests": len(rows), "passed": len(rows) - len(failed),
                      "failed": len(failed), "result": "PASS" if not failed else "FAIL",
                      "authority": AUTHORITY, "offline": True, "network_calls": 0},
                     sort_keys=True, separators=(",", ":")))
    for row in failed:
        print(f"FAIL {row['test_id']} {row['test_name']}: {row['detail']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
