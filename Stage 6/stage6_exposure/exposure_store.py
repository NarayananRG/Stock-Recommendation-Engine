"""Append-only point-in-time company exposure store."""
from __future__ import annotations
import json,sqlite3
from datetime import date
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json,parse_utc,without
from stage6_ingestion.evidence_store import IngestionStore
from stage6_ingestion.registry import resolve_entity
from .errors import ExposureIntegrityFailure,ExposureVersionConflict,Stage6ExposureError
from .exposure_builder import EXPOSURE_SCHEMA_VERSION,build_exposure,deterministic_exposure_id
from .exposure_validation import validate_exposure

STORE_SCHEMA_VERSION="STAGE6_3A_EXPOSURE_STORE_V1";AUTHORITY="SHADOW_ONLY"
BASELINE_TAG="stage6-2f-controlled-event-lifecycle-baseline";BASELINE_COMMIT="9d18f07e159cf147dcfb35654a84da8690e13879"
ARCHITECTURE_TAG="stage6-decision-intelligence-architecture-baseline-v2";ARCHITECTURE_COMMIT="d5bc19c7c2341f56bcaa8c890e0d95979dca878b"
PRODUCTION_TAG="stage5d5-live-paper-runner-baseline";PRODUCTION_COMMIT="74b2710f0e19bd403978da81e87f25a3059ace06"
TRUSTWORTHY={"PRIMARY_OFFICIAL","AUTHORITATIVE_INDEPENDENT"};REL_MAP={"PARENT":"PARENT","SUBSIDIARY":"SUBSIDIARY","GROUP_COMPANY":"CORPORATE_GROUP_MEMBER"}

class ExposureStore:
    def __init__(self,database:Path,ingestion_store:IngestionStore):
        self.database=Path(database);self.database.parent.mkdir(parents=True,exist_ok=True);self.ingestion_store=ingestion_store;new=not self.database.exists();self.connection=sqlite3.connect(self.database);self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA foreign_keys=ON")
        try:
            if new:self._initialize()
            self._verify_metadata()
        except Exception:self.connection.close();raise
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
    def close(self):self.connection.close()
    def _initialize(self):
        self.connection.executescript("""
        CREATE TABLE exposure_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT NOT NULL,exposure_schema_version TEXT NOT NULL,baseline_tag TEXT NOT NULL,baseline_commit TEXT NOT NULL,architecture_tag TEXT NOT NULL,architecture_commit TEXT NOT NULL,production_tag TEXT NOT NULL,production_commit TEXT NOT NULL,authority TEXT NOT NULL);
        CREATE TABLE exposure_series(exposure_id TEXT PRIMARY KEY,company_entity_id TEXT NOT NULL UNIQUE);
        CREATE TABLE exposure_records(exposure_id TEXT NOT NULL,exposure_version INTEGER NOT NULL,previous_version_hash TEXT,record_hash TEXT NOT NULL UNIQUE,as_of_timestamp TEXT NOT NULL,data_cutoff_timestamp TEXT NOT NULL,entity_registry_snapshot_id TEXT NOT NULL,canonical_json TEXT NOT NULL,PRIMARY KEY(exposure_id,exposure_version),FOREIGN KEY(exposure_id) REFERENCES exposure_series(exposure_id));
        CREATE TABLE exposure_dependencies(exposure_id TEXT NOT NULL,exposure_version INTEGER NOT NULL,dependency_record_type TEXT NOT NULL,dependency_record_id TEXT NOT NULL,dependency_record_hash TEXT NOT NULL,PRIMARY KEY(exposure_id,exposure_version,dependency_record_type,dependency_record_id),FOREIGN KEY(exposure_id,exposure_version) REFERENCES exposure_records(exposure_id,exposure_version));
        """)
        self.connection.execute("INSERT INTO exposure_store_meta VALUES(1,?,?,?,?,?,?,?,?,?)",(STORE_SCHEMA_VERSION,EXPOSURE_SCHEMA_VERSION,BASELINE_TAG,BASELINE_COMMIT,ARCHITECTURE_TAG,ARCHITECTURE_COMMIT,PRODUCTION_TAG,PRODUCTION_COMMIT,AUTHORITY))
        for table in ("exposure_store_meta","exposure_series","exposure_records","exposure_dependencies"):
            self.connection.executescript(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE_TABLE_UPDATE'); END;CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE_TABLE_DELETE'); END;")
        self.connection.commit()
    def _verify_metadata(self):
        row=self.connection.execute("SELECT * FROM exposure_store_meta WHERE singleton=1").fetchone();fields=("store_schema_version","exposure_schema_version","baseline_tag","baseline_commit","architecture_tag","architecture_commit","production_tag","production_commit","authority");expected=(STORE_SCHEMA_VERSION,EXPOSURE_SCHEMA_VERSION,BASELINE_TAG,BASELINE_COMMIT,ARCHITECTURE_TAG,ARCHITECTURE_COMMIT,PRODUCTION_TAG,PRODUCTION_COMMIT,AUTHORITY)
        if row is None or tuple(row[x] for x in fields)!=expected:raise ExposureIntegrityFailure("EXPOSURE_STORE_METADATA_MISMATCH")
    def _registry(self,snapshot_id,cutoff,asof):
        snapshot=self.ingestion_store._verify_persisted_registry_chain("ENTITY",snapshot_id)
        if parse_utc(snapshot["as_of_timestamp"],"registry.as_of")>parse_utc(cutoff,"cutoff") or parse_utc(cutoff,"cutoff")>parse_utc(asof,"asof"):raise Stage6ExposureError("EXPOSURE_REGISTRY_PIT_INVALID")
        return snapshot
    def _entities(self,snapshot,company_id,asof):
        try:company=resolve_entity(snapshot,company_id,asof)
        except Exception as exc:raise Stage6ExposureError("EXPOSURE_COMPANY_RESOLUTION_FAILED") from exc
        if company["entity_type"]!="COMPANY":raise Stage6ExposureError("EXPOSURE_COMPANY_TYPE_REQUIRED")
        sector_id=company.get("sector_entity_id");subsector_id=company.get("subsector_entity_id")
        if not sector_id:raise Stage6ExposureError("EXPOSURE_COMPANY_SECTOR_REQUIRED")
        try:sector=resolve_entity(snapshot,sector_id,asof)
        except Exception as exc:raise Stage6ExposureError("EXPOSURE_SECTOR_RESOLUTION_FAILED") from exc
        if sector["entity_type"]!="SECTOR":raise Stage6ExposureError("EXPOSURE_SECTOR_TYPE_REQUIRED")
        if subsector_id is not None:
            try:subsector=resolve_entity(snapshot,subsector_id,asof)
            except Exception as exc:raise Stage6ExposureError("EXPOSURE_SUBSECTOR_RESOLUTION_FAILED") from exc
            if subsector["entity_type"]!="SUBSECTOR":raise Stage6ExposureError("EXPOSURE_SUBSECTOR_TYPE_REQUIRED")
        return company,sector_id,subsector_id
    def _evidence(self,ids,cutoff):
        records=[]
        for identity in ids:
            row=self.ingestion_store.connection.execute("SELECT * FROM ingestion_records WHERE record_id=?",(identity,)).fetchone()
            if row is None:raise Stage6ExposureError("EXPOSURE_EVIDENCE_MISSING")
            record=json.loads(row["canonical_json"]);self.ingestion_store._verify_record_semantics(record)
            expected=canonical_hash(without(record,"record_hash"))
            if row["canonical_json"]!=canonical_json(record) or row["record_hash"]!=expected or record["record_hash"]!=expected:raise ExposureIntegrityFailure("EXPOSURE_EVIDENCE_HASH_MISMATCH")
            if record["record_kind"]!="EVIDENCE" or record["retrieval_status"]!="RETRIEVED":raise Stage6ExposureError("EXPOSURE_RETRIEVED_EVIDENCE_REQUIRED")
            if record["authority_level"] not in TRUSTWORTHY:raise Stage6ExposureError("EXPOSURE_EVIDENCE_AUTHORITY_INVALID")
            if parse_utc(record["retrieved_timestamp_utc"],"retrieved")>parse_utc(cutoff,"cutoff"):raise Stage6ExposureError("EXPOSURE_FUTURE_EVIDENCE_PROHIBITED")
            records.append(record)
        return records
    def _relationships(self,company,relationships,asof):
        day=parse_utc(asof,"asof").date()
        for item in relationships:
            try:related=resolve_entity({**self._current_registry},item["related_entity_id"],asof)
            except Exception as exc:raise Stage6ExposureError("EXPOSURE_RELATED_ENTITY_MISSING") from exc
            wanted=REL_MAP.get(item["relationship_type"]);matches=[]
            for rel in company["relationships"]:
                start=date.fromisoformat(rel["effective_from"]);end=date.fromisoformat(rel["effective_to"]) if rel["effective_to"] else None
                if rel["relationship_type"]==wanted and rel["related_entity_id"]==related["entity_id"] and start<=day and (end is None or day<=end):matches.append(rel)
            if len(matches)!=1:raise Stage6ExposureError("EXPOSURE_REGISTRY_RELATIONSHIP_MISSING")
    def append_exposure(self,*,company_entity_id,exposure_version,previous_version_hash,as_of_timestamp,data_cutoff_timestamp,entity_registry_snapshot_id,input_evidence_ids,assertions,relationships):
        if self.ingestion_store.integrity_check().get("result")!="PASS":raise ExposureIntegrityFailure("UPSTREAM_INGESTION_INTEGRITY_FAILED")
        snapshot=self._registry(entity_registry_snapshot_id,data_cutoff_timestamp,as_of_timestamp);self._current_registry=snapshot
        company,sector,subsector=self._entities(snapshot,company_entity_id,as_of_timestamp);evidence=self._evidence(sorted(input_evidence_ids),data_cutoff_timestamp);self._relationships(company,relationships,as_of_timestamp)
        record=build_exposure(company_entity_id=company_entity_id,exposure_version=exposure_version,previous_version_hash=previous_version_hash,sector_entity_id=sector,subsector_entity_id=subsector,as_of_timestamp=as_of_timestamp,data_cutoff_timestamp=data_cutoff_timestamp,entity_registry_snapshot_id=snapshot["registry_snapshot_id"],entity_registry_version=snapshot["registry_version"],entity_registry_hash=snapshot["registry_hash"],input_evidence_ids=input_evidence_ids,assertions=assertions,relationships=relationships);validate_exposure(record)
        exposure_id=record["exposure_id"];series=self.connection.execute("SELECT * FROM exposure_series WHERE exposure_id=?",(exposure_id,)).fetchone();existing=self.connection.execute("SELECT canonical_json FROM exposure_records WHERE exposure_id=? AND exposure_version=?",(exposure_id,exposure_version)).fetchone();deps=[(snapshot["registry_snapshot_id"],snapshot["registry_hash"],"ENTITY_REGISTRY_SNAPSHOT"),*[(x["evidence_id"],x["record_hash"],"EVIDENCE") for x in evidence]]
        if existing is not None:
            stored=[tuple(x) for x in self.connection.execute("SELECT dependency_record_id,dependency_record_hash,dependency_record_type FROM exposure_dependencies WHERE exposure_id=? AND exposure_version=? ORDER BY dependency_record_type,dependency_record_id",(exposure_id,exposure_version))]
            if existing[0]==canonical_json(record) and sorted(deps,key=lambda x:(x[2],x[0]))==stored:return {"status":"IDEMPOTENT_SUCCESS","exposure":record}
            raise ExposureVersionConflict("INCOMPATIBLE_DUPLICATE_EXPOSURE_VERSION")
        prior_row=self.connection.execute("SELECT canonical_json FROM exposure_records WHERE exposure_id=? ORDER BY exposure_version DESC LIMIT 1",(exposure_id,)).fetchone();prior=json.loads(prior_row[0]) if prior_row else None;expected_version=1 if prior is None else prior["exposure_version"]+1;expected_hash=None if prior is None else prior["record_hash"]
        if exposure_version!=expected_version:raise ExposureVersionConflict("EXPOSURE_VERSION_NOT_CONTIGUOUS")
        if previous_version_hash!=expected_hash:raise ExposureVersionConflict("EXPOSURE_PREDECESSOR_MISMATCH")
        try:
            with self.connection:
                if series is None:self.connection.execute("INSERT INTO exposure_series VALUES(?,?)",(exposure_id,company_entity_id))
                elif series["company_entity_id"]!=company_entity_id:raise ExposureIntegrityFailure("EXPOSURE_SERIES_IDENTITY_MISMATCH")
                self.connection.execute("INSERT INTO exposure_records VALUES(?,?,?,?,?,?,?,?)",(exposure_id,exposure_version,previous_version_hash,record["record_hash"],record["as_of_timestamp"],record["data_cutoff_timestamp"],record["entity_registry_snapshot_id"],canonical_json(record)))
                self.connection.executemany("INSERT INTO exposure_dependencies VALUES(?,?,?,?,?)",[(exposure_id,exposure_version,kind,identity,h) for identity,h,kind in deps])
        except sqlite3.IntegrityError as exc:raise ExposureVersionConflict("EXPOSURE_STORE_INSERT_CONFLICT") from exc
        return {"status":"CREATED","exposure":record}
    def integrity_check(self):
        try:
            self._verify_metadata()
            if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():raise ExposureIntegrityFailure("EXPOSURE_SQLITE_INTEGRITY_FAILURE")
            if self.ingestion_store.integrity_check().get("result")!="PASS":raise ExposureIntegrityFailure("UPSTREAM_INGESTION_INTEGRITY_FAILED")
            for table in ("exposure_store_meta","exposure_series","exposure_records","exposure_dependencies"):
                names={x[0] for x in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,))}
                if names!={f"protect_{table}_update",f"protect_{table}_delete"}:raise ExposureIntegrityFailure("EXPOSURE_APPEND_ONLY_TRIGGER_MISSING")
            count=0
            for series in self.connection.execute("SELECT * FROM exposure_series"):
                if series["exposure_id"]!=deterministic_exposure_id(series["company_entity_id"]):raise ExposureIntegrityFailure("EXPOSURE_SERIES_IDENTITY_MISMATCH")
                rows=self.connection.execute("SELECT * FROM exposure_records WHERE exposure_id=? ORDER BY exposure_version",(series["exposure_id"],)).fetchall()
                if not rows or [x["exposure_version"] for x in rows]!=list(range(1,len(rows)+1)):raise ExposureIntegrityFailure("EXPOSURE_VERSION_CHAIN_GAP")
                prior=None
                for row in rows:
                    count+=1;record=json.loads(row["canonical_json"]);validate_exposure(record);expected_prev=None if prior is None else prior["record_hash"]
                    if row["canonical_json"]!=canonical_json(record) or (row["exposure_id"],row["exposure_version"],row["previous_version_hash"],row["record_hash"],row["as_of_timestamp"],row["data_cutoff_timestamp"],row["entity_registry_snapshot_id"])!=(record["exposure_id"],record["exposure_version"],record["previous_version_hash"],record["record_hash"],record["as_of_timestamp"],record["data_cutoff_timestamp"],record["entity_registry_snapshot_id"]):raise ExposureIntegrityFailure("EXPOSURE_TYPED_COLUMN_MISMATCH")
                    if record["previous_version_hash"]!=expected_prev:raise ExposureIntegrityFailure("EXPOSURE_PREDECESSOR_MISMATCH")
                    snapshot=self._registry(record["entity_registry_snapshot_id"],record["data_cutoff_timestamp"],record["as_of_timestamp"]);self._current_registry=snapshot;company,sector,subsector=self._entities(snapshot,record["company_entity_id"],record["as_of_timestamp"])
                    if (record["entity_registry_version"],record["entity_registry_hash"],record["sector_entity_id"],record["subsector_entity_id"])!=(snapshot["registry_version"],snapshot["registry_hash"],sector,subsector):raise ExposureIntegrityFailure("EXPOSURE_REGISTRY_BINDING_MISMATCH")
                    evidence=self._evidence(record["input_evidence_ids"],record["data_cutoff_timestamp"]);self._relationships(company,record["relationships"],record["as_of_timestamp"])
                    replay=build_exposure(company_entity_id=record["company_entity_id"],exposure_version=record["exposure_version"],previous_version_hash=record["previous_version_hash"],sector_entity_id=sector,subsector_entity_id=subsector,as_of_timestamp=record["as_of_timestamp"],data_cutoff_timestamp=record["data_cutoff_timestamp"],entity_registry_snapshot_id=snapshot["registry_snapshot_id"],entity_registry_version=snapshot["registry_version"],entity_registry_hash=snapshot["registry_hash"],input_evidence_ids=record["input_evidence_ids"],assertions=record["assertions"],relationships=record["relationships"])
                    if replay!=record:raise ExposureIntegrityFailure("EXPOSURE_REPLAY_MISMATCH")
                    actual={(x["dependency_record_type"],x["dependency_record_id"]):x["dependency_record_hash"] for x in self.connection.execute("SELECT * FROM exposure_dependencies WHERE exposure_id=? AND exposure_version=?",(record["exposure_id"],record["exposure_version"]))};wanted={("ENTITY_REGISTRY_SNAPSHOT",snapshot["registry_snapshot_id"]):snapshot["registry_hash"],**{("EVIDENCE",x["evidence_id"]):x["record_hash"] for x in evidence}}
                    if actual!=wanted:raise ExposureIntegrityFailure("EXPOSURE_DEPENDENCY_MISMATCH")
                    prior=record
            orphan=self.connection.execute("SELECT COUNT(*) FROM exposure_records r LEFT JOIN exposure_series s ON s.exposure_id=r.exposure_id WHERE s.exposure_id IS NULL").fetchone()[0]
            if orphan:raise ExposureIntegrityFailure("ORPHAN_EXPOSURE_RECORD")
            return {"result":"PASS","records":count,"series":self.connection.execute("SELECT COUNT(*) FROM exposure_series").fetchone()[0],"authority":AUTHORITY}
        except ExposureIntegrityFailure:raise
        except Exception as exc:raise ExposureIntegrityFailure("FULL_EXPOSURE_INTEGRITY_FAILURE") from exc
