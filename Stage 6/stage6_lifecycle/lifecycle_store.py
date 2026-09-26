"""Append-only Stage 6.2F lifecycle audit store and Event V3 coordinator."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from stage6_evolution import EvolutionStore
from stage6_evolution.directive_validation import validate_directive as validate_evolution_directive
from stage6_evolution.evolution_mapper import build_event_v2, build_evolution_record
from stage6_evolution.evolution_validation import validate_evolution
from stage6_ingestion.canonical import canonical_json, parse_utc

from .directive_builder import DIRECTIVE_SCHEMA_VERSION, build_directive
from .directive_validation import validate_directive
from .errors import LifecycleConflict, LifecycleIntegrityFailure, Stage6LifecycleError
from .lifecycle_mapper import (LIFECYCLE_SCHEMA_VERSION, active_evidence_ids, build_event_v3,
                               build_lifecycle_record)
from .lifecycle_validation import validate_lifecycle
from .policy import (AUTHORITY, POLICY_ID, POLICY_VERSION, PROCESSOR_VERSION, TRUSTWORTHY,
                     load_policy, validate_policy)


STORE_SCHEMA_VERSION = "STAGE6_2F_LIFECYCLE_STORE_V1"
BASELINE_2E_TAG = "stage6-2e-controlled-event-evolution-baseline"
BASELINE_2E_COMMIT = "4fff221bbbf4125a7e32ac6ade1dd5269c871c5b"
BASELINE_2D_TAG = "stage6-2d-candidate-event-materialization-baseline"
BASELINE_2D_COMMIT = "117208546dd9b02c288ddd34d712761d73ea2b79"
ARCHITECTURE_TAG = "stage6-decision-intelligence-architecture-baseline-v2"
ARCHITECTURE_COMMIT = "d5bc19c7c2341f56bcaa8c890e0d95979dca878b"
PRODUCTION_TAG = "stage5d5-live-paper-runner-baseline"
PRODUCTION_COMMIT = "74b2710f0e19bd403978da81e87f25a3059ace06"
EVENT_PREFIX = "stage6_2d_candidate:"


class LifecycleStore:
    def __init__(self, database: Path, evolution_store: EvolutionStore):
        self.database = Path(database); self.database.parent.mkdir(parents=True, exist_ok=True)
        self.evolution_store = evolution_store
        self.candidate_store = evolution_store.candidate_store
        self.materialization_store = evolution_store.materialization_store
        self.event_store = evolution_store.event_store
        self.policy, self.policy_json, self.policy_hash = load_policy()
        new = not self.database.exists()
        self.connection = sqlite3.connect(self.database); self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        try:
            if new: self._initialize()
            self._verify_metadata(); self._verify_policy_snapshot()
        except Exception:
            self.connection.close(); raise

    def __enter__(self) -> "LifecycleStore": return self
    def __exit__(self, *_args: object) -> None: self.close()
    def close(self) -> None: self.connection.close()

    def _initialize(self) -> None:
        self.connection.executescript("""
        CREATE TABLE lifecycle_store_meta(
          singleton INTEGER PRIMARY KEY CHECK(singleton=1), store_schema_version TEXT NOT NULL,
          directive_schema_version TEXT NOT NULL, lifecycle_schema_version TEXT NOT NULL,
          processor_version TEXT NOT NULL, baseline_2e_tag TEXT NOT NULL, baseline_2e_commit TEXT NOT NULL,
          baseline_2d_tag TEXT NOT NULL, baseline_2d_commit TEXT NOT NULL,
          architecture_tag TEXT NOT NULL, architecture_commit TEXT NOT NULL,
          production_tag TEXT NOT NULL, production_commit TEXT NOT NULL, authority TEXT NOT NULL);
        CREATE TABLE lifecycle_policies(
          policy_id TEXT PRIMARY KEY, policy_version INTEGER NOT NULL UNIQUE, policy_hash TEXT NOT NULL UNIQUE,
          processor_version TEXT NOT NULL, canonical_json TEXT NOT NULL);
        CREATE TABLE lifecycle_directives(
          directive_id TEXT PRIMARY KEY, directive_type TEXT NOT NULL, target_event_id TEXT NOT NULL UNIQUE,
          base_event_hash TEXT NOT NULL, target_evolution_id TEXT NOT NULL, target_materialization_id TEXT NOT NULL,
          lifecycle_cutoff TEXT NOT NULL, record_hash TEXT NOT NULL UNIQUE, canonical_json TEXT NOT NULL);
        CREATE TABLE directive_dependencies(
          directive_id TEXT NOT NULL, dependency_record_type TEXT NOT NULL,
          dependency_record_id TEXT NOT NULL, dependency_record_hash TEXT NOT NULL,
          PRIMARY KEY(directive_id,dependency_record_type,dependency_record_id),
          FOREIGN KEY(directive_id) REFERENCES lifecycle_directives(directive_id));
        CREATE TABLE lifecycle_records(
          lifecycle_id TEXT PRIMARY KEY, directive_id TEXT NOT NULL UNIQUE, target_event_id TEXT NOT NULL UNIQUE,
          base_event_hash TEXT NOT NULL, result_event_hash TEXT NOT NULL,
          record_hash TEXT NOT NULL UNIQUE, canonical_json TEXT NOT NULL,
          FOREIGN KEY(directive_id) REFERENCES lifecycle_directives(directive_id));
        CREATE TABLE lifecycle_transitions(
          lifecycle_id TEXT NOT NULL, relation TEXT NOT NULL, affected_evidence_id TEXT NOT NULL,
          affected_evidence_hash TEXT NOT NULL, lifecycle_evidence_id TEXT NOT NULL,
          lifecycle_evidence_hash TEXT NOT NULL,
          PRIMARY KEY(lifecycle_id,affected_evidence_id,lifecycle_evidence_id),
          FOREIGN KEY(lifecycle_id) REFERENCES lifecycle_records(lifecycle_id));
        CREATE TABLE lifecycle_dependencies(
          lifecycle_id TEXT NOT NULL, dependency_record_type TEXT NOT NULL,
          dependency_record_id TEXT NOT NULL, dependency_record_hash TEXT NOT NULL,
          PRIMARY KEY(lifecycle_id,dependency_record_type,dependency_record_id),
          FOREIGN KEY(lifecycle_id) REFERENCES lifecycle_records(lifecycle_id));
        """)
        self.connection.execute("INSERT INTO lifecycle_store_meta VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?)",(
            STORE_SCHEMA_VERSION,DIRECTIVE_SCHEMA_VERSION,LIFECYCLE_SCHEMA_VERSION,PROCESSOR_VERSION,
            BASELINE_2E_TAG,BASELINE_2E_COMMIT,BASELINE_2D_TAG,BASELINE_2D_COMMIT,
            ARCHITECTURE_TAG,ARCHITECTURE_COMMIT,PRODUCTION_TAG,PRODUCTION_COMMIT,AUTHORITY))
        self.connection.execute("INSERT INTO lifecycle_policies VALUES(?,?,?,?,?)",(
            POLICY_ID,POLICY_VERSION,self.policy_hash,PROCESSOR_VERSION,self.policy_json))
        for table in ("lifecycle_store_meta","lifecycle_policies","lifecycle_directives",
                      "directive_dependencies","lifecycle_records","lifecycle_transitions","lifecycle_dependencies"):
            self.connection.executescript(f"""
            CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table}
            BEGIN SELECT RAISE(ABORT,'IMMUTABLE_TABLE_UPDATE'); END;
            CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT,'IMMUTABLE_TABLE_DELETE'); END;
            """)
        self.connection.commit()

    def _verify_metadata(self) -> None:
        fields=("store_schema_version","directive_schema_version","lifecycle_schema_version","processor_version",
                "baseline_2e_tag","baseline_2e_commit","baseline_2d_tag","baseline_2d_commit",
                "architecture_tag","architecture_commit","production_tag","production_commit","authority")
        expected=(STORE_SCHEMA_VERSION,DIRECTIVE_SCHEMA_VERSION,LIFECYCLE_SCHEMA_VERSION,PROCESSOR_VERSION,
                  BASELINE_2E_TAG,BASELINE_2E_COMMIT,BASELINE_2D_TAG,BASELINE_2D_COMMIT,
                  ARCHITECTURE_TAG,ARCHITECTURE_COMMIT,PRODUCTION_TAG,PRODUCTION_COMMIT,AUTHORITY)
        try:
            row=self.connection.execute("SELECT * FROM lifecycle_store_meta WHERE singleton=1").fetchone()
            if row is None or tuple(row[field] for field in fields)!=expected:
                raise LifecycleIntegrityFailure("LIFECYCLE_STORE_METADATA_MISMATCH")
        except sqlite3.Error as exc: raise LifecycleIntegrityFailure("LIFECYCLE_STORE_METADATA_INVALID") from exc

    def _verify_policy_snapshot(self) -> dict:
        row=self.connection.execute("SELECT * FROM lifecycle_policies WHERE policy_id=?",(POLICY_ID,)).fetchone()
        if row is None: raise LifecycleIntegrityFailure("LIFECYCLE_POLICY_MISSING")
        try: stored=json.loads(row["canonical_json"])
        except (TypeError,json.JSONDecodeError) as exc: raise LifecycleIntegrityFailure("LIFECYCLE_POLICY_JSON_INVALID") from exc
        validate_policy(stored)
        if (row["canonical_json"]!=canonical_json(stored) or row["policy_version"]!=POLICY_VERSION
                or row["policy_hash"]!=self.policy_hash or row["processor_version"]!=PROCESSOR_VERSION
                or stored!=self.policy):
            raise LifecycleIntegrityFailure("LIFECYCLE_POLICY_SNAPSHOT_MISMATCH")
        return stored

    def _verify_upstream(self) -> None:
        try:
            if self.candidate_store.integrity_check().get("result")!="PASS": raise ValueError
        except Exception as exc: raise LifecycleIntegrityFailure("UPSTREAM_CANDIDATE_INTEGRITY_FAILED") from exc
        try:
            if self.event_store.integrity_check().get("result")!="PASS": raise ValueError
        except Exception as exc: raise LifecycleIntegrityFailure("UPSTREAM_EVENT_INTEGRITY_FAILED") from exc

    def _event_key(self,event_id:str)->str:
        row=self.event_store.connection.execute("SELECT event_key_json FROM event_series WHERE event_id=?",(event_id,)).fetchone()
        if row is None: raise Stage6LifecycleError("TARGET_EVENT_NOT_FOUND")
        key=json.loads(row[0]).get("event_key")
        if not isinstance(key,str) or not key.startswith(EVENT_PREFIX): raise Stage6LifecycleError("TARGET_NOT_STAGE6_2D_EVENT")
        return key

    def _validate_v2_anchor(self,event_id:str)->tuple[dict,dict,dict,dict]:
        self.evolution_store._verify_metadata(); self.evolution_store._verify_policy_snapshot()
        v1,materialization,_candidate=self.evolution_store._validate_v1_anchor(event_id)
        v2=self.event_store.get_event(event_id,2)
        event_rows=self.event_store.connection.execute(
            "SELECT * FROM event_records WHERE event_id=? AND event_version IN (1,2) ORDER BY event_version",(event_id,)).fetchall()
        if len(event_rows)!=2:
            raise LifecycleIntegrityFailure("LIFECYCLE_V1_V2_RECORDS_MISSING")
        for row,event in zip(event_rows,(v1,v2)):
            if (row["canonical_json"]!=canonical_json(event)
                    or (row["event_id"],row["event_version"],row["previous_event_version_hash"],row["record_hash"],row["last_updated_timestamp"])!=(event["event_id"],event["event_version"],event["previous_event_version_hash"],event["record_hash"],event["last_updated_timestamp"])):
                raise LifecycleIntegrityFailure("LIFECYCLE_V1_V2_TYPED_BINDING_MISMATCH")
        if v2["event_version"]!=2 or v2["previous_event_version_hash"]!=v1["record_hash"]:
            raise LifecycleIntegrityFailure("LIFECYCLE_V2_PREDECESSOR_MISMATCH")
        drow=self.evolution_store.connection.execute("SELECT * FROM evolution_directives WHERE target_event_id=?",(event_id,)).fetchone()
        if drow is None: raise LifecycleIntegrityFailure("LIFECYCLE_EVOLUTION_DIRECTIVE_MISSING")
        directive=json.loads(drow["canonical_json"])
        if drow["canonical_json"]!=canonical_json(directive): raise LifecycleIntegrityFailure("LIFECYCLE_EVOLUTION_DIRECTIVE_JSON_MISMATCH")
        validate_evolution_directive(directive,v1,materialization,expected_policy_hash=self.evolution_store.policy_hash)
        rrow=self.evolution_store.connection.execute("SELECT * FROM evolution_records WHERE directive_id=?",(directive["directive_id"],)).fetchone()
        if rrow is None: raise LifecycleIntegrityFailure("LIFECYCLE_EVOLUTION_RECORD_MISSING")
        evolution=json.loads(rrow["canonical_json"])
        if rrow["canonical_json"]!=canonical_json(evolution): raise LifecycleIntegrityFailure("LIFECYCLE_EVOLUTION_JSON_MISMATCH")
        validate_evolution(evolution,directive,v1,materialization,expected_policy_hash=self.evolution_store.policy_hash)
        all_evidence=self.evolution_store._evidence(sorted({*v1["source_evidence_ids"],*directive["additional_evidence_ids"]}),directive["evolution_cutoff"])
        expected_v2=build_event_v2(event_key=self._event_key(event_id),base_event=v1,directive=directive,evidence=all_evidence)
        replay=build_evolution_record(directive=directive,base_event=v1,result_event=expected_v2,
            materialization=materialization,policy_hash=self.evolution_store.policy_hash)
        if v2!=expected_v2 or evolution!=replay or evolution["result_event_hash"]!=v2["record_hash"]:
            raise LifecycleIntegrityFailure("LIFECYCLE_EVOLUTION_V2_ANCHOR_MISMATCH")
        return v1,v2,materialization,evolution

    def _evidence(self,ids:list[str])->list[dict]:
        return self.event_store._load_evidence(ids,verify_store=False)

    def _derive_transitions(self,directive:dict,base_event:dict)->tuple[list[dict],list[dict],dict|None]:
        lifecycle=self._evidence(directive["lifecycle_evidence_ids"])
        affected=self._evidence(directive["affected_evidence_ids"])
        affected_by_id={item["evidence_id"]:item for item in affected}
        active=set(base_event["source_evidence_ids"]); action=directive["directive_type"]
        if action in {"APPLY_CORRECTION","RETRACT_EVENT"} and base_event["event_status"]!="CANDIDATE":
            raise Stage6LifecycleError("LIFECYCLE_CANDIDATE_BASE_REQUIRED")
        conflict=None
        if action=="RESOLVE_CONFLICT":
            if (base_event["event_status"]!="CONFLICTED" or base_event["corroboration_status"]!="CONFLICTING_EVIDENCE"
                    or len(base_event["evidence_conflicts"])!=1 or base_event["evidence_conflicts"][0]["status"]!="OPEN"):
                raise Stage6LifecycleError("LIFECYCLE_OPEN_CONFLICT_BASE_REQUIRED")
            original=base_event["evidence_conflicts"][0]
            conflict={"evidence_ids":list(original["evidence_ids"]),"description":original["description"],"status":"RESOLVED"}
            allowed=set(original["evidence_ids"])
        else: allowed=active
        transitions=[]; targets=[]
        cutoff=parse_utc(directive["lifecycle_cutoff"],"lifecycle_cutoff")
        for item in lifecycle:
            correction,retraction=item["correction_of_evidence_id"],item["retraction_of_evidence_id"]
            if (correction is None)==(retraction is None): raise Stage6LifecycleError("EXACTLY_ONE_LIFECYCLE_RELATION_REQUIRED")
            relation,target=("CORRECTION",correction) if correction is not None else ("RETRACTION",retraction)
            if action=="APPLY_CORRECTION" and relation!="CORRECTION": raise Stage6LifecycleError("CORRECTION_RELATION_REQUIRED")
            if action=="RETRACT_EVENT" and relation!="RETRACTION": raise Stage6LifecycleError("RETRACTION_RELATION_REQUIRED")
            if target not in allowed or target not in active or target not in affected_by_id:
                raise Stage6LifecycleError("LIFECYCLE_TARGET_NOT_ACTIVE_OR_ALLOWED")
            old=affected_by_id[target]
            if item["source_id"]!=old["source_id"]: raise Stage6LifecycleError("LIFECYCLE_SAME_SOURCE_REQUIRED")
            if item["authority_level"] not in TRUSTWORTHY or old["authority_level"] not in TRUSTWORTHY:
                raise Stage6LifecycleError("LIFECYCLE_TRUSTWORTHY_EVIDENCE_REQUIRED")
            if (parse_utc(item["retrieved_timestamp_utc"],"retrieved")<parse_utc(old["retrieved_timestamp_utc"],"affected.retrieved")
                    or parse_utc(item["retrieved_timestamp_utc"],"retrieved")>cutoff):
                raise Stage6LifecycleError("LIFECYCLE_EVIDENCE_TIMING_INVALID")
            targets.append(target)
            transitions.append({"relation":relation,"affected_evidence_id":target,
                "affected_evidence_hash":old["record_hash"],"lifecycle_evidence_id":item["evidence_id"],
                "lifecycle_evidence_hash":item["record_hash"]})
        if len(targets)!=len(set(targets)) or set(targets)!=set(directive["affected_evidence_ids"]):
            raise Stage6LifecycleError("LIFECYCLE_ONE_TO_ONE_MAPPING_INVALID")
        if action=="RETRACT_EVENT" and set(targets)!=active:
            raise Stage6LifecycleError("COMPLETE_EVENT_RETRACTION_REQUIRED")
        transitions.sort(key=lambda item:(item["affected_evidence_id"],item["lifecycle_evidence_id"]))
        return transitions,lifecycle,conflict

    def _active_evidence(self,base_event:dict,directive:dict,transitions:list[dict])->list[dict]:
        return self._evidence(active_evidence_ids(base_event,directive["directive_type"],transitions))

    def _directive_dependencies(self,directive:dict,evolution:dict,materialization:dict,
                                affected:list[dict],lifecycle:list[dict])->list[tuple[str,str,str]]:
        return [(directive["target_event_id"]+":v2",directive["base_event_hash"],"BASE_STAGE6_EVENT_V2"),
                (evolution["evolution_id"],evolution["record_hash"],"STAGE6_2E_EVOLUTION"),
                (materialization["materialization_id"],materialization["record_hash"],"STAGE6_2D_MATERIALIZATION"),
                (POLICY_ID,self.policy_hash,"LIFECYCLE_POLICY"),
                *[(item["evidence_id"],item["record_hash"],"AFFECTED_EVIDENCE") for item in affected],
                *[(item["evidence_id"],item["record_hash"],"LIFECYCLE_EVIDENCE") for item in lifecycle]]

    def _lifecycle_dependencies(self,record:dict,directive:dict,evolution:dict,materialization:dict,
                                affected:list[dict],lifecycle:list[dict])->list[tuple[str,str,str]]:
        return [(directive["directive_id"],directive["record_hash"],"LIFECYCLE_DIRECTIVE"),
                *self._directive_dependencies(directive,evolution,materialization,affected,lifecycle),
                (record["target_event_id"]+":v3",record["result_event_hash"],"RESULT_STAGE6_EVENT_V3")]

    def apply_lifecycle(self,*,directive_type:str,target_event_id:str,lifecycle_evidence_ids:list[str],
                        affected_evidence_ids:list[str],lifecycle_cutoff:str)->dict:
        self._verify_metadata(); self._verify_policy_snapshot(); self._verify_upstream()
        _v1,v2,materialization,evolution=self._validate_v2_anchor(target_event_id)
        directive=build_directive(directive_type=directive_type,base_event=v2,evolution=evolution,
            materialization=materialization,lifecycle_evidence_ids=lifecycle_evidence_ids,
            affected_evidence_ids=affected_evidence_ids,lifecycle_cutoff=lifecycle_cutoff,
            policy=self.policy,policy_hash=self.policy_hash)
        validate_directive(directive,v2,evolution,materialization,expected_policy_hash=self.policy_hash)
        transitions,lifecycle_evidence,resolved_conflict=self._derive_transitions(directive,v2)
        affected=self._evidence(directive["affected_evidence_ids"])
        active=self._active_evidence(v2,directive,transitions)
        expected_v3=build_event_v3(event_key=self._event_key(target_event_id),base_event=v2,
            directive=directive,transitions=transitions,active_evidence=active)
        existing_v3=self.event_store.connection.execute(
            "SELECT canonical_json FROM event_records WHERE event_id=? AND event_version=3",(target_event_id,)).fetchone()
        existing_directive=self.connection.execute("SELECT canonical_json FROM lifecycle_directives WHERE target_event_id=?",(target_event_id,)).fetchone()
        if existing_v3 is not None and json.loads(existing_v3[0])!=expected_v3:
            raise LifecycleConflict("TARGET_ALREADY_HAS_DIFFERENT_V3")
        if existing_directive is not None and json.loads(existing_directive[0])!=directive:
            raise LifecycleConflict("TARGET_ALREADY_HAS_DISTINCT_LIFECYCLE")
        response=self.event_store.append_event(event_key=self._event_key(target_event_id),event_version=3,
            previous_event_version_hash=v2["record_hash"],source_evidence_ids=expected_v3["source_evidence_ids"],
            entity_resolution_version=v2["entity_resolution_version"],event_type=v2["event_type"],
            event_status=expected_v3["event_status"],direction=v2["direction"],severity=v2["severity"],
            materiality=v2["materiality"],confidence=v2["confidence"],entities=v2["entities"],
            sectors=v2["sectors"],geographies=v2["geographies"],commodities=v2["commodities"],
            currencies=v2["currencies"],corroboration_status=expected_v3["corroboration_status"],
            first_known_timestamp=v2["first_known_timestamp"],last_updated_timestamp=directive["lifecycle_cutoff"],
            event_horizon=v2["event_horizon"],transmission_channels=v2["transmission_channels"],
            causality_assessment=v2["causality_assessment"],evidence_conflicts=[])
        if response["status"] not in {"CREATED","IDEMPOTENT_SUCCESS"} or response["event"]!=expected_v3:
            raise LifecycleIntegrityFailure("EVENTSTORE_V3_RESULT_MISMATCH")
        record=build_lifecycle_record(directive=directive,base_event=v2,result_event=expected_v3,
            evolution=evolution,materialization=materialization,transitions=transitions,
            resolved_conflict=resolved_conflict,policy_hash=self.policy_hash)
        validate_lifecycle(record,directive,v2,evolution,materialization,expected_policy_hash=self.policy_hash)
        if existing_directive is not None:
            stored=self.connection.execute("SELECT canonical_json FROM lifecycle_records WHERE directive_id=?",(directive["directive_id"],)).fetchone()
            if stored is not None and json.loads(stored[0])==record:
                return {"status":"IDEMPOTENT_SUCCESS","directive":directive,"lifecycle":record,"event":expected_v3}
            raise LifecycleConflict("INCOMPATIBLE_LIFECYCLE_IDENTITY")
        try:
            with self.connection:
                self.connection.execute("INSERT INTO lifecycle_directives VALUES(?,?,?,?,?,?,?,?,?)",(
                    directive["directive_id"],directive_type,target_event_id,directive["base_event_hash"],
                    directive["target_evolution_id"],directive["target_materialization_id"],
                    directive["lifecycle_cutoff"],directive["record_hash"],canonical_json(directive)))
                self.connection.executemany("INSERT INTO directive_dependencies VALUES(?,?,?,?)",[
                    (directive["directive_id"],kind,identity,record_hash) for identity,record_hash,kind in
                    self._directive_dependencies(directive,evolution,materialization,affected,lifecycle_evidence)])
                self.connection.execute("INSERT INTO lifecycle_records VALUES(?,?,?,?,?,?,?)",(
                    record["lifecycle_id"],directive["directive_id"],target_event_id,record["base_event_hash"],
                    record["result_event_hash"],record["record_hash"],canonical_json(record)))
                self.connection.executemany("INSERT INTO lifecycle_transitions VALUES(?,?,?,?,?,?)",[
                    (record["lifecycle_id"],item["relation"],item["affected_evidence_id"],item["affected_evidence_hash"],
                     item["lifecycle_evidence_id"],item["lifecycle_evidence_hash"]) for item in transitions])
                self.connection.executemany("INSERT INTO lifecycle_dependencies VALUES(?,?,?,?)",[
                    (record["lifecycle_id"],kind,identity,record_hash) for identity,record_hash,kind in
                    self._lifecycle_dependencies(record,directive,evolution,materialization,affected,lifecycle_evidence)])
        except sqlite3.IntegrityError as exc: raise LifecycleConflict("LIFECYCLE_STORE_INSERT_CONFLICT") from exc
        return {"status":"CREATED","directive":directive,"lifecycle":record,"event":expected_v3}

    @staticmethod
    def _verify_dependencies(rows:list[sqlite3.Row],expected:list[tuple[str,str,str]],label:str)->None:
        actual={(row["dependency_record_type"],row["dependency_record_id"]):row["dependency_record_hash"] for row in rows}
        wanted={(kind,identity):record_hash for identity,record_hash,kind in expected}
        if actual!=wanted: raise LifecycleIntegrityFailure(label+"_DEPENDENCY_MISMATCH")

    def _verify_policy_dependency(self,rows:list[sqlite3.Row],record:dict,label:str)->None:
        found=[row for row in rows if row["dependency_record_type"]=="LIFECYCLE_POLICY"]
        if (len(found)!=1 or found[0]["dependency_record_id"]!=record["policy_id"] or record["policy_id"]!=POLICY_ID
                or found[0]["dependency_record_hash"]!=record["policy_hash"] or record["policy_hash"]!=self.policy_hash):
            raise LifecycleIntegrityFailure(label+"_POLICY_DEPENDENCY_MISMATCH")

    def integrity_check(self)->dict:
        try:
            self._verify_metadata()
            if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok": raise LifecycleIntegrityFailure("LIFECYCLE_SQLITE_INTEGRITY_FAILURE")
            if self.connection.execute("PRAGMA foreign_key_check").fetchall(): raise LifecycleIntegrityFailure("LIFECYCLE_FOREIGN_KEY_FAILURE")
            self._verify_policy_snapshot(); self._verify_upstream()
            tables=("lifecycle_store_meta","lifecycle_policies","lifecycle_directives","directive_dependencies","lifecycle_records","lifecycle_transitions","lifecycle_dependencies")
            for table in tables:
                triggers={row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,))}
                if triggers!={f"protect_{table}_update",f"protect_{table}_delete"}: raise LifecycleIntegrityFailure("LIFECYCLE_APPEND_ONLY_TRIGGER_MISSING")
            directives={row["directive_id"]:row for row in self.connection.execute("SELECT * FROM lifecycle_directives")}
            records={row["directive_id"]:row for row in self.connection.execute("SELECT * FROM lifecycle_records")}
            if set(directives)!=set(records): raise LifecycleIntegrityFailure("LIFECYCLE_DIRECTIVE_RECORD_COVERAGE_MISMATCH")
            owned=set()
            for directive_id,row in directives.items():
                directive=json.loads(row["canonical_json"]); _v1,v2,materialization,evolution=self._validate_v2_anchor(directive["target_event_id"])
                if row["canonical_json"]!=canonical_json(directive): raise LifecycleIntegrityFailure("LIFECYCLE_DIRECTIVE_CANONICAL_MISMATCH")
                validate_directive(directive,v2,evolution,materialization,expected_policy_hash=self.policy_hash)
                transitions,lifecycle_evidence,resolved_conflict=self._derive_transitions(directive,v2)
                affected=self._evidence(directive["affected_evidence_ids"]); active=self._active_evidence(v2,directive,transitions)
                expected_v3=build_event_v3(event_key=self._event_key(v2["event_id"]),base_event=v2,directive=directive,transitions=transitions,active_evidence=active)
                actual_v3=self.event_store.get_event(v2["event_id"],3)
                if actual_v3!=expected_v3: raise LifecycleIntegrityFailure("LIFECYCLE_EVENT_V3_REPLAY_MISMATCH")
                record_row=records[directive_id]; record=json.loads(record_row["canonical_json"])
                if record_row["canonical_json"]!=canonical_json(record): raise LifecycleIntegrityFailure("LIFECYCLE_CANONICAL_MISMATCH")
                validate_lifecycle(record,directive,v2,evolution,materialization,expected_policy_hash=self.policy_hash)
                replay=build_lifecycle_record(directive=directive,base_event=v2,result_event=expected_v3,evolution=evolution,
                    materialization=materialization,transitions=transitions,resolved_conflict=resolved_conflict,policy_hash=self.policy_hash)
                if record!=replay: raise LifecycleIntegrityFailure("LIFECYCLE_REPLAY_MISMATCH")
                if (row["directive_type"],row["target_event_id"],row["base_event_hash"],row["target_evolution_id"],row["target_materialization_id"],row["lifecycle_cutoff"],row["record_hash"])!=(directive["directive_type"],directive["target_event_id"],directive["base_event_hash"],directive["target_evolution_id"],directive["target_materialization_id"],directive["lifecycle_cutoff"],directive["record_hash"]): raise LifecycleIntegrityFailure("LIFECYCLE_DIRECTIVE_TYPED_MISMATCH")
                if (record_row["lifecycle_id"],record_row["target_event_id"],record_row["base_event_hash"],record_row["result_event_hash"],record_row["record_hash"])!=(record["lifecycle_id"],record["target_event_id"],record["base_event_hash"],record["result_event_hash"],record["record_hash"]): raise LifecycleIntegrityFailure("LIFECYCLE_TYPED_MISMATCH")
                transition_rows=[dict(item) for item in self.connection.execute("SELECT relation,affected_evidence_id,affected_evidence_hash,lifecycle_evidence_id,lifecycle_evidence_hash FROM lifecycle_transitions WHERE lifecycle_id=? ORDER BY affected_evidence_id,lifecycle_evidence_id",(record["lifecycle_id"],))]
                if transition_rows!=transitions: raise LifecycleIntegrityFailure("LIFECYCLE_TRANSITION_MISMATCH")
                ddeps=list(self.connection.execute("SELECT * FROM directive_dependencies WHERE directive_id=?",(directive_id,)))
                ldeps=list(self.connection.execute("SELECT * FROM lifecycle_dependencies WHERE lifecycle_id=?",(record["lifecycle_id"],)))
                self._verify_policy_dependency(ddeps,directive,"DIRECTIVE"); self._verify_policy_dependency(ldeps,record,"LIFECYCLE")
                self._verify_dependencies(ddeps,self._directive_dependencies(directive,evolution,materialization,affected,lifecycle_evidence),"DIRECTIVE")
                self._verify_dependencies(ldeps,self._lifecycle_dependencies(record,directive,evolution,materialization,affected,lifecycle_evidence),"LIFECYCLE")
                owned.add(v2["event_id"])
            actual=set()
            for series in self.event_store.connection.execute("SELECT event_id,event_key_json FROM event_series"):
                key=json.loads(series["event_key_json"]).get("event_key")
                if isinstance(key,str) and key.startswith(EVENT_PREFIX):
                    versions=[row[0] for row in self.event_store.connection.execute("SELECT event_version FROM event_records WHERE event_id=? ORDER BY event_version",(series["event_id"],))]
                    if any(version>3 for version in versions): raise LifecycleIntegrityFailure("STAGE6_2F_EVENT_V4_PROHIBITED")
                    if 3 in versions: actual.add(series["event_id"])
            if actual!=owned: raise LifecycleIntegrityFailure("ORPHAN_STAGE6_2F_EVENT_V3")
            return {"result":"PASS","lifecycles":len(records),"event_v3":len(owned),"policy_hash":self.policy_hash,"authority":AUTHORITY}
        except LifecycleIntegrityFailure: raise
        except Stage6LifecycleError as exc: raise LifecycleIntegrityFailure(f"LIFECYCLE_SEMANTIC_INTEGRITY_FAILURE:{exc}") from exc
        except Exception as exc: raise LifecycleIntegrityFailure("FULL_LIFECYCLE_INTEGRITY_FAILURE") from exc
