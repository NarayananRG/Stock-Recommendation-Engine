"""Append-only store for explicit, non-directional Event-to-Exposure bindings."""
from __future__ import annotations
import json,sqlite3
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json,without
from stage6_events import EventStore
from stage6_exposure import ExposureStore
from .binding_builder import BINDING_SCHEMA_VERSION,assertion_hash,build_binding
from .binding_validation import validate_binding
from .errors import BindingConflict,BindingIntegrityFailure,Stage6BindingError
from .policy import AUTHORITY,POLICY_ID,PROCESSOR_VERSION,load_policy

STORE_SCHEMA_VERSION="STAGE6_3B_EVENT_EXPOSURE_BINDING_STORE_V1"
BASELINE_TAG="stage6-3a-pit-exposure-record-foundation-baseline";BASELINE_COMMIT="a71b6ef8ab3fa0a99bf34635774fcdb4fae526ab"
BASELINE_2F_TAG="stage6-2f-controlled-event-lifecycle-baseline";BASELINE_2F_COMMIT="9d18f07e159cf147dcfb35654a84da8690e13879"
ARCHITECTURE_TAG="stage6-decision-intelligence-architecture-baseline-v2";ARCHITECTURE_COMMIT="d5bc19c7c2341f56bcaa8c890e0d95979dca878b"
PRODUCTION_TAG="stage5d5-live-paper-runner-baseline";PRODUCTION_COMMIT="74b2710f0e19bd403978da81e87f25a3059ace06"

class BindingStore:
    def __init__(self,database:Path,event_store:EventStore,exposure_store:ExposureStore):
        self.database=Path(database);self.database.parent.mkdir(parents=True,exist_ok=True);self.event_store=event_store;self.exposure_store=exposure_store
        self.policy,self.policy_json,self.policy_hash=load_policy();new=not self.database.exists();self.connection=sqlite3.connect(self.database);self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA foreign_keys=ON")
        try:
            if new:self._initialize()
            self._verify_metadata();self._verify_policy()
        except Exception:self.connection.close();raise
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
    def close(self):self.connection.close()
    def _initialize(self):
        self.connection.executescript("""
        CREATE TABLE binding_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT NOT NULL,binding_schema_version TEXT NOT NULL,baseline_tag TEXT NOT NULL,baseline_commit TEXT NOT NULL,baseline_2f_tag TEXT NOT NULL,baseline_2f_commit TEXT NOT NULL,architecture_tag TEXT NOT NULL,architecture_commit TEXT NOT NULL,production_tag TEXT NOT NULL,production_commit TEXT NOT NULL,processor_version TEXT NOT NULL,authority TEXT NOT NULL);
        CREATE TABLE binding_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT NOT NULL UNIQUE,canonical_json TEXT NOT NULL);
        CREATE TABLE binding_records(binding_id TEXT PRIMARY KEY,event_id TEXT NOT NULL,event_version INTEGER NOT NULL,event_hash TEXT NOT NULL,exposure_id TEXT NOT NULL,exposure_version INTEGER NOT NULL,exposure_hash TEXT NOT NULL,binding_cutoff_timestamp TEXT NOT NULL,record_hash TEXT NOT NULL UNIQUE,canonical_json TEXT NOT NULL);
        CREATE TABLE binding_assertions(binding_id TEXT NOT NULL,assertion_hash TEXT NOT NULL,exposure_type TEXT NOT NULL,value_type TEXT NOT NULL,canonical_reference_json TEXT NOT NULL,PRIMARY KEY(binding_id,assertion_hash),FOREIGN KEY(binding_id) REFERENCES binding_records(binding_id));
        CREATE TABLE binding_dependencies(binding_id TEXT NOT NULL,dependency_record_type TEXT NOT NULL,dependency_record_id TEXT NOT NULL,dependency_record_hash TEXT NOT NULL,PRIMARY KEY(binding_id,dependency_record_type,dependency_record_id),FOREIGN KEY(binding_id) REFERENCES binding_records(binding_id));
        """)
        self.connection.execute("INSERT INTO binding_store_meta VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?)",(STORE_SCHEMA_VERSION,BINDING_SCHEMA_VERSION,BASELINE_TAG,BASELINE_COMMIT,BASELINE_2F_TAG,BASELINE_2F_COMMIT,ARCHITECTURE_TAG,ARCHITECTURE_COMMIT,PRODUCTION_TAG,PRODUCTION_COMMIT,PROCESSOR_VERSION,AUTHORITY))
        self.connection.execute("INSERT INTO binding_policies VALUES(?,?,?)",(POLICY_ID,self.policy_hash,self.policy_json))
        for table in ("binding_store_meta","binding_policies","binding_records","binding_assertions","binding_dependencies"):
            self.connection.executescript(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE_TABLE_UPDATE'); END; CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE_TABLE_DELETE'); END;")
        self.connection.commit()
    def _verify_metadata(self):
        row=self.connection.execute("SELECT * FROM binding_store_meta WHERE singleton=1").fetchone();fields=("store_schema_version","binding_schema_version","baseline_tag","baseline_commit","baseline_2f_tag","baseline_2f_commit","architecture_tag","architecture_commit","production_tag","production_commit","processor_version","authority");expected=(STORE_SCHEMA_VERSION,BINDING_SCHEMA_VERSION,BASELINE_TAG,BASELINE_COMMIT,BASELINE_2F_TAG,BASELINE_2F_COMMIT,ARCHITECTURE_TAG,ARCHITECTURE_COMMIT,PRODUCTION_TAG,PRODUCTION_COMMIT,PROCESSOR_VERSION,AUTHORITY)
        if row is None or tuple(row[x] for x in fields)!=expected:raise BindingIntegrityFailure("BINDING_STORE_METADATA_MISMATCH")
    def _verify_policy(self):
        row=self.connection.execute("SELECT * FROM binding_policies WHERE policy_id=?",(POLICY_ID,)).fetchone()
        if row is None or (row["policy_hash"],row["canonical_json"])!=(self.policy_hash,self.policy_json):raise BindingIntegrityFailure("BINDING_POLICY_SNAPSHOT_MISMATCH")
    def _verify_upstream(self):
        if self.event_store.integrity_check().get("result")!="PASS":raise BindingIntegrityFailure("EVENT_STORE_INTEGRITY_FAILED")
        if self.exposure_store.integrity_check().get("result")!="PASS":raise BindingIntegrityFailure("EXPOSURE_STORE_INTEGRITY_FAILED")
    def _event(self,event_id,event_version):
        row=self.event_store.connection.execute("SELECT * FROM event_records WHERE event_id=? AND event_version=?",(event_id,event_version)).fetchone()
        if row is None:raise Stage6BindingError("EXACT_EVENT_VERSION_NOT_FOUND")
        event=json.loads(row["canonical_json"])
        if row["canonical_json"]!=canonical_json(event) or (row["event_id"],row["event_version"],row["record_hash"],row["last_updated_timestamp"])!=(event["event_id"],event["event_version"],event["record_hash"],event["last_updated_timestamp"]) or event["record_hash"]!=canonical_hash(without(event,"record_hash")):raise BindingIntegrityFailure("EXACT_EVENT_BINDING_INVALID")
        if event["schema_version"]!="STAGE6_EVENT_V1":raise BindingIntegrityFailure("EVENT_SCHEMA_INVALID")
        return event
    def _exposure(self,exposure_id,exposure_version):
        row=self.exposure_store.connection.execute("SELECT * FROM exposure_records WHERE exposure_id=? AND exposure_version=?",(exposure_id,exposure_version)).fetchone()
        if row is None:raise Stage6BindingError("EXACT_EXPOSURE_VERSION_NOT_FOUND")
        exposure=json.loads(row["canonical_json"])
        if row["canonical_json"]!=canonical_json(exposure) or (row["exposure_id"],row["exposure_version"],row["record_hash"],row["data_cutoff_timestamp"])!=(exposure["exposure_id"],exposure["exposure_version"],exposure["record_hash"],exposure["data_cutoff_timestamp"]) or exposure["record_hash"]!=canonical_hash(without(exposure,"record_hash")):raise BindingIntegrityFailure("EXACT_EXPOSURE_BINDING_INVALID")
        if exposure["schema_version"]!="STAGE6_EXPOSURE_V2":raise BindingIntegrityFailure("EXPOSURE_SCHEMA_INVALID")
        return exposure
    @staticmethod
    def _select(exposure,hashes):
        if not isinstance(hashes,list) or not hashes or any(not isinstance(x,str) or not x for x in hashes) or len(hashes)!=len(set(hashes)):raise Stage6BindingError("SELECTED_ASSERTION_HASHES_INVALID")
        index={}
        for item in exposure["assertions"]:index.setdefault(assertion_hash(item),[]).append(item)
        selected=[]
        for identity in sorted(hashes):
            matches=index.get(identity,[])
            if not matches:raise Stage6BindingError("SELECTED_ASSERTION_NOT_FOUND")
            if len(matches)!=1:raise Stage6BindingError("ASSERTION_HASH_AMBIGUOUS")
            selected.append(matches[0])
        return selected
    def _evidence(self,exposure,ids):
        records=self.exposure_store._evidence(ids,exposure["data_cutoff_timestamp"])
        return records
    def _dependencies(self,record,event,exposure,evidence):
        return [("STAGE6_EVENT",f'{event["event_id"]}:v{event["event_version"]}',event["record_hash"]),("STAGE6_EXPOSURE",f'{exposure["exposure_id"]}:v{exposure["exposure_version"]}',exposure["record_hash"]),("ENTITY_REGISTRY_SNAPSHOT",exposure["entity_registry_snapshot_id"],exposure["entity_registry_hash"]),("BINDING_POLICY",POLICY_ID,self.policy_hash),*[("EVIDENCE",x["evidence_id"],x["record_hash"]) for x in evidence]]
    def append_binding(self,*,event_id,event_version,exposure_id,exposure_version,selected_assertion_hashes,binding_channel,binding_cutoff_timestamp):
        self._verify_metadata();self._verify_policy();self._verify_upstream();event=self._event(event_id,event_version);exposure=self._exposure(exposure_id,exposure_version);selected=self._select(exposure,selected_assertion_hashes)
        record=build_binding(event=event,exposure=exposure,selected_assertions=selected,binding_channel=binding_channel,binding_cutoff_timestamp=binding_cutoff_timestamp,policy=self.policy,policy_hash=self.policy_hash);validate_binding(record,event=event,exposure=exposure,expected_policy_hash=self.policy_hash)
        evidence=self._evidence(exposure,record["supporting_evidence_ids"]);deps=self._dependencies(record,event,exposure,evidence);existing=self.connection.execute("SELECT canonical_json FROM binding_records WHERE binding_id=?",(record["binding_id"],)).fetchone()
        if existing is not None:
            stored=[tuple(x) for x in self.connection.execute("SELECT dependency_record_type,dependency_record_id,dependency_record_hash FROM binding_dependencies WHERE binding_id=? ORDER BY dependency_record_type,dependency_record_id",(record["binding_id"],))]
            if existing[0]==canonical_json(record) and sorted(deps)==stored:return {"status":"IDEMPOTENT_SUCCESS","binding":record}
            raise BindingConflict("INCOMPATIBLE_BINDING_ID_COLLISION")
        try:
            with self.connection:
                self.connection.execute("INSERT INTO binding_records VALUES(?,?,?,?,?,?,?,?,?,?)",(record["binding_id"],event_id,event_version,event["record_hash"],exposure_id,exposure_version,exposure["record_hash"],record["binding_cutoff_timestamp"],record["record_hash"],canonical_json(record)))
                self.connection.executemany("INSERT INTO binding_assertions VALUES(?,?,?,?,?)",[(record["binding_id"],x["assertion_hash"],x["exposure_type"],x["value_type"],canonical_json(x)) for x in record["selected_assertions"]])
                self.connection.executemany("INSERT INTO binding_dependencies VALUES(?,?,?,?)",[(record["binding_id"],*x) for x in deps])
        except sqlite3.IntegrityError as exc:raise BindingConflict("BINDING_STORE_INSERT_CONFLICT") from exc
        return {"status":"CREATED","binding":record}
    def integrity_check(self):
        try:
            self._verify_metadata();self._verify_policy()
            if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():raise BindingIntegrityFailure("BINDING_SQLITE_INTEGRITY_FAILURE")
            self._verify_upstream()
            for table in ("binding_store_meta","binding_policies","binding_records","binding_assertions","binding_dependencies"):
                names={x[0] for x in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,))}
                if names!={f"protect_{table}_update",f"protect_{table}_delete"}:raise BindingIntegrityFailure("BINDING_APPEND_ONLY_TRIGGER_MISSING")
            count=0
            for row in self.connection.execute("SELECT * FROM binding_records"):
                count+=1;record=json.loads(row["canonical_json"]);event=self._event(record["event_id"],record["event_version"]);exposure=self._exposure(record["exposure_id"],record["exposure_version"]);validate_binding(record,event=event,exposure=exposure,expected_policy_hash=self.policy_hash)
                typed=(row["binding_id"],row["event_id"],row["event_version"],row["event_hash"],row["exposure_id"],row["exposure_version"],row["exposure_hash"],row["binding_cutoff_timestamp"],row["record_hash"]);expected=(record["binding_id"],record["event_id"],record["event_version"],record["event_hash"],record["exposure_id"],record["exposure_version"],record["exposure_hash"],record["binding_cutoff_timestamp"],record["record_hash"])
                if row["canonical_json"]!=canonical_json(record) or typed!=expected:raise BindingIntegrityFailure("BINDING_TYPED_COLUMN_MISMATCH")
                selected=self._select(exposure,[x["assertion_hash"] for x in record["selected_assertions"]]);replay=build_binding(event=event,exposure=exposure,selected_assertions=selected,binding_channel=record["binding_channel"],binding_cutoff_timestamp=record["binding_cutoff_timestamp"],policy=self.policy,policy_hash=self.policy_hash)
                if replay!=record:raise BindingIntegrityFailure("BINDING_REPLAY_MISMATCH")
                assertion_rows=self.connection.execute("SELECT * FROM binding_assertions WHERE binding_id=? ORDER BY assertion_hash",(record["binding_id"],)).fetchall();assertions=[]
                for item in assertion_rows:
                    ref=json.loads(item["canonical_reference_json"])
                    if item["canonical_reference_json"]!=canonical_json(ref) or (item["assertion_hash"],item["exposure_type"],item["value_type"])!=(ref["assertion_hash"],ref["exposure_type"],ref["value_type"]):raise BindingIntegrityFailure("BINDING_ASSERTION_TYPED_COLUMN_MISMATCH")
                    assertions.append(ref)
                if assertions!=record["selected_assertions"]:raise BindingIntegrityFailure("BINDING_ASSERTION_TABLE_MISMATCH")
                evidence=self._evidence(exposure,record["supporting_evidence_ids"]);wanted={(t,i):h for t,i,h in self._dependencies(record,event,exposure,evidence)};actual={(x["dependency_record_type"],x["dependency_record_id"]):x["dependency_record_hash"] for x in self.connection.execute("SELECT * FROM binding_dependencies WHERE binding_id=?",(record["binding_id"],))}
                if actual!=wanted:raise BindingIntegrityFailure("BINDING_DEPENDENCY_MISMATCH")
            return {"result":"PASS","bindings":count,"authority":AUTHORITY,"policy_hash":self.policy_hash}
        except BindingIntegrityFailure:raise
        except Exception as exc:raise BindingIntegrityFailure("FULL_BINDING_INTEGRITY_FAILURE") from exc
