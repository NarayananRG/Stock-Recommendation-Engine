"""Research-only model lifecycle, dataset freeze, evaluation, approval, and rollback."""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from common import canonical_bytes, parse_date, parse_time, record, sha256

STATES = {"INCUMBENT", "CHALLENGER", "APPROVED", "REJECTED", "RETIRED", "ROLLED_BACK"}
TRANSITIONS = {("CHALLENGER", "APPROVED"), ("CHALLENGER", "REJECTED"), ("APPROVED", "INCUMBENT"), ("INCUMBENT", "RETIRED"), ("INCUMBENT", "ROLLED_BACK")}


def model_record(**values) -> dict:
    required = {"model_id", "model_version", "model_state", "created_at", "training_cutoff", "training_dataset_id", "training_dataset_hash", "feature_set_id", "feature_set_hash", "algorithm", "algorithm_configuration_hash", "preprocessing_identity", "source_code_commit", "source_code_manifest_hash"}
    if required - values.keys() or values["model_state"] not in STATES:
        raise ValueError("incomplete or invalid model record")
    return record("RESEARCH_MODEL_VERSION_V1", {**values, "authority_scope": "RESEARCH_ONLY", "trading_authority": False})


class ResearchModelRegistry:
    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path))
        self.db.execute("CREATE TABLE IF NOT EXISTS models(model_id TEXT PRIMARY KEY, payload BLOB NOT NULL, state TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY, model_id TEXT NOT NULL, payload BLOB NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS recommendation_links(link_id TEXT PRIMARY KEY, model_id TEXT NOT NULL, recommendation_id TEXT NOT NULL)")
        for table in ("models", "events", "recommendation_links"):
            self.db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'append-only'); END")
            self.db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'append-only'); END")
        self.db.commit()

    def add_model(self, model: dict) -> str:
        payload = canonical_bytes(model)
        existing = self.db.execute("SELECT payload FROM models WHERE model_id=?", (model["model_id"],)).fetchone()
        if existing:
            if existing[0] == payload:
                return "IDEMPOTENT_SUCCESS"
            raise ValueError("MODEL_ID_CONFLICT")
        self.db.execute("INSERT INTO models VALUES(?,?,?)", (model["model_id"], payload, model["model_state"]))
        self.db.commit(); return "CREATED"

    def get(self, model_id: str) -> dict:
        row = self.db.execute("SELECT payload FROM models WHERE model_id=?", (model_id,)).fetchone()
        if not row:
            raise ValueError("unknown model")
        return json.loads(row[0])

    def link_recommendation(self, model_id: str, recommendation_id: str) -> str:
        link = record("MODEL_RECOMMENDATION_LINK_V1", {"model_id": model_id, "recommendation_id": recommendation_id})
        self.db.execute("INSERT OR IGNORE INTO recommendation_links VALUES(?,?,?)", (link["record_id"], model_id, recommendation_id)); self.db.commit()
        return link["record_id"]

    def transition(self, model_id: str, from_state: str, to_state: str, evidence: dict | None = None) -> dict:
        model = self.get(model_id)
        events = [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM events WHERE model_id=? ORDER BY rowid", (model_id,))]
        current = events[-1]["to_state"] if events else model["model_state"]
        if current != from_state or (from_state, to_state) not in TRANSITIONS:
            raise ValueError("INVALID_MODEL_STATE_TRANSITION")
        if to_state == "APPROVED" and (not evidence or evidence.get("schema") != "MODEL_PROMOTION_APPROVAL_V1"):
            raise ValueError("approval artifact required")
        if to_state == "INCUMBENT" and (not evidence or evidence.get("active_system_apply_status") != "NOT_EXECUTED"):
            raise ValueError("research activation must remain not executed")
        event = record("MODEL_STATE_EVENT_V1", {"model_id": model_id, "from_state": from_state, "to_state": to_state, "evidence_hash": sha256(evidence) if evidence else None, "active_system_apply_status": "NOT_EXECUTED"})
        self.db.execute("INSERT INTO events VALUES(?,?,?)", (event["record_id"], model_id, canonical_bytes(event))); self.db.commit()
        return event

    def rollback(self, failed_model_id: str, earlier_approved_model_id: str, reason: str) -> dict:
        self.get(failed_model_id); self.get(earlier_approved_model_id)
        event = record("MODEL_ROLLBACK_EVENT_V1", {"failed_model_id": failed_model_id, "rollback_model_id": earlier_approved_model_id, "reason": reason, "history_preserved": True, "recommendation_provenance_preserved": True, "active_system_apply_status": "NOT_EXECUTED"})
        self.db.execute("INSERT INTO events VALUES(?,?,?)", (event["record_id"], failed_model_id, canonical_bytes(event))); self.db.commit()
        return event

    def counts(self) -> dict:
        return {name: self.db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in ("models", "events", "recommendation_links")}


def retraining_eligibility(stats: dict, policy: dict) -> dict:
    if policy.get("status") != "CONFIGURED_TEST_FIXTURE":
        return {"status": "NOT_CONFIGURED", "eligible": False, "failed_gates": ["POLICY_NOT_APPROVED"]}
    checks = {
        "minimum_elapsed_days": stats.get("elapsed_days", 0),
        "minimum_resolved": stats.get("resolved", 0),
        "minimum_positive": stats.get("positive", 0),
        "minimum_negative": stats.get("negative", 0),
        "minimum_benchmark_comparable": stats.get("benchmark_comparable", 0),
        "minimum_mature": stats.get("mature", 0),
        "minimum_sector_coverage": stats.get("sector_coverage", 0),
        "minimum_regime_coverage": stats.get("regime_coverage", 0),
        "minimum_adverse_cases": stats.get("adverse_cases", 0),
    }
    failed = [key for key, actual in checks.items() if actual < policy.get(key, 0)]
    return {"status": "ELIGIBLE_FOR_OFFLINE_RESEARCH" if not failed else "INSUFFICIENT_EVIDENCE", "eligible": not failed, "failed_gates": failed}


def freeze_training_dataset(rows: list[dict], cutoff: str, metadata: dict) -> dict:
    limit = parse_time(cutoff)
    included, excluded = [], []
    for row in rows:
        if row.get("split") != "TRAIN":
            excluded.append({"observation_id": row["observation_id"], "reason": "NON_TRAINING_SPLIT"}); continue
        if parse_time(row["observed_at"]) > limit:
            raise ValueError("POST_CUTOFF_OBSERVATION")
        included.append(row["observation_id"])
    return record("FROZEN_TRAINING_DATASET_V1", {
        "data_cutoff": cutoff, "included_observation_ids": sorted(included), "excluded_observations": sorted(excluded, key=lambda x: x["observation_id"]),
        "pit_universe_version": metadata["pit_universe_version"], "pit_universe_hash": metadata["pit_universe_hash"],
        "feature_definition_version": metadata["feature_definition_version"], "label_definition_version": metadata["label_definition_version"],
        "execution_policy_version": metadata["execution_policy_version"], "source_data_manifest_hash": metadata["source_data_manifest_hash"],
    })


def challenger_evaluation(incumbent: dict, challenger: dict, dataset: dict, metrics: dict, execution_policy_hash: str) -> dict:
    return record("CHALLENGER_EVALUATION_V1", {"incumbent_id": incumbent["model_id"], "challenger_id": challenger["model_id"], "untouched_dataset_hash": dataset["record_hash"], "execution_policy_hash": execution_policy_hash, "metrics": metrics, "promotion_state": "NO_PROMOTION", "active_system_apply_status": "NOT_EXECUTED"})


def approval_artifact(incumbent_id: str, challenger_id: str, evaluation: dict, approver: str, timestamp: str) -> dict:
    if evaluation.get("schema") != "CHALLENGER_EVALUATION_V1" or evaluation.get("challenger_id") != challenger_id:
        raise ValueError("invalid evaluation binding")
    parse_time(timestamp)
    return record("MODEL_PROMOTION_APPROVAL_V1", {"incumbent_id": incumbent_id, "challenger_id": challenger_id, "evaluation_hash": evaluation["record_hash"], "approval_identity": approver, "approved_at": timestamp, "requested_future_model_identity": challenger_id, "active_system_apply_status": "NOT_EXECUTED"})

