"""Create immutable checkpoint market archives through the frozen Stage 4A.3 adapter."""
from __future__ import annotations

import csv
import gzip
import json
import re
import shutil
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json, without

from .activation import verify_activation_record
from .checkpoint_builder import derive_final_exit
from .cohort_guard import verify_active_cohort
from .control_reader import Stage5DControlReader, parse_utc
from .errors import ProspectiveConflict, ProspectiveIntegrityFailure, Stage6ProspectiveError
from .observation_config import (
    AUTHORITY, OBSERVATION_CONTRACT, OBSERVATION_POLICY, OBSERVATION_STORE_SCHEMA,
    load_observation_contract, load_observation_policy,
)
from .observation_store import TABLES
from .recommendation_envelope import validate_envelope
from .verified_inputs import (
    COMPLETED_SESSION_TIME,
    IST,
    MARKET_CLASSIFICATION,
    MarketArchiveResolver,
    ProspectiveStoreReader,
    _sha256,
)

CREATOR_ID = "STAGE6_8C_CHECKPOINT_MARKET_ARCHIVE_CREATOR_V1"
ARCHIVE_SCHEMA = "STAGE6_8C_CHECKPOINT_MARKET_ARCHIVE_V1"
FROZEN_ADAPTER_ID = "STAGE4A3_FINAL_MARKET_DATA_ACQUIRE_AND_ARCHIVE_V1"
FROZEN_SOURCE_SCHEMA = "STAGE4A3_FINAL_MARKET_DATA_V1"
FROZEN_PROVIDER = "YFINANCE_REFRESH_VIA_FROZEN_STAGE2_2_1"
RUNTIME_RELATIVE = Path("Stage 6/runtime/prospective_validation/checkpoint_market_data")
CHECKPOINT_TYPES = ("D+5", "D+20", "D+60", "FINAL_EXIT")
SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9_.-]+$")


def validate_checkpoint_market_archive_root(path, repo_root, *, allow_test_runtime=False):
    root = Path(path).resolve(); repo = Path(repo_root).resolve()
    if allow_test_runtime:
        return root
    approved = (repo / RUNTIME_RELATIVE).resolve()
    try:
        root.relative_to(approved)
    except ValueError as exc:
        raise Stage6ProspectiveError("CHECKPOINT_MARKET_ARCHIVE_RUNTIME_BOUNDARY_VIOLATION") from exc
    if {part.casefold() for part in root.parts} & {"results", "fixtures", "fixture", "tests", "test"}:
        raise Stage6ProspectiveError("CHECKPOINT_MARKET_ARCHIVE_RUNTIME_BOUNDARY_VIOLATION")
    return root


def _safe_component(value: str, code: str) -> str:
    if not isinstance(value, str) or not SAFE_COMPONENT.fullmatch(value):
        raise Stage6ProspectiveError(code)
    return value


def _checkpoint_directory(runtime_root: Path, recommendation_id: str, checkpoint_type: str) -> Path:
    recommendation = _safe_component(recommendation_id, "RECOMMENDATION_ID_PATH_UNSAFE")
    label = _safe_component(checkpoint_type.replace("+", "PLUS"), "CHECKPOINT_TYPE_PATH_UNSAFE")
    return runtime_root / recommendation / label


def _read_envelope(database, recommendation_id: str, cohort: dict):
    path = Path(database).resolve()
    if not path.is_file():
        raise Stage6ProspectiveError("OBSERVATION_STORE_REQUIRED")
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row; connection.execute("PRAGMA query_only=ON")
    try:
        if connection.execute("PRAGMA query_only").fetchone()[0] != 1 or connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ProspectiveIntegrityFailure("OBSERVATION_STORE_INVALID")
        _, _, policy_hash = load_observation_policy(); _, _, contract_hash = load_observation_contract()
        meta = connection.execute("SELECT * FROM observation_store_meta").fetchall()
        expected_meta = (1, OBSERVATION_STORE_SCHEMA, OBSERVATION_POLICY, policy_hash,
                         OBSERVATION_CONTRACT, contract_hash, AUTHORITY, 0)
        if len(meta) != 1 or tuple(meta[0]) != expected_meta:
            raise ProspectiveIntegrityFailure("OBSERVATION_STORE_METADATA_INVALID")
        cohort_rows = connection.execute("SELECT * FROM cohort_fingerprints").fetchall()
        if (len(cohort_rows) != 1 or tuple(cohort_rows[0]) !=
                (cohort["cohort_fingerprint_id"], cohort["record_hash"], canonical_json(cohort))):
            raise ProspectiveIntegrityFailure("OBSERVATION_STORE_COHORT_INVALID")
        for table in TABLES:
            triggers = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,))}
            if triggers != {f"protect_{table}_update", f"protect_{table}_delete"}:
                raise ProspectiveIntegrityFailure("OBSERVATION_STORE_TRIGGER_INVALID:" + table)
        row = connection.execute("SELECT canonical_json,record_hash FROM recommendation_audit_envelopes WHERE recommendation_id=?", (recommendation_id,)).fetchone()
        if row is None:
            raise Stage6ProspectiveError("RECOMMENDATION_ENVELOPE_REQUIRED")
        envelope = json.loads(row["canonical_json"]); validate_envelope(envelope)
        if canonical_json(envelope) != row["canonical_json"] or envelope["record_hash"] != row["record_hash"]:
            raise ProspectiveIntegrityFailure("RECOMMENDATION_ENVELOPE_STORED_RECORD_INVALID")
        expected = {"record_type": cohort["schema_version"], "record_id": cohort["cohort_fingerprint_id"], "record_hash": cohort["record_hash"]}
        if envelope.get("cohort_fingerprint_binding") != expected:
            raise ProspectiveIntegrityFailure("RECOMMENDATION_ENVELOPE_COHORT_INVALID")
        existing = {r[0] for r in connection.execute("SELECT checkpoint_type FROM benchmark_checkpoints WHERE recommendation_id=?", (recommendation_id,))}
        return envelope, existing
    finally:
        connection.close()


@contextmanager
def _frozen_adapter(stage4a3_root: Path):
    inserted = str(stage4a3_root) not in sys.path
    if inserted:
        sys.path.insert(0, str(stage4a3_root))
    try:
        from stage4a3.final_market_data import acquire_and_archive
        yield acquire_and_archive
    finally:
        if inserted:
            sys.path.remove(str(stage4a3_root))


def _production_acquire(repo: Path, stage4a3_root: Path, target_date: str, archive_parent: Path, acquired_at: str):
    with _frozen_adapter(stage4a3_root) as acquire_and_archive:
        return acquire_and_archive(repo, stage4a3_root, target_date, archive_parent, acquired_at)


def _decimal_text(value, code: str):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ProspectiveIntegrityFailure(code) from exc
    if not number.is_finite():
        raise ProspectiveIntegrityFailure(code)
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _frame_rows(frame, ticker: str, dates: list[str], acquired_at: str, *, benchmark=False):
    source = frame.copy()
    if "Date" in source.columns:
        source = source.set_index("Date")
    source.index = source.index.map(lambda value: str(value)[:10])
    if source.index.duplicated().any():
        raise ProspectiveIntegrityFailure("FROZEN_MARKET_ARCHIVE_DUPLICATE_SESSION")
    columns = {str(column).casefold(): column for column in source.columns}
    required = ("close",) if benchmark else ("open", "high", "low", "close")
    if any(name not in columns for name in required):
        raise ProspectiveIntegrityFailure("FROZEN_MARKET_ARCHIVE_COLUMNS_INVALID")
    rows = []
    for session in dates:
        if session not in source.index:
            raise ProspectiveIntegrityFailure("FROZEN_MARKET_ARCHIVE_SESSION_MISSING")
        row = source.loc[session]
        if getattr(row, "ndim", 1) != 1:
            raise ProspectiveIntegrityFailure("FROZEN_MARKET_ARCHIVE_DUPLICATE_SESSION")
        value = {"ticker": ticker, "session_date": session, "observed_at_utc": acquired_at,
                 "close": _decimal_text(row[columns["close"]], "FROZEN_MARKET_ARCHIVE_VALUE_INVALID")}
        if not benchmark:
            value.update({name: _decimal_text(row[columns[name]], "FROZEN_MARKET_ARCHIVE_VALUE_INVALID") for name in ("open", "high", "low")})
        rows.append(value)
    return rows


def _write_gzip_csv(path: Path, fieldnames, rows):
    from io import StringIO
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader(); writer.writerows(rows); payload = stream.getvalue().encode("utf-8")
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            zipped.write(payload)


def _source_binding(source_parent: Path, source_manifest: dict, ticker: str):
    manifest_path = source_parent / "stage4a3_final_market_data_manifest.json"
    archive = source_parent / "final_market_data"
    if source_manifest.get("schema") != FROZEN_SOURCE_SCHEMA or source_manifest.get("immutable") is not True:
        raise ProspectiveIntegrityFailure("FROZEN_STAGE4A3_MARKET_MANIFEST_INVALID")
    items = {str(item.get("Ticker")): item for item in source_manifest.get("files", [])}
    if ticker not in items or "^NSEI" not in items:
        raise ProspectiveIntegrityFailure("FROZEN_STAGE4A3_MARKET_REQUIRED_SERIES_MISSING")
    required = []
    for symbol in (ticker, "^NSEI"):
        item = items[symbol]; path = archive / str(item["File"])
        if not path.is_file() or _sha256(path) != item.get("SHA256"):
            raise ProspectiveIntegrityFailure("FROZEN_STAGE4A3_MARKET_FILE_INVALID")
        required.append({"ticker": symbol, "file": str(Path("source_stage4a3/final_market_data") / path.name),
                         "sha256": item["SHA256"], "logical_hash": item["Logical Hash"]})
    return {"schema": source_manifest["schema"], "manifest_file": "source_stage4a3/stage4a3_final_market_data_manifest.json",
            "manifest_sha256": _sha256(manifest_path), "manifest_hash": canonical_hash(source_manifest),
            "overall_logical_hash": source_manifest["overall_logical_hash"], "required_files": required}


def _manifest(*, recommendation_id, envelope, checkpoint_type, target_date, provider, acquired_at,
              dates, stock_rows, nifty_rows, source_binding, stock_path, nifty_path):
    observations = [{"session_date": stock["session_date"], "observed_at_utc": acquired_at,
                     "stock_close": stock["close"], "stock_high": stock["high"], "stock_low": stock["low"],
                     "nifty_close": nifty["close"]} for stock, nifty in zip(stock_rows, nifty_rows)]
    logical = canonical_hash({"provider_identifier": provider, "ticker": envelope["ticker"],
                              "benchmark_ticker": "^NSEI", "observations": observations})
    value = {"archive_schema": ARCHIVE_SCHEMA, "archive_id": "", "creator_id": CREATOR_ID,
             "recommendation_id": recommendation_id,
             "envelope_binding": {"record_type": envelope["schema_version"], "record_id": envelope["envelope_id"], "record_hash": envelope["record_hash"]},
             "ticker": envelope["ticker"], "benchmark_ticker": "^NSEI", "checkpoint_type": checkpoint_type,
             "target_session_date": target_date, "provider_identifier": provider, "acquired_at_utc": acquired_at,
             "captured_at_utc": acquired_at, "frozen_adapter_id": FROZEN_ADAPTER_ID,
             "source_archive": source_binding, "verified_session_dates": dates,
             "files": [{"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size} for path in (stock_path, nifty_path)],
             "market_data_logical_hash": logical, "classification": MARKET_CLASSIFICATION,
             "recommendation_influence": "NONE", "trading_authority": False, "record_hash": "", "manifest_hash": ""}
    value["archive_id"] = "S6CPMKT_" + canonical_hash(without(value, "archive_id", "record_hash", "manifest_hash"))[:24]
    value["record_hash"] = canonical_hash(without(value, "record_hash", "manifest_hash"))
    value["manifest_hash"] = canonical_hash(without(value, "manifest_hash"))
    return value


def capture_checkpoint_market_archive(*, repo_root, activation_record, prospective_database,
                                      control_database, observation_database, recommendation_id,
                                      checkpoint_type, current_time_utc=None, acquisition_adapter=None,
                                      runtime_root=None, test_only_adapter=False):
    """Derive eligibility, call the frozen adapter, and create an immutable archive once."""
    repo = Path(repo_root).resolve()
    if checkpoint_type not in CHECKPOINT_TYPES:
        raise Stage6ProspectiveError("CHECKPOINT_TYPE_INVALID")
    if (current_time_utc is not None or acquisition_adapter is not None or runtime_root is not None) and not test_only_adapter:
        raise Stage6ProspectiveError("CHECKPOINT_MARKET_TEST_ADAPTER_PROHIBITED")
    cohort = verify_active_cohort(repo, activation_record)
    envelope, existing_checkpoints = _read_envelope(observation_database, recommendation_id, cohort)
    activation = verify_activation_record(activation_record)
    with Stage5DControlReader(control_database) as control:
        recommendation = control.get_recommendation(recommendation_id)
        origin_run = control.get_origin_run(recommendation["allocation_run_id"])
        database_id = control.database_id()
        now = parse_utc(current_time_utc) if current_time_utc is not None else datetime.now(timezone.utc)
        now_text = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        with ProspectiveStoreReader(prospective_database, activation) as prospective:
            origin = prospective.origin_session(origin_run, database_id)
            if checkpoint_type == "FINAL_EXIT":
                final_exit = derive_final_exit(control, recommendation_id, now_text)
                target_date = final_exit["final_exit_date"]
            else:
                due = prospective.due_checkpoints(origin, ())
                matches = [item for item in due if item["checkpoint_type"] == checkpoint_type]
                if len(matches) != 1 or matches[0]["status"] != "DUE":
                    raise Stage6ProspectiveError("CHECKPOINT_NOT_DUE_FROM_VERIFIED_SESSION_CHAIN")
                target_date = matches[0]["checkpoint_date"]
            dates = prospective.session_dates_through(origin, target_date)
    boundary = datetime.combine(datetime.fromisoformat(target_date).date(), COMPLETED_SESSION_TIME, IST).astimezone(timezone.utc)
    if now < boundary:
        raise Stage6ProspectiveError("CHECKPOINT_BEFORE_COMPLETED_SESSION_BOUNDARY")
    approved = (repo / RUNTIME_RELATIVE).resolve()
    root = validate_checkpoint_market_archive_root(runtime_root or approved, repo, allow_test_runtime=test_only_adapter)
    destination = _checkpoint_directory(root, recommendation_id, checkpoint_type)
    if destination.exists():
        try:
            resolved = MarketArchiveResolver(destination).resolve(
                ticker=envelope["ticker"], anchor_date=envelope["decision_date"], target_date=target_date,
                checkpoint_cutoff_utc=now_text, verified_session_dates=dates, require_creator_archive=True,
                recommendation_id=recommendation_id, checkpoint_type=checkpoint_type,
                envelope_binding={"record_type": envelope["schema_version"], "record_id": envelope["envelope_id"], "record_hash": envelope["record_hash"]})
        except Exception as exc:
            raise ProspectiveConflict("CHECKPOINT_MARKET_ARCHIVE_CONFLICT") from exc
        return {"status": "IDEMPOTENT_SUCCESS", "archive_directory": str(destination), "market_manifest": resolved}
    if checkpoint_type in existing_checkpoints:
        raise ProspectiveConflict("CHECKPOINT_ALREADY_PERSISTED_WITHOUT_VERIFIED_MARKET_ARCHIVE")
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / ("." + destination.parent.name + "-" + destination.name + "-" + uuid.uuid4().hex + ".tmp")
    temporary.mkdir(parents=False, exist_ok=False)
    try:
        source_parent = temporary / "source_stage4a3"; source_parent.mkdir()
        stage4a3_root = repo / "Stage 4A.3"
        adapter = acquisition_adapter if acquisition_adapter is not None else _production_acquire
        frames, source_manifest = adapter(repo, stage4a3_root, target_date, source_parent, now_text)
        if not test_only_adapter and source_manifest.get("provider") != FROZEN_PROVIDER:
            raise ProspectiveIntegrityFailure("NEW_MARKET_PROVIDER_PROHIBITED")
        if source_manifest.get("as_of_date") != target_date:
            raise ProspectiveIntegrityFailure("FROZEN_STAGE4A3_MARKET_TARGET_INVALID")
        provider = str(source_manifest.get("provider") or "")
        if not provider or envelope["ticker"] not in frames or "^NSEI" not in frames:
            raise ProspectiveIntegrityFailure("FROZEN_STAGE4A3_MARKET_REQUIRED_SERIES_MISSING")
        stock_rows = _frame_rows(frames[envelope["ticker"]], envelope["ticker"], dates, now_text)
        nifty_rows = _frame_rows(frames["^NSEI"], "^NSEI", dates, now_text, benchmark=True)
        stock_path = temporary / "stock_ohlc.csv.gz"; nifty_path = temporary / "nifty_close.csv.gz"
        _write_gzip_csv(stock_path, ("ticker", "session_date", "observed_at_utc", "open", "high", "low", "close"), stock_rows)
        _write_gzip_csv(nifty_path, ("ticker", "session_date", "observed_at_utc", "close"), nifty_rows)
        source = _source_binding(source_parent, source_manifest, envelope["ticker"])
        document = _manifest(recommendation_id=recommendation_id, envelope=envelope, checkpoint_type=checkpoint_type,
                             target_date=target_date, provider=provider, acquired_at=now_text, dates=dates,
                             stock_rows=stock_rows, nifty_rows=nifty_rows, source_binding=source,
                             stock_path=stock_path, nifty_path=nifty_path)
        (temporary / "market_archive_manifest.json").write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        if destination.exists():
            raise ProspectiveConflict("CHECKPOINT_MARKET_ARCHIVE_CONFLICT")
        destination.parent.mkdir(parents=True, exist_ok=True); temporary.replace(destination)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    resolved = MarketArchiveResolver(destination).resolve(
        ticker=envelope["ticker"], anchor_date=envelope["decision_date"], target_date=target_date,
        checkpoint_cutoff_utc=now_text, verified_session_dates=dates, require_creator_archive=True,
        recommendation_id=recommendation_id, checkpoint_type=checkpoint_type,
        envelope_binding={"record_type": envelope["schema_version"], "record_id": envelope["envelope_id"], "record_hash": envelope["record_hash"]})
    return {"status": "CREATED", "archive_directory": str(destination), "market_manifest": resolved}
