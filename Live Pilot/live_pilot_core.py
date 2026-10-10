"""Live Pilot V1 infrastructure.

This module wraps the frozen production application's decision output.
It does NOT calculate stock scores, alter rankings, place broker orders,
or grant Fundamental V2 production authority.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import sqlite3
from typing import Any, Iterable


SCHEMA_VERSION = "LIVE_PILOT_SCHEMA_V1"
REQUIRED_REPRO_FIELDS = (
    "action",
    "symbol",
    "rank",
    "quantity",
    "expected_return",
    "probability",
    "risk",
    "reason_codes",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def sha256_json(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _bool(value: Any) -> bool:
    return bool(value)


@dataclass(frozen=True)
class ReadinessResult:
    live_ready: bool
    hard_failures: tuple[str, ...]
    checks: dict[str, bool]
    evidence: dict[str, Any]
    checked_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["hard_failures"] = list(self.hard_failures)
        return result


def evaluate_readiness(
    *,
    expected_production_version: str,
    actual_production_version: str,
    official_price_data_ready: bool,
    market_index_data_ready: bool,
    sector_data_ready: bool,
    data_freshness_ready: bool,
    pit_integrity_ready: bool,
    database_integrity_ready: bool,
    backup_ready: bool,
    duplicate_run_protection_ready: bool,
    capital_sizing_ready: bool,
    yfinance_used: bool,
    evidence: dict[str, Any] | None = None,
) -> ReadinessResult:
    checks = {
        "official_price_data_ready": _bool(official_price_data_ready),
        "market_index_data_ready": _bool(market_index_data_ready),
        "sector_data_ready": _bool(sector_data_ready),
        "data_freshness_ready": _bool(data_freshness_ready),
        "pit_integrity_ready": _bool(pit_integrity_ready),
        "database_integrity_ready": _bool(database_integrity_ready),
        "backup_ready": _bool(backup_ready),
        "duplicate_run_protection_ready": _bool(duplicate_run_protection_ready),
        "capital_sizing_ready": _bool(capital_sizing_ready),
        "yfinance_used_false": not _bool(yfinance_used),
        "production_version_match": actual_production_version == expected_production_version,
    }
    failures = tuple(sorted(key for key, ok in checks.items() if not ok))
    return ReadinessResult(
        live_ready=not failures,
        hard_failures=failures,
        checks=checks,
        evidence=dict(evidence or {}),
        checked_at_utc=_utc_now(),
    )


def build_decision_envelope(
    *,
    pilot_id: str,
    production_version: str,
    capital_inr: float,
    holding_sessions: int,
    readiness: ReadinessResult,
    production_decision: dict[str, Any],
    production_ranking: list[dict[str, Any]] | None = None,
    source_provenance: dict[str, Any] | None = None,
    fundamental_v2_shadow: dict[str, Any] | None = None,
    run_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an immutable, hash-addressed record of what the app knew.

    The caller supplies the existing production result. Nothing here modifies
    action/rank/quantity/score.
    """
    decision_copy = json.loads(_canonical_json(production_decision))
    ranking_copy = json.loads(_canonical_json(production_ranking or []))
    shadow_copy = json.loads(_canonical_json(fundamental_v2_shadow or {}))

    envelope = {
        "schema_version": SCHEMA_VERSION,
        "pilot_id": pilot_id,
        "captured_at_utc": _utc_now(),
        "mode": "LIVE_PILOT",
        "production_version": production_version,
        "capital_inr": float(capital_inr),
        "holding_sessions": int(holding_sessions),
        "readiness": readiness.to_dict(),
        "production_decision": decision_copy,
        "production_ranking": ranking_copy,
        "source_provenance": dict(source_provenance or {}),
        "fundamental_v2_shadow": {
            **shadow_copy,
            "authority": "SHADOW_ONLY",
            "production_action_changed": False,
            "production_rank_changed": False,
        },
        "run_context": dict(run_context or {}),
        "broker_order_placed": False,
        "production_logic_changed": False,
    }
    envelope["decision_hash_sha256"] = sha256_json(
        {k: v for k, v in envelope.items() if k != "decision_hash_sha256"}
    )
    return envelope


def normalized_reproducibility_view(envelope: dict[str, Any]) -> dict[str, Any]:
    d = dict(envelope.get("production_decision") or {})
    return {field: d.get(field) for field in REQUIRED_REPRO_FIELDS}


def compare_reproducibility(
    first: dict[str, Any],
    second: dict[str, Any],
) -> dict[str, Any]:
    a = normalized_reproducibility_view(first)
    b = normalized_reproducibility_view(second)
    differences = {
        key: {"run_a": a.get(key), "run_b": b.get(key)}
        for key in REQUIRED_REPRO_FIELDS
        if a.get(key) != b.get(key)
    }
    return {
        "schema_version": "LIVE_PILOT_REPRODUCIBILITY_V1",
        "exact_match": not differences,
        "differences": differences,
        "run_a_decision_hash": first.get("decision_hash_sha256"),
        "run_b_decision_hash": second.get("decision_hash_sha256"),
        "checked_at_utc": _utc_now(),
    }


class LivePilotStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS live_pilot_snapshots (
                    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pilot_id TEXT NOT NULL,
                    captured_at_utc TEXT NOT NULL,
                    decision_hash_sha256 TEXT NOT NULL UNIQUE,
                    envelope_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS live_pilot_execution (
                    execution_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pilot_id TEXT NOT NULL,
                    decision_hash_sha256 TEXT NOT NULL,
                    recorded_at_utc TEXT NOT NULL,
                    execution_json TEXT NOT NULL,
                    FOREIGN KEY(decision_hash_sha256)
                      REFERENCES live_pilot_snapshots(decision_hash_sha256)
                );

                CREATE TABLE IF NOT EXISTS live_pilot_monitoring (
                    monitoring_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pilot_id TEXT NOT NULL,
                    decision_hash_sha256 TEXT NOT NULL,
                    recorded_at_utc TEXT NOT NULL,
                    monitoring_json TEXT NOT NULL,
                    FOREIGN KEY(decision_hash_sha256)
                      REFERENCES live_pilot_snapshots(decision_hash_sha256)
                );

                CREATE TABLE IF NOT EXISTS live_pilot_reproducibility (
                    reproducibility_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pilot_id TEXT NOT NULL,
                    recorded_at_utc TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );
                """
            )

    def save_snapshot(self, envelope: dict[str, Any]) -> str:
        decision_hash = str(envelope["decision_hash_sha256"])
        payload = _canonical_json(envelope)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT envelope_json FROM live_pilot_snapshots WHERE decision_hash_sha256=?",
                (decision_hash,),
            ).fetchone()
            if existing:
                if existing[0] != payload:
                    raise RuntimeError("IMMUTABLE_SNAPSHOT_HASH_COLLISION")
                return decision_hash
            conn.execute(
                """
                INSERT INTO live_pilot_snapshots
                (pilot_id,captured_at_utc,decision_hash_sha256,envelope_json)
                VALUES (?,?,?,?)
                """,
                (
                    str(envelope["pilot_id"]),
                    str(envelope["captured_at_utc"]),
                    decision_hash,
                    payload,
                ),
            )
        return decision_hash

    def load_snapshot(self, decision_hash: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT envelope_json FROM live_pilot_snapshots WHERE decision_hash_sha256=?",
                (decision_hash,),
            ).fetchone()
        if not row:
            raise KeyError(decision_hash)
        return json.loads(row[0])

    def record_execution(
        self,
        *,
        pilot_id: str,
        decision_hash: str,
        execution: dict[str, Any],
    ) -> None:
        prohibited = {"broker_order_id_auto", "automatic_order_placed"}
        if prohibited.intersection(execution):
            raise ValueError("BROKER_AUTOMATION_NOT_ALLOWED_IN_LIVE_PILOT_V1")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO live_pilot_execution
                (pilot_id,decision_hash_sha256,recorded_at_utc,execution_json)
                VALUES (?,?,?,?)
                """,
                (pilot_id, decision_hash, _utc_now(), _canonical_json(execution)),
            )

    def record_monitoring(
        self,
        *,
        pilot_id: str,
        decision_hash: str,
        monitoring: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO live_pilot_monitoring
                (pilot_id,decision_hash_sha256,recorded_at_utc,monitoring_json)
                VALUES (?,?,?,?)
                """,
                (pilot_id, decision_hash, _utc_now(), _canonical_json(monitoring)),
            )

    def record_reproducibility(
        self,
        *,
        pilot_id: str,
        result: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO live_pilot_reproducibility
                (pilot_id,recorded_at_utc,result_json)
                VALUES (?,?,?)
                """,
                (pilot_id, _utc_now(), _canonical_json(result)),
            )

    def integrity_check(self) -> str:
        with self._connect() as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        return str(row[0] if row else "unknown")
