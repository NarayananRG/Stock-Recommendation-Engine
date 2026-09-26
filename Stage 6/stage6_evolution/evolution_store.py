"""Append-only Stage 6.2E directive/evolution store with Event V2 replay."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from stage6_candidates import CandidateStore
from stage6_events import EventStore
from stage6_ingestion.canonical import canonical_json, parse_utc
from stage6_materialization import MaterializationStore, validate_materialization
from stage6_materialization.event_mapper import build_expected_event

from .directive_builder import DIRECTIVE_SCHEMA_VERSION, build_directive
from .directive_validation import validate_directive
from .errors import EvolutionConflict, EvolutionIntegrityFailure, Stage6EvolutionError
from .evolution_mapper import (EVOLUTION_SCHEMA_VERSION, build_event_v2, build_evolution_record,
                               corroboration_status)
from .evolution_validation import validate_evolution
from .policy import (EVOLVER_VERSION, POLICY_ID, POLICY_VERSION, load_policy, validate_policy)


STORE_SCHEMA_VERSION = "STAGE6_2E_EVOLUTION_STORE_V1"
AUTHORITY = "SHADOW_ONLY"
BASELINE_2D_TAG = "stage6-2d-candidate-event-materialization-baseline"
BASELINE_2D_COMMIT = "117208546dd9b02c288ddd34d712761d73ea2b79"
BASELINE_2C_TAG = "stage6-2c-event-candidate-classification-baseline"
BASELINE_2C_COMMIT = "5f1955aa83b02dfbd2bac28916cf64d55e3853c1"
BASELINE_2A_TAG = "stage6-2a-event-intelligence-foundation-baseline"
BASELINE_2A_COMMIT = "850809db87b2d63380c532404ca8922bc8807a7b"
ARCHITECTURE_TAG = "stage6-decision-intelligence-architecture-baseline-v2"
ARCHITECTURE_COMMIT = "d5bc19c7c2341f56bcaa8c890e0d95979dca878b"
PRODUCTION_TAG = "stage5d5-live-paper-runner-baseline"
PRODUCTION_COMMIT = "74b2710f0e19bd403978da81e87f25a3059ace06"
EVENT_PREFIX = "stage6_2d_candidate:"


class EvolutionStore:
    def __init__(self, database: Path, candidate_store: CandidateStore,
                 materialization_store: MaterializationStore, event_store: EventStore):
        self.database = Path(database); self.database.parent.mkdir(parents=True, exist_ok=True)
        self.candidate_store = candidate_store; self.materialization_store = materialization_store
        self.event_store = event_store
        self.policy, self.policy_json, self.policy_hash = load_policy()
        new = not self.database.exists()
        self.connection = sqlite3.connect(self.database); self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        try:
            if new: self._initialize()
            self._verify_metadata(); self._verify_policy_snapshot()
        except Exception:
            self.connection.close(); raise

    def __enter__(self) -> "EvolutionStore": return self
    def __exit__(self, *_args: object) -> None: self.close()
    def close(self) -> None: self.connection.close()

    def _initialize(self) -> None:
        self.connection.executescript("""
        CREATE TABLE evolution_store_meta(
          singleton INTEGER PRIMARY KEY CHECK(singleton=1), store_schema_version TEXT NOT NULL,
          directive_schema_version TEXT NOT NULL, evolution_schema_version TEXT NOT NULL,
          evolver_version TEXT NOT NULL, baseline_2d_tag TEXT NOT NULL, baseline_2d_commit TEXT NOT NULL,
          baseline_2c_tag TEXT NOT NULL, baseline_2c_commit TEXT NOT NULL,
          baseline_2a_tag TEXT NOT NULL, baseline_2a_commit TEXT NOT NULL,
          architecture_tag TEXT NOT NULL, architecture_commit TEXT NOT NULL,
          production_tag TEXT NOT NULL, production_commit TEXT NOT NULL, authority TEXT NOT NULL);
        CREATE TABLE evolution_policies(
          policy_id TEXT PRIMARY KEY, policy_version INTEGER NOT NULL UNIQUE, policy_hash TEXT NOT NULL UNIQUE,
          evolver_version TEXT NOT NULL, canonical_json TEXT NOT NULL);
        CREATE TABLE evolution_directives(
          directive_id TEXT PRIMARY KEY, directive_type TEXT NOT NULL, target_event_id TEXT NOT NULL UNIQUE,
          base_event_hash TEXT NOT NULL, target_materialization_id TEXT NOT NULL,
          evolution_cutoff TEXT NOT NULL, record_hash TEXT NOT NULL UNIQUE, canonical_json TEXT NOT NULL);
        CREATE TABLE directive_dependencies(
          directive_id TEXT NOT NULL, dependency_record_type TEXT NOT NULL,
          dependency_record_id TEXT NOT NULL, dependency_record_hash TEXT NOT NULL,
          PRIMARY KEY(directive_id,dependency_record_type,dependency_record_id),
          FOREIGN KEY(directive_id) REFERENCES evolution_directives(directive_id));
        CREATE TABLE evolution_records(
          evolution_id TEXT PRIMARY KEY, directive_id TEXT NOT NULL UNIQUE, target_event_id TEXT NOT NULL UNIQUE,
          base_event_hash TEXT NOT NULL, result_event_hash TEXT NOT NULL,
          record_hash TEXT NOT NULL UNIQUE, canonical_json TEXT NOT NULL,
          FOREIGN KEY(directive_id) REFERENCES evolution_directives(directive_id));
        CREATE TABLE evolution_dependencies(
          evolution_id TEXT NOT NULL, dependency_record_type TEXT NOT NULL,
          dependency_record_id TEXT NOT NULL, dependency_record_hash TEXT NOT NULL,
          PRIMARY KEY(evolution_id,dependency_record_type,dependency_record_id),
          FOREIGN KEY(evolution_id) REFERENCES evolution_records(evolution_id));
        """)
        self.connection.execute("INSERT INTO evolution_store_meta VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            STORE_SCHEMA_VERSION, DIRECTIVE_SCHEMA_VERSION, EVOLUTION_SCHEMA_VERSION, EVOLVER_VERSION,
            BASELINE_2D_TAG, BASELINE_2D_COMMIT, BASELINE_2C_TAG, BASELINE_2C_COMMIT,
            BASELINE_2A_TAG, BASELINE_2A_COMMIT, ARCHITECTURE_TAG, ARCHITECTURE_COMMIT,
            PRODUCTION_TAG, PRODUCTION_COMMIT, AUTHORITY))
        self.connection.execute("INSERT INTO evolution_policies VALUES(?,?,?,?,?)", (
            POLICY_ID, POLICY_VERSION, self.policy_hash, EVOLVER_VERSION, self.policy_json))
        for table in ("evolution_store_meta", "evolution_policies", "evolution_directives",
                      "directive_dependencies", "evolution_records", "evolution_dependencies"):
            self.connection.executescript(f"""
            CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table}
            BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_TABLE_UPDATE'); END;
            CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_TABLE_DELETE'); END;
            """)
        self.connection.commit()

    def _verify_metadata(self) -> None:
        fields = ("store_schema_version","directive_schema_version","evolution_schema_version","evolver_version",
                  "baseline_2d_tag","baseline_2d_commit","baseline_2c_tag","baseline_2c_commit",
                  "baseline_2a_tag","baseline_2a_commit","architecture_tag","architecture_commit",
                  "production_tag","production_commit","authority")
        expected = (STORE_SCHEMA_VERSION,DIRECTIVE_SCHEMA_VERSION,EVOLUTION_SCHEMA_VERSION,EVOLVER_VERSION,
                    BASELINE_2D_TAG,BASELINE_2D_COMMIT,BASELINE_2C_TAG,BASELINE_2C_COMMIT,
                    BASELINE_2A_TAG,BASELINE_2A_COMMIT,ARCHITECTURE_TAG,ARCHITECTURE_COMMIT,
                    PRODUCTION_TAG,PRODUCTION_COMMIT,AUTHORITY)
        try:
            row=self.connection.execute("SELECT * FROM evolution_store_meta WHERE singleton=1").fetchone()
            if row is None or tuple(row[field] for field in fields)!=expected:
                raise EvolutionIntegrityFailure("EVOLUTION_STORE_METADATA_MISMATCH")
        except sqlite3.Error as exc: raise EvolutionIntegrityFailure("EVOLUTION_STORE_METADATA_INVALID") from exc

    def _verify_policy_snapshot(self) -> dict:
        row=self.connection.execute("SELECT * FROM evolution_policies WHERE policy_id=?",(POLICY_ID,)).fetchone()
        if row is None: raise EvolutionIntegrityFailure("EVOLUTION_POLICY_MISSING")
        try: stored=json.loads(row["canonical_json"])
        except (TypeError,json.JSONDecodeError) as exc: raise EvolutionIntegrityFailure("EVOLUTION_POLICY_JSON_INVALID") from exc
        validate_policy(stored)
        if (row["canonical_json"]!=canonical_json(stored) or row["policy_version"]!=POLICY_VERSION
                or row["policy_hash"]!=self.policy_hash or row["evolver_version"]!=EVOLVER_VERSION or stored!=self.policy):
            raise EvolutionIntegrityFailure("EVOLUTION_POLICY_SNAPSHOT_MISMATCH")
        return stored

    def _verify_upstream(self) -> None:
        try:
            if self.candidate_store.integrity_check().get("result")!="PASS": raise ValueError
        except Exception as exc: raise EvolutionIntegrityFailure("UPSTREAM_CANDIDATE_INTEGRITY_FAILED") from exc
        try:
            if self.event_store.integrity_check().get("result")!="PASS": raise ValueError
        except Exception as exc: raise EvolutionIntegrityFailure("UPSTREAM_EVENT_INTEGRITY_FAILED") from exc

    def _event_key(self, event_id: str) -> str:
        row=self.event_store.connection.execute("SELECT event_key_json FROM event_series WHERE event_id=?",(event_id,)).fetchone()
        if row is None: raise Stage6EvolutionError("TARGET_EVENT_NOT_FOUND")
        key=json.loads(row[0]).get("event_key")
        if not isinstance(key,str) or not key.startswith(EVENT_PREFIX):
            raise Stage6EvolutionError("TARGET_NOT_STAGE6_2D_EVENT")
        return key

    def _validate_v1_anchor(self, event_id: str) -> tuple[dict,dict,dict]:
        self.materialization_store._verify_metadata(); policy=self.materialization_store._verify_policy_snapshot()
        event_key=self._event_key(event_id); v1=self.event_store.get_event(event_id,1)
        if v1["event_version"]!=1 or v1["previous_event_version_hash"] is not None or v1["event_status"]!="CANDIDATE":
            raise EvolutionIntegrityFailure("EVOLUTION_V1_ANCHOR_INVALID")
        rows=self.materialization_store.connection.execute(
            "SELECT * FROM materialization_records WHERE event_id=? AND decision_status='MATERIALIZED'",(event_id,)).fetchall()
        if len(rows)!=1: raise EvolutionIntegrityFailure("EVOLUTION_MATERIALIZATION_ANCHOR_MISSING")
        materialization=json.loads(rows[0]["canonical_json"])
        if rows[0]["canonical_json"]!=canonical_json(materialization):
            raise EvolutionIntegrityFailure("EVOLUTION_ANCHOR_MATERIALIZATION_JSON_MISMATCH")
        candidate_row=self.candidate_store.connection.execute(
            "SELECT canonical_json FROM candidate_records WHERE candidate_id=?",(materialization["candidate_id"],)).fetchone()
        if candidate_row is None: raise EvolutionIntegrityFailure("EVOLUTION_ANCHOR_CANDIDATE_MISSING")
        candidate=json.loads(candidate_row[0]); validate_materialization(materialization,candidate)
        typed=(materialization["materialization_id"],materialization["candidate_id"],materialization["candidate_hash"],
               materialization["decision_status"],materialization["event_id"],materialization["event_version"],
               materialization["event_record_hash"],materialization["record_hash"])
        stored=tuple(rows[0][field] for field in ("materialization_id","candidate_id","candidate_hash",
                     "decision_status","event_id","event_version","event_record_hash","record_hash"))
        if typed!=stored: raise EvolutionIntegrityFailure("EVOLUTION_ANCHOR_MATERIALIZATION_TYPED_MISMATCH")
        if (materialization["event_id"],materialization["event_version"],materialization["event_record_hash"])!=(event_id,1,v1["record_hash"]):
            raise EvolutionIntegrityFailure("EVOLUTION_ANCHOR_EVENT_BINDING_MISMATCH")
        deps={row["dependency_record_type"]:row for row in self.materialization_store.connection.execute(
            "SELECT * FROM materialization_dependencies WHERE materialization_id=?",(materialization["materialization_id"],))}
        expected={kind:(identity,record_hash) for identity,record_hash,kind in self.materialization_store._expected_dependencies(materialization)}
        if set(deps)!=set(expected): raise EvolutionIntegrityFailure("EVOLUTION_ANCHOR_DEPENDENCY_COVERAGE_MISMATCH")
        for kind,binding in expected.items():
            if (deps[kind]["dependency_record_id"],deps[kind]["dependency_record_hash"])!=binding:
                raise EvolutionIntegrityFailure("EVOLUTION_ANCHOR_DEPENDENCY_MISMATCH")
        extraction,evidence=self.materialization_store._lineage(candidate)
        batch_row=self.candidate_store.connection.execute(
            "SELECT * FROM classification_batches WHERE classification_batch_id=?",(materialization["classification_batch_id"],)).fetchone()
        if batch_row is None: raise EvolutionIntegrityFailure("EVOLUTION_ANCHOR_BATCH_MISSING")
        expected_v1=build_expected_event(candidate,evidence,materialization["materialization_cutoff"],policy)
        if expected_v1!=v1 or event_key!=EVENT_PREFIX+candidate["candidate_id"]:
            raise EvolutionIntegrityFailure("EVOLUTION_V1_ANCHOR_REPLAY_MISMATCH")
        return v1,materialization,candidate

    def _evidence(self, ids: list[str], cutoff: str) -> list[dict]:
        evidence=self.event_store._load_evidence(ids,verify_store=False)
        for item in evidence:
            if item["record_kind"]!="EVIDENCE" or item["retrieval_status"]!="RETRIEVED":
                raise Stage6EvolutionError("EVOLUTION_RETRIEVED_EVIDENCE_REQUIRED")
            if parse_utc(item["retrieved_timestamp_utc"],"retrieved_timestamp_utc")>parse_utc(cutoff,"evolution_cutoff"):
                raise Stage6EvolutionError("EVOLUTION_FUTURE_EVIDENCE_PROHIBITED")
            if item["authority_level"] not in self.policy["trustworthy_authorities"]:
                raise Stage6EvolutionError("EVOLUTION_TRUSTWORTHY_EVIDENCE_REQUIRED")
        return evidence

    def _directive_dependencies(self,directive:dict,materialization:dict,evidence:list[dict])->list[tuple[str,str,str]]:
        return [(directive["target_event_id"]+":v1",directive["base_event_hash"],"BASE_STAGE6_EVENT"),
                (materialization["materialization_id"],materialization["record_hash"],"STAGE6_2D_MATERIALIZATION"),
                (POLICY_ID,self.policy_hash,"EVOLUTION_POLICY"),
                *[(item["evidence_id"],item["record_hash"],"EVIDENCE") for item in evidence]]

    def _evolution_dependencies(self,record:dict,directive:dict,materialization:dict,evidence:list[dict])->list[tuple[str,str,str]]:
        return [(directive["directive_id"],directive["record_hash"],"EVOLUTION_DIRECTIVE"),
                (record["target_event_id"]+":v1",record["base_event_hash"],"BASE_STAGE6_EVENT"),
                (materialization["materialization_id"],materialization["record_hash"],"STAGE6_2D_MATERIALIZATION"),
                (POLICY_ID,self.policy_hash,"EVOLUTION_POLICY"),
                (record["target_event_id"]+":v2",record["result_event_hash"],"RESULT_STAGE6_EVENT"),
                *[(item["evidence_id"],item["record_hash"],"EVIDENCE") for item in evidence]]

    def evolve_event(self, *, directive_type: str, target_event_id: str,
                     additional_evidence_ids: list[str], evolution_cutoff: str,
                     conflict_evidence_ids: list[str] | None=None,
                     conflict_description: str | None=None) -> dict:
        self._verify_metadata(); self._verify_policy_snapshot(); self._verify_upstream()
        v1,materialization,_candidate=self._validate_v1_anchor(target_event_id)
        directive=build_directive(directive_type=directive_type,target_event_id=target_event_id,
            base_event=v1,materialization=materialization,additional_evidence_ids=additional_evidence_ids,
            conflict_evidence_ids=conflict_evidence_ids or [],conflict_description=conflict_description,
            evolution_cutoff=evolution_cutoff,policy=self.policy,policy_hash=self.policy_hash)
        validate_directive(directive,v1,materialization)
        added=self._evidence(directive["additional_evidence_ids"],directive["evolution_cutoff"])
        all_evidence=self._evidence(sorted({*v1["source_evidence_ids"],*directive["additional_evidence_ids"]}),directive["evolution_cutoff"])
        event_key=self._event_key(target_event_id); expected_v2=build_event_v2(event_key=event_key,base_event=v1,directive=directive,evidence=all_evidence)
        existing_v2=self.event_store.connection.execute(
            "SELECT canonical_json FROM event_records WHERE event_id=? AND event_version=2",(target_event_id,)).fetchone()
        existing_directive=self.connection.execute("SELECT canonical_json FROM evolution_directives WHERE target_event_id=?",(target_event_id,)).fetchone()
        if existing_v2 is not None and json.loads(existing_v2[0])!=expected_v2:
            raise EvolutionConflict("TARGET_ALREADY_HAS_DIFFERENT_V2")
        if existing_directive is not None and json.loads(existing_directive[0])!=directive:
            raise EvolutionConflict("TARGET_ALREADY_HAS_DISTINCT_EVOLUTION")
        response=self.event_store.append_event(event_key=event_key,event_version=2,
            previous_event_version_hash=v1["record_hash"],source_evidence_ids=expected_v2["source_evidence_ids"],
            entity_resolution_version=v1["entity_resolution_version"],event_type=v1["event_type"],
            event_status=expected_v2["event_status"],direction=v1["direction"],severity=v1["severity"],
            materiality=v1["materiality"],confidence=v1["confidence"],entities=v1["entities"],
            sectors=v1["sectors"],geographies=v1["geographies"],commodities=v1["commodities"],
            currencies=v1["currencies"],corroboration_status=expected_v2["corroboration_status"],
            first_known_timestamp=v1["first_known_timestamp"],last_updated_timestamp=directive["evolution_cutoff"],
            event_horizon=v1["event_horizon"],transmission_channels=v1["transmission_channels"],
            causality_assessment=v1["causality_assessment"],evidence_conflicts=expected_v2["evidence_conflicts"])
        if response["status"] not in {"CREATED","IDEMPOTENT_SUCCESS"} or response["event"]!=expected_v2:
            raise EvolutionIntegrityFailure("EVENTSTORE_V2_RESULT_MISMATCH")
        record=build_evolution_record(directive=directive,base_event=v1,result_event=expected_v2,
                                      materialization=materialization,policy_hash=self.policy_hash)
        validate_evolution(record,directive,v1,materialization)
        if existing_directive is not None:
            stored=self.connection.execute("SELECT canonical_json FROM evolution_records WHERE directive_id=?",(directive["directive_id"],)).fetchone()
            if stored is not None and json.loads(stored[0])==record:
                return {"status":"IDEMPOTENT_SUCCESS","directive":directive,"evolution":record,"event":expected_v2}
            raise EvolutionConflict("INCOMPATIBLE_EVOLUTION_IDENTITY")
        try:
            with self.connection:
                self.connection.execute("INSERT INTO evolution_directives VALUES(?,?,?,?,?,?,?,?)",(
                    directive["directive_id"],directive["directive_type"],target_event_id,directive["base_event_hash"],
                    directive["target_materialization_id"],directive["evolution_cutoff"],directive["record_hash"],canonical_json(directive)))
                self.connection.executemany("INSERT INTO directive_dependencies VALUES(?,?,?,?)",[
                    (directive["directive_id"],kind,identity,record_hash)
                    for identity,record_hash,kind in self._directive_dependencies(directive,materialization,added)])
                self.connection.execute("INSERT INTO evolution_records VALUES(?,?,?,?,?,?,?)",(
                    record["evolution_id"],directive["directive_id"],target_event_id,record["base_event_hash"],
                    record["result_event_hash"],record["record_hash"],canonical_json(record)))
                self.connection.executemany("INSERT INTO evolution_dependencies VALUES(?,?,?,?)",[
                    (record["evolution_id"],kind,identity,record_hash)
                    for identity,record_hash,kind in self._evolution_dependencies(record,directive,materialization,added)])
        except sqlite3.IntegrityError as exc: raise EvolutionConflict("EVOLUTION_STORE_INSERT_CONFLICT") from exc
        return {"status":"CREATED","directive":directive,"evolution":record,"event":expected_v2}

    @staticmethod
    def _verify_dependencies(rows:list[sqlite3.Row],expected:list[tuple[str,str,str]],label:str)->None:
        actual={(row["dependency_record_type"],row["dependency_record_id"]):row["dependency_record_hash"] for row in rows}
        wanted={(kind,identity):record_hash for identity,record_hash,kind in expected}
        if actual!=wanted: raise EvolutionIntegrityFailure(label+"_DEPENDENCY_MISMATCH")

    def integrity_check(self) -> dict:
        try:
            self._verify_metadata()
            if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok": raise EvolutionIntegrityFailure("EVOLUTION_SQLITE_INTEGRITY_FAILURE")
            if self.connection.execute("PRAGMA foreign_key_check").fetchall(): raise EvolutionIntegrityFailure("EVOLUTION_FOREIGN_KEY_FAILURE")
            self._verify_policy_snapshot(); self._verify_upstream()
            for table in ("evolution_store_meta","evolution_policies","evolution_directives","directive_dependencies","evolution_records","evolution_dependencies"):
                triggers={row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,))}
                if triggers!={f"protect_{table}_update",f"protect_{table}_delete"}: raise EvolutionIntegrityFailure("EVOLUTION_APPEND_ONLY_TRIGGER_MISSING")
            directives={row["directive_id"]:row for row in self.connection.execute("SELECT * FROM evolution_directives")}
            records={row["directive_id"]:row for row in self.connection.execute("SELECT * FROM evolution_records")}
            if set(directives)!=set(records): raise EvolutionIntegrityFailure("EVOLUTION_DIRECTIVE_RECORD_COVERAGE_MISMATCH")
            evolved_events=set()
            for directive_id,row in directives.items():
                directive=json.loads(row["canonical_json"]); v1,materialization,_candidate=self._validate_v1_anchor(directive["target_event_id"])
                if row["canonical_json"]!=canonical_json(directive): raise EvolutionIntegrityFailure("DIRECTIVE_CANONICAL_JSON_MISMATCH")
                validate_directive(directive,v1,materialization)
                added=self._evidence(directive["additional_evidence_ids"],directive["evolution_cutoff"])
                all_evidence=self._evidence(sorted({*v1["source_evidence_ids"],*directive["additional_evidence_ids"]}),directive["evolution_cutoff"])
                expected_v2=build_event_v2(event_key=self._event_key(v1["event_id"]),base_event=v1,directive=directive,evidence=all_evidence)
                actual_v2=self.event_store.get_event(v1["event_id"],2)
                if actual_v2!=expected_v2: raise EvolutionIntegrityFailure("EVOLUTION_EVENT_V2_REPLAY_MISMATCH")
                record_row=records[directive_id]; record=json.loads(record_row["canonical_json"])
                if record_row["canonical_json"]!=canonical_json(record): raise EvolutionIntegrityFailure("EVOLUTION_CANONICAL_JSON_MISMATCH")
                validate_evolution(record,directive,v1,materialization)
                replay=build_evolution_record(directive=directive,base_event=v1,result_event=expected_v2,materialization=materialization,policy_hash=self.policy_hash)
                if record!=replay: raise EvolutionIntegrityFailure("EVOLUTION_REPLAY_MISMATCH")
                if (row["directive_type"],row["target_event_id"],row["base_event_hash"],row["target_materialization_id"],row["evolution_cutoff"],row["record_hash"])!=(directive["directive_type"],directive["target_event_id"],directive["base_event_hash"],directive["target_materialization_id"],directive["evolution_cutoff"],directive["record_hash"]): raise EvolutionIntegrityFailure("DIRECTIVE_TYPED_COLUMN_MISMATCH")
                if (record_row["evolution_id"],record_row["target_event_id"],record_row["base_event_hash"],record_row["result_event_hash"],record_row["record_hash"])!=(record["evolution_id"],record["target_event_id"],record["base_event_hash"],record["result_event_hash"],record["record_hash"]): raise EvolutionIntegrityFailure("EVOLUTION_TYPED_COLUMN_MISMATCH")
                self._verify_dependencies(list(self.connection.execute("SELECT * FROM directive_dependencies WHERE directive_id=?",(directive_id,))),self._directive_dependencies(directive,materialization,added),"DIRECTIVE")
                self._verify_dependencies(list(self.connection.execute("SELECT * FROM evolution_dependencies WHERE evolution_id=?",(record["evolution_id"],))),self._evolution_dependencies(record,directive,materialization,added),"EVOLUTION")
                evolved_events.add(v1["event_id"])
            owned_v2=set()
            for series in self.event_store.connection.execute("SELECT event_id,event_key_json FROM event_series"):
                key=json.loads(series["event_key_json"]).get("event_key")
                if isinstance(key,str) and key.startswith(EVENT_PREFIX):
                    versions=[row[0] for row in self.event_store.connection.execute("SELECT event_version FROM event_records WHERE event_id=? ORDER BY event_version",(series["event_id"],))]
                    if any(version>2 for version in versions): raise EvolutionIntegrityFailure("STAGE6_2E_EVENT_V3_PROHIBITED")
                    if 2 in versions: owned_v2.add(series["event_id"])
            if owned_v2!=evolved_events: raise EvolutionIntegrityFailure("ORPHAN_STAGE6_2E_EVENT_V2")
            return {"result":"PASS","evolutions":len(records),"event_v2":len(evolved_events),"policy_hash":self.policy_hash,"authority":AUTHORITY}
        except EvolutionIntegrityFailure: raise
        except Stage6EvolutionError as exc: raise EvolutionIntegrityFailure(f"EVOLUTION_SEMANTIC_INTEGRITY_FAILURE:{exc}") from exc
        except Exception as exc: raise EvolutionIntegrityFailure("FULL_EVOLUTION_INTEGRITY_FAILURE") from exc
