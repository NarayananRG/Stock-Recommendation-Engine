"""Read-only provenance resolvers used by the Stage 6.8C production path."""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import sqlite3
import sys
from contextlib import contextmanager
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from stage6_ingestion.canonical import canonical_hash, canonical_json, without
from .control_reader import parse_utc
from .errors import ProspectiveIntegrityFailure, Stage6ProspectiveError
from .policy import (
    ACTIVATION_SCHEMA, AUTHORITY, BASELINE, CONTRACT_VERSION, CONTROL_COMMIT, CONTROL_SCHEMA,
    EXPECTED_CONTRACT_HASH, EXPECTED_POLICY_HASH, EXPECTED_PROTOCOL_HASH,
    POLICY_ID, PROCESSOR, PROTOCOL_ID, SESSION_SCHEMA, STORE_SCHEMA, load_contract,
    load_policy, load_protocol,
)
from .session_calendar import verify_ordinary_session

MODEL_BUNDLE_HASH = "4631eb8a1d0b34212252df3b1aae180f64ec98ba5e7955a84729df0a471c62da"
PROTOCOL_VERSION = "STAGE4A3A_V1"
PROTOCOL_TAG = "stage4a3-prospective-shadow-protocol-baseline"
PROTOCOL_COMMIT = "3ff3c0283174589d43883ce75b1dfd87a33613ce"
PREDICTION_SEMANTICS = "SHADOW_ONLY_NO_TRADING_EFFECT"
MARKET_CLASSIFICATION = "OUTCOME_MEASUREMENT_ONLY_NOT_STAGE6_EVENT_EVIDENCE"
MARKET_ARCHIVE_SCHEMA = "STAGE6_8C_VERIFIED_MARKET_ARCHIVE_V1"
CHECKPOINT_MARKET_ARCHIVE_SCHEMA = "STAGE6_8C_CHECKPOINT_MARKET_ARCHIVE_V1"
CHECKPOINT_MARKET_ARCHIVE_CREATOR = "STAGE6_8C_CHECKPOINT_MARKET_ARCHIVE_CREATOR_V1"
FROZEN_MARKET_ADAPTER = "STAGE4A3_FINAL_MARKET_DATA_ACQUIRE_AND_ARCHIVE_V1"
IST = ZoneInfo("Asia/Kolkata")
COMPLETED_SESSION_TIME = time(15, 45)
SNAPSHOT_FILES = {
    "snapshot_metadata.json", "candidate_predictions.csv.gz", "feature_snapshot.csv.gz",
    "market_data_manifest.json", "candidate_input_manifest.json", "snapshot_manifest.json",
    "hash_chain.json",
}
PROSPECTIVE_TABLES = {
    "prospective_store_meta", "prospective_protocols", "prospective_policies",
    "prospective_contracts", "prospective_activations", "prospective_sessions",
    "prospective_control_recommendations", "prospective_pending_events",
    "prospective_shadow_submissions", "prospective_cases",
    "prospective_case_dependencies", "prospective_audits",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def _stage4a3_modules(root: Path):
    inserted = str(root) not in sys.path
    if inserted:
        sys.path.insert(0, str(root))
    try:
        from stage4a3.hash_chain import current_chain_hash
        from stage4a3.hashing import dataframe_content_hash, sha256_file
        from stage4a3.snapshot_contract import (
            PREDICTION_COLUMNS, snapshot_content_hash, validate_candidate_predictions,
        )
        yield current_chain_hash, dataframe_content_hash, sha256_file, PREDICTION_COLUMNS, snapshot_content_hash, validate_candidate_predictions
    finally:
        if inserted:
            sys.path.remove(str(root))


def _frame_row(frame, signal_id: str, ticker: str, code: str):
    if "Signal ID" not in frame or "Ticker" not in frame:
        raise ProspectiveIntegrityFailure(code + "_COLUMNS_INVALID")
    matches = frame.loc[frame["Signal ID"].astype(str).eq(signal_id)]
    if len(matches) == 0:
        raise Stage6ProspectiveError(code + "_ABSENT")
    if len(matches) != 1:
        raise ProspectiveIntegrityFailure(code + "_DUPLICATE")
    row = matches.iloc[0]
    if str(row["Ticker"]).upper() != ticker.upper():
        raise ProspectiveIntegrityFailure(code + "_TICKER_MISMATCH")
    return row


def _json_scalar(value):
    try:
        import pandas as pd
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        value = value.item()
    return value


class Stage4A3SnapshotResolver:
    """Resolve and verify the real immutable Stage 4A.3 snapshot files."""

    def __init__(self, stage4a3_root, prospective_root):
        self.stage4a3_root = Path(stage4a3_root).resolve()
        self.prospective_root = Path(prospective_root).resolve()
        if not (self.stage4a3_root / "stage4a3").is_dir() or not self.prospective_root.is_dir():
            raise Stage6ProspectiveError("STAGE4A3_VERIFIED_ROOT_REQUIRED")
        model = json.loads((self.stage4a3_root / "results/stage4a3_model_bundle_manifest.json").read_text(encoding="utf-8"))
        if model.get("FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH") != MODEL_BUNDLE_HASH or model.get("protocol_version") != PROTOCOL_VERSION:
            raise ProspectiveIntegrityFailure("STAGE4A3_FROZEN_MODEL_IDENTITY_INVALID")
        self.models = model["models"]

    def resolve(self, origin_run: dict, recommendation: dict, snapshot_directory=None):
        signal_date = str(recommendation["signal_date"])
        directory = (Path(snapshot_directory).resolve() if snapshot_directory else self.prospective_root / signal_date[:4] / signal_date)
        try:
            directory.relative_to(self.prospective_root)
        except ValueError as exc:
            raise Stage6ProspectiveError("STAGE4A3_SNAPSHOT_OUTSIDE_VERIFIED_ROOT") from exc
        if not directory.is_dir():
            raise Stage6ProspectiveError("STAGE4A3_SNAPSHOT_DIRECTORY_MISSING")
        if {p.name for p in directory.iterdir() if p.is_file()} < SNAPSHOT_FILES:
            raise Stage6ProspectiveError("STAGE4A3_SNAPSHOT_FILES_MISSING")
        metadata = json.loads((directory / "snapshot_metadata.json").read_text(encoding="utf-8"))
        market = json.loads((directory / "market_data_manifest.json").read_text(encoding="utf-8"))
        candidate_input = json.loads((directory / "candidate_input_manifest.json").read_text(encoding="utf-8"))
        manifest = json.loads((directory / "snapshot_manifest.json").read_text(encoding="utf-8"))
        chain = json.loads((directory / "hash_chain.json").read_text(encoding="utf-8"))
        with _stage4a3_modules(self.stage4a3_root) as frozen:
            current_chain_hash, dataframe_content_hash, sha256_file, columns, snapshot_content_hash, validate = frozen
            import pandas as pd
            inventory = manifest.get("files")
            expected_inventory = SNAPSHOT_FILES - {"snapshot_manifest.json", "hash_chain.json"}
            if not isinstance(inventory, list) or {x.get("file") for x in inventory} != expected_inventory:
                raise ProspectiveIntegrityFailure("STAGE4A3_SNAPSHOT_MANIFEST_INVENTORY_INVALID")
            for item in inventory:
                path = directory / str(item["file"])
                if not path.is_file() or item.get("bytes") != path.stat().st_size or item.get("sha256") != sha256_file(path):
                    raise ProspectiveIntegrityFailure("STAGE4A3_SNAPSHOT_FILE_HASH_INVALID")
            predictions = pd.read_csv(directory / "candidate_predictions.csv.gz")
            features = pd.read_csv(directory / "feature_snapshot.csv.gz")
            validate(predictions)
            if list(predictions.columns) != list(columns):
                raise ProspectiveIntegrityFailure("STAGE4A3_CANDIDATE_COLUMNS_INVALID")
            content_hash = snapshot_content_hash(metadata, predictions, features, market, candidate_input)
            expected_chain = current_chain_hash(str(chain.get("Previous Chain Hash", "")), signal_date, content_hash, PROTOCOL_COMMIT, MODEL_BUNDLE_HASH)
            feature_frame_hash = dataframe_content_hash(features)
        snapshot_id = str(metadata.get("Snapshot ID") or "")
        if snapshot_id != origin_run["stage4a3_snapshot_id"]:
            raise ProspectiveIntegrityFailure("STAGE4A3_SNAPSHOT_ID_MISMATCH")
        if metadata.get("Signal Date", signal_date) != signal_date or chain.get("Signal Date") != signal_date:
            raise ProspectiveIntegrityFailure("STAGE4A3_SIGNAL_DATE_MISMATCH")
        if manifest.get("Snapshot Content Hash") != content_hash or chain.get("Snapshot Content Hash") != content_hash:
            raise ProspectiveIntegrityFailure("STAGE4A3_REAL_SNAPSHOT_HASH_INVALID")
        if chain.get("Protocol Commit") != PROTOCOL_COMMIT or chain.get("Model Bundle Hash") != MODEL_BUNDLE_HASH or chain.get("Current Chain Hash") != expected_chain:
            raise ProspectiveIntegrityFailure("STAGE4A3_HASH_CHAIN_INVALID")
        if candidate_input.get("Full Input Logical Hash") != origin_run["candidate_input_hash"]:
            raise ProspectiveIntegrityFailure("STAGE4A3_CANDIDATE_INPUT_HASH_MISMATCH")
        if market.get("raw_data_logical_hash") != origin_run["market_data_hash"]:
            raise ProspectiveIntegrityFailure("STAGE4A3_MARKET_DATA_HASH_MISMATCH")
        if metadata.get("Candidate Input Manifest Hash") != canonical_hash(candidate_input):
            # Stage 4A.3 canonical JSON includes a terminal newline; its digest is supplied by the frozen helper.
            with _stage4a3_modules(self.stage4a3_root) as frozen:
                from stage4a3.hashing import canonical_json_hash
                if metadata.get("Candidate Input Manifest Hash") != canonical_json_hash(candidate_input):
                    raise ProspectiveIntegrityFailure("STAGE4A3_CANDIDATE_MANIFEST_BINDING_INVALID")
        signal_id = str(recommendation["signal_id"]); ticker = str(recommendation["ticker"]).upper()
        prediction = _frame_row(predictions, signal_id, ticker, "STAGE4A3_CANDIDATE")
        feature = _frame_row(features, signal_id, ticker, "STAGE4A3_FEATURE")
        if str(prediction["Signal Date"]) != signal_date or str(prediction["Snapshot ID"]) != snapshot_id:
            raise ProspectiveIntegrityFailure("STAGE4A3_CANDIDATE_LINEAGE_INVALID")
        if (str(prediction["Protocol Version"]) != PROTOCOL_VERSION or str(prediction["Protocol Tag"]) != PROTOCOL_TAG
                or str(prediction["Protocol Commit"]) != PROTOCOL_COMMIT or str(prediction["Model Bundle Hash"]) != MODEL_BUNDLE_HASH
                or str(prediction["Prediction Semantics"]) != PREDICTION_SEMANTICS):
            raise ProspectiveIntegrityFailure("STAGE4A3_CANDIDATE_FROZEN_IDENTITY_INVALID")
        declared_feature_hash = str(feature.get("Feature Row Hash") or "")
        if not declared_feature_hash or str(prediction["Feature Row Hash"]) != declared_feature_hash:
            raise ProspectiveIntegrityFailure("STAGE4A3_FEATURE_ROW_HASH_MISMATCH")
        prediction_row = {str(k): _json_scalar(v) for k, v in prediction.to_dict().items()}
        feature_row = {str(k): _json_scalar(v) for k, v in feature.to_dict().items()}
        primary = next(item for item in self.models if item["feature_set"] == "FS3_FULL_SIGNAL_STATE" and item["model_name"] == "PRIMARY_ONLY_T1_LOGIT_FULL")
        return {
            "snapshot_id": snapshot_id, "snapshot_content_hash": content_hash,
            "snapshot_chain_hash": chain["Current Chain Hash"], "signal_id": signal_id,
            "ticker": ticker, "candidate_row": prediction_row, "feature_row": feature_row,
            "feature_row_hash": declared_feature_hash,
            "feature_row_content_hash": canonical_hash(feature_row),
            "feature_snapshot_logical_hash": feature_frame_hash,
            "feature_set": primary["feature_set"], "feature_hash": primary["feature_hash"],
            "frozen_feature_hashes": sorted({item["feature_hash"] for item in self.models}),
            "model_bundle_hash": MODEL_BUNDLE_HASH, "protocol_version": PROTOCOL_VERSION,
            "protocol_tag": PROTOCOL_TAG, "protocol_commit": PROTOCOL_COMMIT,
            "candidate_input_hash": candidate_input["Full Input Logical Hash"],
            "candidate_input_manifest_hash": canonical_hash(candidate_input),
            "market_data_hash": market["raw_data_logical_hash"],
            "market_data_manifest_hash": canonical_hash(market),
            "market_data_manifest_id": "S4A3MD_" + canonical_hash(market)[:24],
            "snapshot_directory_verification": "PASS",
        }


class ProspectiveStoreReader:
    """Read-only, query-only verifier for the active Stage 6.8A store."""

    def __init__(self, database, activation: dict):
        self.database = Path(database).resolve(); self.activation = activation
        if not self.database.is_file():
            raise Stage6ProspectiveError("PROSPECTIVE_STORE_REQUIRED")
        self.connection = sqlite3.connect(f"file:{self.database.as_posix()}?mode=ro", uri=True)
        self.connection.row_factory = sqlite3.Row; self.connection.execute("PRAGMA query_only=ON")
        self.verify()

    def __enter__(self): return self
    def __exit__(self, *_): self.close()
    def close(self): self.connection.close()

    def verify(self):
        if self.connection.execute("PRAGMA query_only").fetchone()[0] != 1:
            raise ProspectiveIntegrityFailure("PROSPECTIVE_STORE_NOT_QUERY_ONLY")
        if self.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ProspectiveIntegrityFailure("PROSPECTIVE_STORE_INVALID")
        tables = {r[0] for r in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not PROSPECTIVE_TABLES <= tables:
            raise ProspectiveIntegrityFailure("PROSPECTIVE_STORE_SCHEMA_INCOMPLETE")
        protocol, protocol_json, protocol_hash = load_protocol(); policy, policy_json, policy_hash = load_policy(); contract, contract_json, contract_hash = load_contract()
        expected = {
            "prospective_protocols": (PROTOCOL_ID, protocol_hash, protocol_json),
            "prospective_policies": (POLICY_ID, policy_hash, policy_json),
            "prospective_contracts": (CONTRACT_VERSION, contract_hash, contract_json),
            "prospective_activations": (self.activation["activation_id"], self.activation["record_hash"], canonical_json(self.activation)),
        }
        meta = self.connection.execute("SELECT * FROM prospective_store_meta").fetchall()
        if len(meta) != 1 or tuple(meta[0]) != (1, STORE_SCHEMA, PROCESSOR, AUTHORITY, BASELINE, CONTROL_COMMIT):
            raise ProspectiveIntegrityFailure("PROSPECTIVE_STORE_METADATA_INVALID")
        for table, wanted in expected.items():
            rows = self.connection.execute(f"SELECT * FROM {table}").fetchall()
            if len(rows) != 1 or tuple(rows[0]) != wanted:
                raise ProspectiveIntegrityFailure("PROSPECTIVE_STORE_IDENTITY_INVALID:" + table)
        for table in PROSPECTIVE_TABLES:
            names = {r[0] for r in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,))}
            if names != {f"protect_{table}_update", f"protect_{table}_delete"}:
                raise ProspectiveIntegrityFailure("PROSPECTIVE_STORE_TRIGGER_INVALID:" + table)
        previous = 0; prior_date = None
        for row in self.connection.execute("SELECT * FROM prospective_sessions ORDER BY session_ordinal"):
            record = json.loads(row["canonical_json"])
            if canonical_json(record) != row["canonical_json"] or record.get("record_hash") != canonical_hash(without(record, "record_hash")):
                raise ProspectiveIntegrityFailure("PROSPECTIVE_SESSION_HASH_INVALID")
            typed = (record.get("enrollment_id"), record.get("stage5d5_run_id"), record.get("market_session_date"), record.get("session_ordinal_since_activation"), record.get("record_hash"))
            if typed != (row["enrollment_id"], row["run_id"], row["market_session_date"], row["session_ordinal"], row["record_hash"]):
                raise ProspectiveIntegrityFailure("PROSPECTIVE_SESSION_TYPED_BINDING_INVALID")
            if row["session_ordinal"] != previous + 1 or (prior_date and row["market_session_date"] <= prior_date):
                raise ProspectiveIntegrityFailure("PROSPECTIVE_SESSION_CHAIN_INVALID")
            try:
                verify_ordinary_session(row["market_session_date"])
            except Exception as exc:
                raise ProspectiveIntegrityFailure("PROSPECTIVE_SESSION_CALENDAR_INVALID") from exc
            if record.get("prospective_eligibility") != "PASS" or record.get("activation_binding", {}).get("record_id") != self.activation["activation_id"]:
                raise ProspectiveIntegrityFailure("PROSPECTIVE_SESSION_ELIGIBILITY_INVALID")
            previous = row["session_ordinal"]; prior_date = row["market_session_date"]
        return {"result": "PASS", "query_only": True, "sessions": previous}

    def origin_session(self, origin_run: dict, control_database_id: str | None = None):
        rows = self.connection.execute("SELECT canonical_json FROM prospective_sessions WHERE run_id=?", (origin_run["run_id"],)).fetchall()
        if len(rows) != 1:
            raise Stage6ProspectiveError("PROSPECTIVE_ORIGIN_SESSION_NOT_ENROLLED")
        record = json.loads(rows[0][0])
        if control_database_id is not None and record.get("control_database_id") != control_database_id:
            raise ProspectiveIntegrityFailure("PROSPECTIVE_CONTROL_DATABASE_IDENTITY_INVALID")
        binding = record.get("control_run_binding", {})
        if (binding.get("record_type"), binding.get("record_id"), binding.get("record_hash")) != (CONTROL_SCHEMA, origin_run["run_id"], origin_run["payload_sha256"]):
            raise ProspectiveIntegrityFailure("PROSPECTIVE_ORIGIN_RUN_BINDING_INVALID")
        for key in ("market_session_date", "run_started_utc", "run_completed_utc", "allocation_run_id", "stage4a3_snapshot_id", "market_data_hash", "candidate_input_hash"):
            if record.get(key) != origin_run.get(key):
                raise ProspectiveIntegrityFailure("PROSPECTIVE_ORIGIN_RUN_FIELD_MISMATCH:" + key)
        if record["market_session_date"] <= self.activation["activation_date_ist"] or parse_utc(record["run_started_utc"]) <= parse_utc(self.activation["activated_at_utc"]):
            raise Stage6ProspectiveError("PROSPECTIVE_ORIGIN_PRE_ACTIVATION")
        return record

    def case_at_creation(self, recommendation_id: str, creation_time: str):
        row = self.connection.execute("SELECT canonical_json FROM prospective_cases WHERE recommendation_id=?", (recommendation_id,)).fetchone()
        if row is None:
            return "NOT_AVAILABLE_AT_RECOMMENDATION_CREATION", None
        record = json.loads(row[0])
        enrolled = record.get("enrolled_at_utc")
        if enrolled is None or parse_utc(enrolled) > parse_utc(creation_time):
            return "NOT_AVAILABLE_AT_RECOMMENDATION_CREATION", None
        return "AVAILABLE_AT_RECOMMENDATION_CREATION", {"record_type": record["schema_version"], "record_id": record["case_id"], "record_hash": record["record_hash"]}

    def due_checkpoints(self, origin_session: dict, existing=()):
        existing = set(existing); result = []
        later = [json.loads(r[0]) for r in self.connection.execute("SELECT canonical_json FROM prospective_sessions WHERE session_ordinal>? ORDER BY session_ordinal", (origin_session["session_ordinal_since_activation"],))]
        for kind, ordinal in (("D+5", 5), ("D+20", 20), ("D+60", 60)):
            if kind in existing:
                continue
            if len(later) < ordinal:
                result.append({"checkpoint_type": kind, "trading_session_ordinal": ordinal, "checkpoint_date": None, "status": "NOT_DUE"})
            else:
                target = later[ordinal - 1]
                result.append({"checkpoint_type": kind, "trading_session_ordinal": ordinal, "checkpoint_date": target["market_session_date"], "session_binding": {"record_type": target["schema_version"], "record_id": target["enrollment_id"], "record_hash": target["record_hash"]}, "status": "DUE"})
        return result

    def session_dates_through(self, origin_session: dict, target_date: str):
        rows = self.connection.execute("SELECT market_session_date FROM prospective_sessions WHERE session_ordinal>=? AND market_session_date<=? ORDER BY session_ordinal", (origin_session["session_ordinal_since_activation"], target_date)).fetchall()
        dates = [r[0] for r in rows]
        if not dates or dates[0] != origin_session["market_session_date"] or dates[-1] != target_date:
            raise Stage6ProspectiveError("CHECKPOINT_SESSION_NOT_VERIFIED_ENROLLED_CONTROL")
        return dates


class MarketArchiveResolver:
    """Verify an immutable market archive produced from the frozen market-data path."""

    def __init__(self, archive_directory):
        self.directory = Path(archive_directory).resolve()
        self.manifest_path = self.directory / "market_archive_manifest.json"
        if not self.directory.is_dir() or not self.manifest_path.is_file():
            raise Stage6ProspectiveError("VERIFIED_MARKET_ARCHIVE_REQUIRED")

    @staticmethod
    def _rows(path):
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def _verified_source(self, manifest, stock, nifty):
        source = manifest.get("source_archive")
        if not isinstance(source, dict) or source.get("schema") != "STAGE4A3_FINAL_MARKET_DATA_V1":
            raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_SOURCE_PROVENANCE_INVALID")
        manifest_path = (self.directory / str(source.get("manifest_file", ""))).resolve()
        try:
            manifest_path.relative_to(self.directory)
        except ValueError as exc:
            raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_SOURCE_PATH_INVALID") from exc
        if not manifest_path.is_file() or source.get("manifest_sha256") != _sha256(manifest_path):
            raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_SOURCE_MANIFEST_HASH_INVALID")
        source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if canonical_hash(source_manifest) != source.get("manifest_hash") or source_manifest.get("schema") != source.get("schema"):
            raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_SOURCE_MANIFEST_INVALID")
        if (source_manifest.get("overall_logical_hash") != source.get("overall_logical_hash")
                or source_manifest.get("provider") != manifest.get("provider_identifier")
                or source_manifest.get("as_of_date") != manifest.get("target_session_date")
                or source_manifest.get("immutable") is not True):
            raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_SOURCE_IDENTITY_INVALID")
        required = source.get("required_files")
        if not isinstance(required, list) or {item.get("ticker") for item in required} != {manifest["ticker"], "^NSEI"}:
            raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_SOURCE_FILES_INVALID")
        source_rows = {}
        for item in required:
            path = (self.directory / str(item.get("file", ""))).resolve()
            try:
                path.relative_to(self.directory)
            except ValueError as exc:
                raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_SOURCE_PATH_INVALID") from exc
            if not path.is_file() or _sha256(path) != item.get("sha256"):
                raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_SOURCE_FILE_HASH_INVALID")
            rows = self._rows(path)
            source_rows[item["ticker"]] = {str(row.get("Date"))[:10]: row for row in rows}
        def same(left, right):
            try: return Decimal(str(left)) == Decimal(str(right))
            except Exception: return False
        for row in stock:
            source_row = source_rows[manifest["ticker"]].get(row["session_date"])
            if source_row is None or any(not same(row[name], source_row[name.title()]) for name in ("open", "high", "low", "close")):
                raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_SOURCE_STOCK_MISMATCH")
        for row in nifty:
            source_row = source_rows["^NSEI"].get(row["session_date"])
            if source_row is None or not same(row["close"], source_row["Close"]):
                raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_SOURCE_NIFTY_MISMATCH")

    def resolve(self, *, ticker, anchor_date, target_date, checkpoint_cutoff_utc, verified_session_dates,
                require_creator_archive=False, recommendation_id=None, checkpoint_type=None,
                envelope_binding=None):
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        stored_hash = manifest.get("manifest_hash")
        schema = manifest.get("archive_schema")
        if schema not in {MARKET_ARCHIVE_SCHEMA, CHECKPOINT_MARKET_ARCHIVE_SCHEMA} or stored_hash != canonical_hash(without(manifest, "manifest_hash")):
            raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_MANIFEST_INVALID")
        if require_creator_archive and schema != CHECKPOINT_MARKET_ARCHIVE_SCHEMA:
            raise ProspectiveIntegrityFailure("PRODUCTION_CHECKPOINT_MARKET_ARCHIVE_REQUIRED")
        if schema == CHECKPOINT_MARKET_ARCHIVE_SCHEMA:
            if (manifest.get("creator_id") != CHECKPOINT_MARKET_ARCHIVE_CREATOR
                    or manifest.get("frozen_adapter_id") != FROZEN_MARKET_ADAPTER
                    or manifest.get("record_hash") != canonical_hash(without(manifest, "record_hash", "manifest_hash"))):
                raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_CREATOR_IDENTITY_INVALID")
            if recommendation_id is not None and manifest.get("recommendation_id") != recommendation_id:
                raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_RECOMMENDATION_MISMATCH")
            if checkpoint_type is not None and manifest.get("checkpoint_type") != checkpoint_type:
                raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_CHECKPOINT_TYPE_MISMATCH")
            if envelope_binding is not None and manifest.get("envelope_binding") != envelope_binding:
                raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_ENVELOPE_BINDING_MISMATCH")
        if manifest.get("classification") != MARKET_CLASSIFICATION or manifest.get("ticker") != ticker or manifest.get("benchmark_ticker") != "^NSEI":
            raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_IDENTITY_INVALID")
        if manifest.get("target_session_date") != target_date or not manifest.get("provider_identifier"):
            raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_TARGET_INVALID")
        inventory = manifest.get("files")
        if not isinstance(inventory, list) or {x.get("file") for x in inventory} != {"stock_ohlc.csv.gz", "nifty_close.csv.gz"}:
            raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_FILES_INVALID")
        for item in inventory:
            path = self.directory / item["file"]
            if not path.is_file() or item.get("bytes") != path.stat().st_size or item.get("sha256") != _sha256(path):
                raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_FILE_HASH_INVALID")
        cutoff = parse_utc(checkpoint_cutoff_utc)
        boundary = datetime.combine(date.fromisoformat(target_date), COMPLETED_SESSION_TIME, IST).astimezone(timezone.utc)
        if cutoff < boundary or parse_utc(manifest["captured_at_utc"]) < boundary:
            raise Stage6ProspectiveError("CHECKPOINT_BEFORE_COMPLETED_SESSION_BOUNDARY")
        stock = self._rows(self.directory / "stock_ohlc.csv.gz"); nifty = self._rows(self.directory / "nifty_close.csv.gz")
        if any(r.get("ticker") != ticker for r in stock) or any(r.get("ticker") != "^NSEI" for r in nifty):
            raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_TICKER_MISMATCH")
        stock_by = {r["session_date"]: r for r in stock}; nifty_by = {r["session_date"]: r for r in nifty}
        wanted = [d for d in verified_session_dates if anchor_date <= d <= target_date]
        if schema == CHECKPOINT_MARKET_ARCHIVE_SCHEMA and manifest.get("verified_session_dates") != wanted:
            raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_VERIFIED_SESSION_SEQUENCE_INVALID")
        if not wanted or wanted[0] != anchor_date or wanted[-1] != target_date or set(stock_by) != set(wanted) or set(nifty_by) != set(wanted):
            raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_SESSION_ALIGNMENT_INVALID")
        observations = []
        for session in wanted:
            s = stock_by[session]; n = nifty_by[session]
            if parse_utc(s["observed_at_utc"]) > cutoff or parse_utc(n["observed_at_utc"]) > cutoff:
                raise Stage6ProspectiveError("FUTURE_MARKET_DATA_CROSSES_CHECKPOINT_CUTOFF")
            if session == target_date and (parse_utc(s["observed_at_utc"]) < boundary or parse_utc(n["observed_at_utc"]) < boundary):
                raise Stage6ProspectiveError("TARGET_MARKET_OBSERVATION_BEFORE_COMPLETED_SESSION")
            observations.append({"session_date": session, "observed_at_utc": max(s["observed_at_utc"], n["observed_at_utc"]), "stock_close": s["close"], "stock_high": s["high"], "stock_low": s["low"], "nifty_close": n["close"]})
        logical = canonical_hash({"provider_identifier": manifest["provider_identifier"], "ticker": ticker, "benchmark_ticker": "^NSEI", "observations": observations})
        if manifest.get("market_data_logical_hash") != logical:
            raise ProspectiveIntegrityFailure("MARKET_ARCHIVE_LOGICAL_HASH_INVALID")
        if schema == CHECKPOINT_MARKET_ARCHIVE_SCHEMA:
            self._verified_source(manifest, stock, nifty)
        return {"manifest_id": manifest["archive_id"], "manifest_hash": stored_hash, "archive_schema": schema,
                "classification": MARKET_CLASSIFICATION, "provider_identifier": manifest["provider_identifier"],
                "ticker": ticker, "benchmark_ticker": "^NSEI", "target_session_date": target_date,
                "checkpoint_type": manifest.get("checkpoint_type"), "recommendation_id": manifest.get("recommendation_id"),
                "completed_session_boundary_utc": boundary.isoformat().replace("+00:00", "Z"),
                "captured_at_utc": manifest["captured_at_utc"], "market_data_logical_hash": logical,
                "provenance_verification": "PASS", "observations": observations}


class Stage6ContextReader:
    """Resolve exact canonical records from an explicitly supplied Stage 6 store."""

    ALLOWED_TABLES = {"trade_thesis_records", "trade_thesis_version_records", "recursive_thesis_versions", "thesis_review_assessment_records", "recursive_review_assessments"}

    def __init__(self, database):
        self.database = Path(database).resolve()
        if not self.database.is_file():
            raise Stage6ProspectiveError("STAGE6_CONTEXT_STORE_REQUIRED")
        self.connection = sqlite3.connect(f"file:{self.database.as_posix()}?mode=ro", uri=True); self.connection.row_factory = sqlite3.Row; self.connection.execute("PRAGMA query_only=ON")
        if self.connection.execute("PRAGMA query_only").fetchone()[0] != 1 or self.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ProspectiveIntegrityFailure("STAGE6_CONTEXT_STORE_INVALID")

    def close(self): self.connection.close()
    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    def resolve(self, binding: dict, *, cutoff_utc: str, recommendation_id: str, signal_id: str, ticker: str):
        required = {"table", "id_column", "record_type", "record_id", "record_hash"}
        if set(binding) != required or binding["table"] not in self.ALLOWED_TABLES:
            raise Stage6ProspectiveError("STAGE6_CONTEXT_BINDING_INVALID")
        columns = {r[1] for r in self.connection.execute(f"PRAGMA table_info({binding['table']})")}
        if binding["id_column"] not in columns or not {"canonical_json", "record_hash"} <= columns:
            raise ProspectiveIntegrityFailure("STAGE6_CONTEXT_SCHEMA_INVALID")
        rows = self.connection.execute(f"SELECT canonical_json,record_hash FROM {binding['table']} WHERE {binding['id_column']}=?", (binding["record_id"],)).fetchall()
        if len(rows) != 1 or rows[0]["record_hash"] != binding["record_hash"]:
            raise ProspectiveIntegrityFailure("STAGE6_CONTEXT_RECORD_BINDING_INVALID")
        value = json.loads(rows[0]["canonical_json"])
        if canonical_json(value) != rows[0]["canonical_json"] or value.get("record_hash") != canonical_hash(without(value, "record_hash")):
            raise ProspectiveIntegrityFailure("STAGE6_CONTEXT_RECORD_HASH_INVALID")
        recorded = value.get("recorded_at_utc") or value.get("decision_cutoff") or value.get("review_cutoff")
        if not recorded or parse_utc(recorded) > parse_utc(cutoff_utc):
            raise Stage6ProspectiveError("STAGE6_CONTEXT_AFTER_CUTOFF")
        for key, expected in (("recommendation_id", recommendation_id), ("signal_id", signal_id), ("ticker", ticker)):
            present = value.get(key)
            if present is not None and str(present).upper() != str(expected).upper():
                raise ProspectiveIntegrityFailure("STAGE6_CONTEXT_SUBJECT_MISMATCH:" + key)
        return value, {"record_type": binding["record_type"], "record_id": binding["record_id"], "record_hash": binding["record_hash"]}
