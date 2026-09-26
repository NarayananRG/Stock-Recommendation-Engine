"""Deterministic, socket-free Stage 6.1C multi-source acceptance tests."""
from __future__ import annotations

import ast
import csv
import inspect
import json
import socket
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
    RBI_ENTITY_ID, RBI_REVIEWED_AT_UTC, RBI_SOURCE_ID, SEBI_ENTITY_ID, SEBI_SOURCE_ID,
    build_live_registries, build_multisource_registries,
)
from stage6_connectors.official_rss import OfficialRssConnector
from stage6_connectors.policy import (
    APPROVED_ENDPOINTS, EndpointPolicy, EndpointPolicyError, RBI_ENDPOINT, RBI_RSS_URL,
    SEBI_ENDPOINT, endpoint_for_source, validate_endpoint, validate_redirect,
)
from stage6_connectors.rbi_rss import RbiRssConnector
from stage6_connectors.sebi_rss import SebiRssConnector
from stage6_connectors.transport import ControlledHttpsTransport, TransportFailure, TransportResponse
from stage6_ingestion.canonical import canonical_json, sha256_bytes, without
from stage6_ingestion.errors import IntegrityFailure, ResolutionError
from stage6_ingestion.evidence_store import AUTHORITY, IngestionStore
from stage6_ingestion.registry import (
    build_entity_registry, build_source_registry, verify_entity_registry, verify_source_registry,
)


BASELINE_1B = "680f07926b51c6473f4069f93a3d1c679ca438cd"
ARCHITECTURE_TAG = "stage6-decision-intelligence-architecture-baseline-v2"
PRODUCTION_TAG = "stage5d5-live-paper-runner-baseline"
RESULT_PATH = STAGE_ROOT / "results" / "stage6_1c_test_results.csv"
RBI_RSS = (STAGE_ROOT / "fixtures" / "stage6_1c" / "valid_rbi_press_releases_rss.xml").read_bytes()
SEBI_RSS = (STAGE_ROOT / "fixtures" / "stage6_1b" / "valid_sebi_rss.xml").read_bytes()
OBSERVED = "2026-09-26T08:00:00Z"
RETRIEVED = "2026-09-26T08:00:01Z"
REGISTRIES = build_multisource_registries()
CHECKS: list[tuple[str, str, object]] = []


def check(category: str, name: str):
    def register(function):
        CHECKS.append((category, name, function)); return function
    return register


def require(condition: object, message: str = "assertion failed") -> None:
    if not condition: raise AssertionError(message)


def expect(error: type[BaseException], function, contains: str | None = None) -> BaseException:
    try: function()
    except error as exc:
        if contains is not None: require(contains in str(exc), f"expected {contains!r} in {exc!r}")
        return exc
    raise AssertionError(f"expected {error.__name__}")


class FakeTransport:
    def __init__(self, response: TransportResponse | None = None, failure: TransportFailure | None = None):
        self.response = response or rbi_response(); self.failure = failure; self.request_count = 0
    def fetch(self):
        self.request_count += 1
        if self.failure: raise self.failure
        return self.response


def rbi_response(*, body: bytes = RBI_RSS, content_type: str = "application/rss+xml; charset=UTF-8",
                 status: int = 200, retrieved: str = RETRIEVED, truncated: bool = False):
    return TransportResponse(status=status, headers={"content-type": content_type}, body=body,
                             retrieved_timestamp_utc=retrieved, final_url=RBI_RSS_URL, truncated=truncated)


def sebi_response(*, body: bytes = SEBI_RSS, retrieved: str = RETRIEVED):
    return TransportResponse(status=200, headers={"content-type": "application/rss+xml"}, body=body,
                             retrieved_timestamp_utc=retrieved, final_url=SEBI_ENDPOINT.url)


@contextmanager
def store_with_versions(*, source_v2=None, entity_v2=None, include_v2: bool = True):
    source2 = source_v2 or REGISTRIES["source_v2"]; entity2 = entity_v2 or REGISTRIES["entity_v2"]
    with tempfile.TemporaryDirectory(prefix="stage6_1c_test_") as folder:
        root = Path(folder)
        with IngestionStore(root / "store.sqlite3", root / "raw") as store:
            store.import_registry(REGISTRIES["entity_v1"]); store.import_registry(REGISTRIES["source_v1"])
            if include_v2:
                store.import_registry(entity2); store.import_registry(source2)
            yield store, root, source2, entity2


def rbi_acquire(store, source, entity, transport, observed: str = OBSERVED):
    return RbiRssConnector(store, transport).acquire(
        source_registry_snapshot_id=source["registry_snapshot_id"],
        entity_registry_snapshot_id=entity["registry_snapshot_id"], observed_timestamp_utc=observed)


def sebi_acquire(store, source, entity, transport, observed: str = OBSERVED):
    return SebiRssConnector(store, transport).acquire(
        source_registry_snapshot_id=source["registry_snapshot_id"],
        entity_registry_snapshot_id=entity["registry_snapshot_id"], observed_timestamp_utc=observed)


def source_v2_with(**changes):
    records = deepcopy(REGISTRIES["source_v2"]["sources"])
    next(row for row in records if row["source_id"] == RBI_SOURCE_ID).update(changes)
    return build_source_registry(records, RBI_REVIEWED_AT_UTC, REGISTRIES["source_v1"])


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()


@check("IDENTITY", "Stage 6.1B baseline is in HEAD ancestry")
def _(): subprocess.check_call(["git", "merge-base", "--is-ancestor", BASELINE_1B, "HEAD"], cwd=REPO_ROOT)

@check("IDENTITY", "authority remains SHADOW_ONLY")
def _(): require(AUTHORITY == "SHADOW_ONLY")

@check("REGISTRY_V2", "Entity Registry V1 to V2 verifies")
def _(): require(verify_entity_registry(REGISTRIES["entity_v2"], REGISTRIES["entity_v1"])["registry_version"] == 2)

@check("REGISTRY_V2", "Source Registry V1 to V2 verifies")
def _(): require(verify_source_registry(REGISTRIES["source_v2"], REGISTRIES["source_v1"])["registry_version"] == 2)

@check("REGISTRY_V2", "Entity V2 predecessor hash exact")
def _(): require(REGISTRIES["entity_v2"]["previous_registry_hash"] == REGISTRIES["entity_v1"]["registry_hash"])

@check("REGISTRY_V2", "Source V2 predecessor hash exact")
def _(): require(REGISTRIES["source_v2"]["previous_registry_hash"] == REGISTRIES["source_v1"]["registry_hash"])

@check("REGISTRY_V2", "registry versions contiguous")
def _(): require([REGISTRIES[k]["registry_version"] for k in ("entity_v1", "entity_v2", "source_v1", "source_v2")] == [1, 2, 1, 2])

@check("REGISTRY_V2", "SEBI entity record unchanged and hash stable")
def _():
    old = next(row for row in REGISTRIES["entity_v1"]["entities"] if row["entity_id"] == SEBI_ENTITY_ID)
    new = next(row for row in REGISTRIES["entity_v2"]["entities"] if row["entity_id"] == SEBI_ENTITY_ID)
    require(old == new and old["record_hash"] == new["record_hash"])

@check("REGISTRY_V2", "SEBI source record unchanged and hash stable")
def _():
    old = next(row for row in REGISTRIES["source_v1"]["sources"] if row["source_id"] == SEBI_SOURCE_ID)
    new = next(row for row in REGISTRIES["source_v2"]["sources"] if row["source_id"] == SEBI_SOURCE_ID)
    require(old == new and old["record_hash"] == new["record_hash"])

@check("REGISTRY_V2", "RBI entity begins record V1 with null predecessor")
def _():
    row = next(row for row in REGISTRIES["entity_v2"]["entities"] if row["entity_id"] == RBI_ENTITY_ID)
    require(row["entity_record_version"] == 1 and row["previous_version_hash"] is None and row["ticker_mappings"] == [])

@check("REGISTRY_V2", "RBI source begins record V1 with null predecessor")
def _():
    row = next(row for row in REGISTRIES["source_v2"]["sources"] if row["source_id"] == RBI_SOURCE_ID)
    require(row["source_record_version"] == 1 and row["previous_version_hash"] is None)

@check("REGISTRY_V2", "complete V2 snapshots deterministic")
def _(): require(build_multisource_registries() == build_multisource_registries())

@check("REGISTRY_V2", "V1 snapshots remain byte-canonical stable")
def _():
    rebuilt = build_live_registries()
    require(canonical_json(rebuilt["entity_v1"]) == canonical_json(REGISTRIES["entity_v1"]))
    require(canonical_json(rebuilt["source_v1"]) == canonical_json(REGISTRIES["source_v1"]))

@check("REGISTRY_V2", "tampered V1 predecessor causes V2 verification failure")
def _():
    bad = deepcopy(REGISTRIES["source_v1"]); bad["sources"][0]["source_name"] = "tampered"
    expect(IntegrityFailure, lambda: verify_source_registry(REGISTRIES["source_v2"], bad))

@check("REGISTRY_V2", "skipped registry version rejected")
def _():
    bad = deepcopy(REGISTRIES["source_v2"]); bad["registry_version"] = 3
    expect(IntegrityFailure, lambda: verify_source_registry(bad, REGISTRIES["source_v1"]), "REGISTRY_VERSION_GAP")

@check("REGISTRY_V2", "wrong previous registry hash rejected")
def _():
    bad = deepcopy(REGISTRIES["entity_v2"]); bad["previous_registry_hash"] = "0" * 64
    expect(IntegrityFailure, lambda: verify_entity_registry(bad, REGISTRIES["entity_v1"]), "REGISTRY_PREVIOUS_HASH_MISMATCH")

@check("RBI_APPROVAL", "approved RBI source reaches fake transport")
def _():
    with store_with_versions() as (store, _, source, entity):
        transport = FakeTransport(); rbi_acquire(store, source, entity, transport); require(transport.request_count == 1)


def _approval_blocked(changes):
    source = source_v2_with(**changes)
    with store_with_versions(source_v2=source) as (store, _, source, entity):
        transport = FakeTransport()
        expect(ResolutionError, lambda: rbi_acquire(store, source, entity, transport), "SOURCE_NOT_APPROVED_FOR_AUTOMATION")
        require(transport.request_count == 0)


for _label, _changes in [
    ("disabled", {"enabled": False}), ("pending review", {"verification_status": "PENDING_REVIEW"}),
    ("disabled verification", {"verification_status": "DISABLED"}),
    ("rejected verification", {"verification_status": "REJECTED"}),
    ("unknown automation", {"automation_allowed_status": "UNKNOWN"}),
    ("prohibited automation", {"automation_allowed_status": "PROHIBITED"}),
    ("pending terms", {"licensing_or_terms_status": "PENDING_REVIEW"}),
    ("restricted terms", {"licensing_or_terms_status": "REVIEWED_RESTRICTED"}),
]:
    check("RBI_APPROVAL", f"RBI {_label} blocks before transport")(
        lambda changes=_changes: _approval_blocked(changes))

@check("RBI_APPROVAL", "wrong RBI source record hash blocks before transport")
def _():
    with store_with_versions() as (store, _, source, entity):
        row = store.connection.execute("SELECT canonical_json FROM registry_snapshots WHERE registry_kind='SOURCE' AND registry_version=2").fetchone()
        bad = json.loads(row[0]); next(x for x in bad["sources"] if x["source_id"] == RBI_SOURCE_ID)["source_name"] = "tampered"
        store.connection.execute("DROP TRIGGER protect_registry_snapshots_update")
        store.connection.execute("UPDATE registry_snapshots SET canonical_json=? WHERE registry_kind='SOURCE' AND registry_version=2", (canonical_json(bad),)); store.connection.commit()
        transport = FakeTransport(); expect(IntegrityFailure, lambda: rbi_acquire(store, source, entity, transport)); require(transport.request_count == 0)

@check("RBI_APPROVAL", "wrong source snapshot hash blocks before transport")
def _():
    with store_with_versions() as (store, _, source, entity):
        row = store.connection.execute("SELECT canonical_json FROM registry_snapshots WHERE registry_kind='SOURCE' AND registry_version=2").fetchone()
        bad = json.loads(row[0]); bad["registry_hash"] = "0" * 64
        store.connection.execute("DROP TRIGGER protect_registry_snapshots_update")
        store.connection.execute("UPDATE registry_snapshots SET canonical_json=? WHERE registry_kind='SOURCE' AND registry_version=2", (canonical_json(bad),)); store.connection.commit()
        transport = FakeTransport(); expect(IntegrityFailure, lambda: rbi_acquire(store, source, entity, transport)); require(transport.request_count == 0)

@check("RBI_APPROVAL", "missing RBI entity blocks before transport")
def _():
    entity = build_entity_registry(deepcopy(REGISTRIES["entity_v1"]["entities"]), RBI_REVIEWED_AT_UTC, REGISTRIES["entity_v1"])
    with store_with_versions(entity_v2=entity) as (store, _, source, entity):
        transport = FakeTransport(); expect(ResolutionError, lambda: rbi_acquire(store, source, entity, transport), "ENTITY_NOT_FOUND"); require(transport.request_count == 0)

@check("RBI_APPROVAL", "future V2 registry blocks before transport")
def _():
    with store_with_versions() as (store, _, source, entity):
        transport = FakeTransport()
        expect(IntegrityFailure, lambda: rbi_acquire(store, source, entity, transport, observed="2026-09-26T06:00:00Z"), "REGISTRY_SNAPSHOT_FROM_FUTURE")
        require(transport.request_count == 0)

@check("ENDPOINT_POLICY", "exact RBI endpoint accepted")
def _(): require(validate_endpoint(RBI_RSS_URL, RBI_ENDPOINT) == RBI_RSS_URL)

for _label, _url, _error in [
    ("HTTP rejected", "http://rbi.org.in/pressreleases_rss.xml", "HTTPS_REQUIRED"),
    ("localhost rejected", "https://localhost/pressreleases_rss.xml", "ENDPOINT_HOST_PROHIBITED"),
    ("IPv4 rejected", "https://127.0.0.1/pressreleases_rss.xml", "ENDPOINT_HOST_PROHIBITED"),
    ("IPv6 rejected", "https://[::1]/pressreleases_rss.xml", "ENDPOINT_HOST_PROHIBITED"),
    ("file rejected", "file:///pressreleases_rss.xml", "HTTPS_REQUIRED"),
    ("FTP rejected", "ftp://rbi.org.in/pressreleases_rss.xml", "HTTPS_REQUIRED"),
    ("arbitrary host rejected", "https://attacker.example/pressreleases_rss.xml", "ENDPOINT_HOST_PROHIBITED"),
    ("unapproved www host rejected", "https://www.rbi.org.in/pressreleases_rss.xml", "ENDPOINT_HOST_PROHIBITED"),
    ("arbitrary path rejected", "https://rbi.org.in/notifications_rss.xml", "ENDPOINT_PATH_PROHIBITED"),
    ("port rejected", "https://rbi.org.in:8443/pressreleases_rss.xml", "ENDPOINT_PORT_PROHIBITED"),
    ("query substitution rejected", "https://rbi.org.in/pressreleases_rss.xml?next=evil", "ENDPOINT_SUFFIX_PROHIBITED"),
]:
    check("ENDPOINT_POLICY", f"RBI {_label}")(
        lambda url=_url, error=_error: expect(EndpointPolicyError, lambda: validate_endpoint(url, RBI_ENDPOINT), error))

@check("ENDPOINT_POLICY", "RBI cross-domain redirect rejected")
def _(): expect(EndpointPolicyError, lambda: validate_redirect(RBI_RSS_URL, "https://attacker.example/x", RBI_ENDPOINT), "ENDPOINT_HOST_PROHIBITED")

@check("ENDPOINT_POLICY", "RBI localhost redirect rejected")
def _(): expect(EndpointPolicyError, lambda: validate_redirect(RBI_RSS_URL, "https://localhost/x", RBI_ENDPOINT), "ENDPOINT_HOST_PROHIBITED")

@check("ENDPOINT_POLICY", "RBI redirect downgrade rejected")
def _(): expect(EndpointPolicyError, lambda: validate_redirect(RBI_RSS_URL, "http://rbi.org.in/pressreleases_rss.xml", RBI_ENDPOINT), "HTTPS_REQUIRED")


class FakeHttpResponse:
    def __init__(self, status, body=b"", headers=None): self.status=status; self.body=body; self.offset=0; self.headers=headers or []
    def getheaders(self): return self.headers
    def read(self, size=-1):
        if self.offset >= len(self.body): return b""
        end = len(self.body) if size < 0 else min(len(self.body), self.offset + size)
        chunk=self.body[self.offset:end]; self.offset=end; return chunk

class FakeConnection:
    def __init__(self, response): self.response=response
    def request(self, *_args, **_kwargs): pass
    def getresponse(self): return self.response
    def close(self): pass

@check("ENDPOINT_POLICY", "RBI redirect limit enforced")
def _():
    response=FakeHttpResponse(302, headers=[("Location", RBI_RSS_URL)])
    transport=ControlledHttpsTransport(endpoint=RBI_ENDPOINT, max_redirects=0, connection_factory=lambda *_a, **_k: FakeConnection(response))
    expect(TransportFailure, transport.fetch, "REDIRECT_LIMIT_EXCEEDED")

@check("RBI_EVIDENCE", "valid RBI RSS creates retrieved evidence")
def _():
    with store_with_versions() as (store, _, source, entity): require(rbi_acquire(store, source, entity, FakeTransport())["outcome"] == "RETRIEVED")

@check("RBI_EVIDENCE", "RBI exact response bytes and deterministic hash preserved")
def _():
    with store_with_versions() as (store, _, source, entity):
        record=rbi_acquire(store, source, entity, FakeTransport())["record"]
        require(record["raw_payload_hash"] == sha256_bytes(RBI_RSS)); require(store.raw_store.path_for(record["raw_payload_hash"]).read_bytes() == RBI_RSS)

@check("RBI_EVIDENCE", "RBI source authority and entity binding exact")
def _():
    with store_with_versions() as (store, _, source, entity):
        record=rbi_acquire(store, source, entity, FakeTransport())["record"]
        require((record["source_id"], record["authority_level"], record["entity_ids"]) == (RBI_SOURCE_ID, "PRIMARY_OFFICIAL", [RBI_ENTITY_ID]))

@check("RBI_EVIDENCE", "RBI item links and enclosures never fetched")
def _():
    with store_with_versions() as (store, _, source, entity):
        transport=FakeTransport(); rbi_acquire(store, source, entity, transport); require(transport.request_count == 1)

for _label, _response, _reason in [
    ("malformed XML", rbi_response(body=b"<rss><broken>"), "MALFORMED_XML"),
    ("HTML", rbi_response(body=b"<html>blocked</html>", content_type="text/html"), "CONTENT_TYPE_REJECTED"),
    ("wrong content type", rbi_response(content_type="application/json"), "CONTENT_TYPE_REJECTED"),
    ("DTD entity declaration", rbi_response(body=b'<!DOCTYPE rss [<!ENTITY x "y">]><rss><channel/></rss>'), "XML_EXTERNAL_OR_ENTITY_DECLARATION_REJECTED"),
    ("truncated payload", rbi_response(truncated=True), "TRUNCATED_PAYLOAD"),
]:
    @check("RBI_EVIDENCE", f"RBI {_label} quarantined with bytes preserved")
    def _(response=_response, reason=_reason):
        with store_with_versions() as (store, _, source, entity):
            result=rbi_acquire(store, source, entity, FakeTransport(response)); require(result["outcome"] == "QUARANTINED" and result["reason"] == reason)
            require(store.raw_store.path_for(result["record"]["raw_payload_hash"]).read_bytes() == response.body)

@check("RBI_EVIDENCE", "future RBI publisher timestamp quarantined")
def _():
    body=b'<rss><channel><title>RBI</title><pubDate>Sat, 26 Sep 2026 14:00:00 +0530</pubDate></channel></rss>'
    with store_with_versions() as (store, _, source, entity):
        result=rbi_acquire(store, source, entity, FakeTransport(rbi_response(body=body)))
        require(result["outcome"] == "QUARANTINED" and result["record"]["publication_timestamp_utc"] is None)

@check("RBI_EVIDENCE", "missing RBI publication timestamp remains null")
def _():
    body=b'<rss><channel><title>RBI</title></channel></rss>'
    with store_with_versions() as (store, _, source, entity):
        result=rbi_acquire(store, source, entity, FakeTransport(rbi_response(body=body)))
        require(result["outcome"] == "RETRIEVED" and result["record"]["publication_timestamp_utc"] is None)

for _label, _code in [("timeout", "TIMEOUT"), ("DNS", "DNS_FAILURE"), ("TLS", "TLS_FAILURE")]:
    @check("FAILURE_SEMANTICS", f"RBI {_label} becomes FAILED attempt")
    def _(code=_code):
        with store_with_versions() as (store, _, source, entity):
            record=rbi_acquire(store, source, entity, FakeTransport(failure=TransportFailure(code)))["record"]
            require(record["record_kind"] == "ACQUISITION_ATTEMPT" and record["retrieval_status"] == "FAILED")

for _status, _expected in [(404,"NOT_FOUND"),(401,"ACCESS_DENIED"),(403,"ACCESS_DENIED"),(500,"FAILED")]:
    @check("FAILURE_SEMANTICS", f"RBI HTTP {_status} maps to {_expected}")
    def _(status=_status, expected=_expected):
        with store_with_versions() as (store, _, source, entity):
            record=rbi_acquire(store, source, entity, FakeTransport(rbi_response(status=status)))["record"]
            require(record["record_kind"] == "ACQUISITION_ATTEMPT" and record["retrieval_status"] == expected)

@check("HISTORICAL_COEXISTENCE", "old SEBI V1 evidence survives V2 import and integrity")
def _():
    with store_with_versions(include_v2=False) as (store, _, _, _):
        old=sebi_acquire(store, REGISTRIES["source_v1"], REGISTRIES["entity_v1"], FakeTransport(sebi_response()), observed="2026-09-25T15:00:00Z")["record"]
        store.import_registry(REGISTRIES["entity_v2"]); store.import_registry(REGISTRIES["source_v2"])
        require(store.get_record(old["evidence_id"])["source_registry_version"] == 1 and store.integrity_check()["result"] == "PASS")

@check("HISTORICAL_COEXISTENCE", "new SEBI acquisition under complete V2 succeeds")
def _():
    with store_with_versions() as (store, _, source, entity):
        record=sebi_acquire(store, source, entity, FakeTransport(sebi_response()))["record"]
        require(record["source_id"] == SEBI_SOURCE_ID and record["source_registry_version"] == 2 and record["entity_registry_version"] == 2)

@check("HISTORICAL_COEXISTENCE", "RBI cannot acquire against V1 and makes zero requests")
def _():
    with store_with_versions(include_v2=False) as (store, _, _, _):
        transport=FakeTransport()
        expect(ResolutionError, lambda: rbi_acquire(store, REGISTRIES["source_v1"], REGISTRIES["entity_v1"], transport), "SOURCE_NOT_FOUND")
        require(transport.request_count == 0)

@check("HISTORICAL_COEXISTENCE", "RBI acquisition under V2 succeeds")
def _():
    with store_with_versions() as (store, _, source, entity): require(rbi_acquire(store, source, entity, FakeTransport())["record"]["source_registry_version"] == 2)

@check("HISTORICAL_COEXISTENCE", "SEBI and RBI identities do not cross-bind")
def _():
    with store_with_versions() as (store, _, source, entity):
        sebi=sebi_acquire(store, source, entity, FakeTransport(sebi_response()))["record"]
        rbi=rbi_acquire(store, source, entity, FakeTransport())["record"]
        require((sebi["source_id"],sebi["entity_ids"]) == (SEBI_SOURCE_ID,[SEBI_ENTITY_ID]))
        require((rbi["source_id"],rbi["entity_ids"]) == (RBI_SOURCE_ID,[RBI_ENTITY_ID]))

@check("HISTORICAL_COEXISTENCE", "SEBI and RBI raw bytes remain source-bound and distinct")
def _():
    with store_with_versions() as (store, _, source, entity):
        sebi=sebi_acquire(store, source, entity, FakeTransport(sebi_response()))["record"]
        rbi=rbi_acquire(store, source, entity, FakeTransport())["record"]
        require(sebi["raw_payload_hash"] == sha256_bytes(SEBI_RSS) and rbi["raw_payload_hash"] == sha256_bytes(RBI_RSS))
        require(sebi["raw_payload_hash"] != rbi["raw_payload_hash"])

@check("HISTORICAL_COEXISTENCE", "complete multi-source store restart integrity passes")
def _():
    with tempfile.TemporaryDirectory(prefix="stage6_1c_restart_") as folder:
        root=Path(folder); db=root/"store.sqlite3"; raw=root/"raw"
        with IngestionStore(db,raw) as store:
            for version in ("v1","v2"):
                store.import_registry(REGISTRIES[f"entity_{version}"]); store.import_registry(REGISTRIES[f"source_{version}"])
            sebi_acquire(store, REGISTRIES["source_v2"], REGISTRIES["entity_v2"], FakeTransport(sebi_response()))
            rbi_acquire(store, REGISTRIES["source_v2"], REGISTRIES["entity_v2"], FakeTransport())
        with IngestionStore(db,raw) as store: require(store.integrity_check()["result"] == "PASS")

@check("IDEMPOTENCY", "exact RBI retry is idempotent")
def _():
    with store_with_versions() as (store, _, source, entity):
        first=rbi_acquire(store,source,entity,FakeTransport()); second=rbi_acquire(store,source,entity,FakeTransport())
        require(second["status"] == "IDEMPOTENT_SUCCESS" and first["record"]["evidence_id"] == second["record"]["evidence_id"])

@check("IDEMPOTENCY", "changed RBI retrieved timestamp creates later observation")
def _():
    with store_with_versions() as (store, _, source, entity):
        first=rbi_acquire(store,source,entity,FakeTransport())["record"]
        second=rbi_acquire(store,source,entity,FakeTransport(rbi_response(retrieved="2026-09-26T08:00:02Z")))["record"]
        require(first["evidence_id"] != second["evidence_id"])

@check("IDEMPOTENCY", "changed RBI payload creates new observation")
def _():
    with store_with_versions() as (store, _, source, entity):
        first=rbi_acquire(store,source,entity,FakeTransport())["record"]
        changed=RBI_RSS.replace(b"Synthetic central-bank press release",b"Changed central-bank press release")
        second=rbi_acquire(store,source,entity,FakeTransport(rbi_response(body=changed)))["record"]
        require(first["evidence_id"] != second["evidence_id"])

@check("IDEMPOTENCY", "changed registry snapshot changes RBI binding")
def _():
    source_records=deepcopy(REGISTRIES["source_v2"]["sources"]); entity_records=deepcopy(REGISTRIES["entity_v2"]["entities"])
    source3=build_source_registry(source_records,"2026-09-27T00:00:00Z",REGISTRIES["source_v2"])
    entity3=build_entity_registry(entity_records,"2026-09-27T00:00:00Z",REGISTRIES["entity_v2"])
    with store_with_versions() as (store, _, source, entity):
        store.import_registry(entity3); store.import_registry(source3)
        record=rbi_acquire(store,source3,entity3,FakeTransport(rbi_response(retrieved="2026-09-27T01:00:01Z")),observed="2026-09-27T01:00:00Z")["record"]
        require(record["source_registry_version"] == 3 and record["entity_registry_version"] == 3)

@check("IDEMPOTENCY", "RBI source record version change binds exactly")
def _():
    records=deepcopy(REGISTRIES["source_v2"]["sources"]); rbi=next(row for row in records if row["source_id"] == RBI_SOURCE_ID)
    rbi["source_record_version"]=2; rbi["previous_version_hash"]=rbi["record_hash"]; rbi["availability_notes"]="V2 test review"; rbi["reviewed_at_utc"]="2026-09-27T00:00:00Z"
    source3=build_source_registry(records,"2026-09-27T00:00:00Z",REGISTRIES["source_v2"])
    with store_with_versions() as (store, _, source, entity):
        store.import_registry(source3)
        record=rbi_acquire(store,source3,entity,FakeTransport(rbi_response(retrieved="2026-09-27T01:00:01Z")),observed="2026-09-27T01:00:00Z")["record"]
        require(record["source_record_version"] == 2)

@check("IDEMPOTENCY", "RBI evidence registry and raw objects cannot be overwritten")
def _():
    with store_with_versions() as (store, _, source, entity):
        record=rbi_acquire(store,source,entity,FakeTransport())["record"]; path=store.raw_store.path_for(record["raw_payload_hash"]); before=path.read_bytes()
        expect(sqlite3.IntegrityError,lambda: store.connection.execute("UPDATE ingestion_records SET retrieval_status='FAILED' WHERE record_id=?",(record["evidence_id"],)),"IMMUTABLE_TABLE_UPDATE")
        expect(sqlite3.IntegrityError,lambda: store.connection.execute("UPDATE registry_snapshots SET registry_version=9 WHERE snapshot_id=?",(source["registry_snapshot_id"],)),"IMMUTABLE_TABLE_UPDATE")
        rbi_acquire(store,source,entity,FakeTransport()); require(path.read_bytes() == before)

@check("BOUNDARY", "unknown source ID fails before transport construction")
def _(): expect(ValueError,lambda: OfficialRssConnector(None,"UNKNOWN_SOURCE"),"SOURCE_CONNECTOR_NOT_APPROVED")

@check("BOUNDARY", "unapproved endpoint definition rejected")
def _():
    bad=EndpointPolicy("BAD","https","attacker.example","/x","bad")
    expect(EndpointPolicyError,lambda: ControlledHttpsTransport(endpoint=bad),"SOURCE_ENDPOINT_NOT_APPROVED")

@check("BOUNDARY", "transport fetch accepts no URL argument")
def _(): require(list(inspect.signature(ControlledHttpsTransport.fetch).parameters) == ["self"])

@check("BOUNDARY", "connector imports have no network execution")
def _():
    for path in (STAGE_ROOT/"stage6_connectors").glob("*.py"):
        tree=ast.parse(path.read_text(encoding="utf-8")); require(not any(isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and getattr(n.value.func,"attr","") == "fetch" for n in tree.body))

@check("BOUNDARY", "approved connector hosts are exact and complete")
def _(): require({endpoint.host for endpoint in APPROVED_ENDPOINTS} == {"www.sebi.gov.in","rbi.org.in"})

@check("BOUNDARY", "connector code contains no trading ranking broker or ML calls")
def _():
    text="\n".join(path.read_text(encoding="utf-8").casefold() for path in (STAGE_ROOT/"stage6_connectors").glob("*.py"))
    for prohibited in ("place_order","cancel_order","rank_securities","sentiment_score","ml_model","execute_trade"): require(prohibited not in text)

@check("BOUNDARY", "historical Stage 6.1A and 6.1B delivery files unchanged")
def _():
    paths=["Stage 6/Stage6_1A_Delivery_Report.md","Stage 6/results/stage6_1a_contract.json","Stage 6/results/stage6_1a_test_results.csv","Stage 6/Stage6_1B_Delivery_Report.md","Stage 6/results/stage6_1b_contract.json","Stage 6/results/stage6_1b_test_results.csv"]
    require(git("diff","--name-only",BASELINE_1B,"--",*paths) == "")

@check("BOUNDARY", "frozen Stage 6 architecture unchanged")
def _():
    paths=["Stage 6/contracts","Stage 6/policy","Stage 6/Stage6_Master_Architecture.md","Stage 6/results/stage6_0_architecture_contract.json","Stage 6/scripts/validate_stage6_0.py"]
    require(git("diff","--name-only",ARCHITECTURE_TAG,"--",*paths) == "")

@check("BOUNDARY", "Stage 5D unchanged")
def _(): require(git("diff","--name-only",PRODUCTION_TAG,"--","Stage 5D") == "")

@check("BOUNDARY", "runtime Stage 6.1C path is gitignored")
def _():
    result=subprocess.run(["git","check-ignore","-q","Stage 6/runtime/stage6_1c_test/store.sqlite3"],cwd=REPO_ROOT)
    require(result.returncode == 0)


def main() -> int:
    rows=[]
    for number,(category,name,function) in enumerate(CHECKS,1):
        try:
            with mock.patch.object(socket,"socket",side_effect=AssertionError("OFFLINE_TEST_NETWORK_USED")): function()
            rows.append({"test_id":f"S6_1C_{number:03d}","category":category,"test_name":name,"result":"PASS","detail":""})
        except Exception as exc:
            rows.append({"test_id":f"S6_1C_{number:03d}","category":category,"test_name":name,"result":"FAIL","detail":f"{type(exc).__name__}:{exc}"})
    RESULT_PATH.parent.mkdir(parents=True,exist_ok=True)
    with RESULT_PATH.open("w",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=["test_id","category","test_name","result","detail"],lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    failed=[row for row in rows if row["result"] != "PASS"]
    print(json.dumps({"stage":"6.1C","tests":len(rows),"passed":len(rows)-len(failed),"failed":len(failed),"result":"PASS" if not failed else "FAIL","authority":AUTHORITY,"offline":True,"network_calls":0},sort_keys=True,separators=(",",":")))
    for row in failed: print(f"FAIL {row['test_id']} {row['test_name']}: {row['detail']}")
    return 1 if failed else 0


if __name__ == "__main__": raise SystemExit(main())
