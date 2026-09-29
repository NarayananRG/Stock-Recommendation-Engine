import json,sqlite3
from pathlib import Path
from stage6_ingestion.canonical import canonical_json
from stage6_trade_thesis.trade_thesis_validation import validate_trade_thesis
from stage6_thesis_review_input.review_input_validation import validate_review_snapshot
from .errors import Stage6ThesisReviewAssessmentError,ThesisReviewAssessmentConflict,ThesisReviewAssessmentIntegrityFailure
from .policy import *
from .review_assessment_builder import build_assessment
from .review_assessment_validation import validate_assessment,validate_structured
TABLES=("thesis_review_assessment_store_meta","thesis_review_assessment_policies","thesis_review_assessment_contracts","thesis_review_assessment_records","thesis_review_assessment_assertions","thesis_review_invalidation_assessments","thesis_review_assessment_bindings","thesis_review_assessment_dependencies")
class ThesisReviewAssessmentStore:
 def __init__(self,database:Path,review_store,thesis_store):
  self.database=Path(database);self.database.parent.mkdir(parents=True,exist_ok=True);self.review_store=review_store;self.thesis_store=thesis_store;self.policy,self.policy_json,self.policy_hash=load_policy();self.contract,self.contract_json,self.contract_hash=load_contract();new=not self.database.exists();self.connection=sqlite3.connect(self.database);self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA foreign_keys=ON")
  if new:self._init()
  self._singletons()
 def __enter__(self):return self
 def __exit__(self,*_):self.close()
 def close(self):self.connection.close()
 def _init(self):
  self.connection.executescript("""CREATE TABLE thesis_review_assessment_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT NOT NULL,baseline_commit TEXT NOT NULL,processor_version TEXT NOT NULL,decision_semantics_version TEXT NOT NULL,authority TEXT NOT NULL);CREATE TABLE thesis_review_assessment_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);CREATE TABLE thesis_review_assessment_contracts(contract_version TEXT PRIMARY KEY,contract_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);CREATE TABLE thesis_review_assessment_records(assessment_id TEXT PRIMARY KEY,logical_review_key TEXT UNIQUE NOT NULL,thesis_id TEXT NOT NULL,review_snapshot_id TEXT UNIQUE NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);CREATE TABLE thesis_review_assessment_assertions(assessment_id TEXT NOT NULL,assertion_id TEXT NOT NULL,ordinal INTEGER NOT NULL,canonical_json TEXT NOT NULL,PRIMARY KEY(assessment_id,assertion_id),UNIQUE(assessment_id,ordinal),FOREIGN KEY(assessment_id) REFERENCES thesis_review_assessment_records);CREATE TABLE thesis_review_invalidation_assessments(assessment_id TEXT NOT NULL,condition_index INTEGER NOT NULL,canonical_json TEXT NOT NULL,PRIMARY KEY(assessment_id,condition_index),FOREIGN KEY(assessment_id) REFERENCES thesis_review_assessment_records);CREATE TABLE thesis_review_assessment_bindings(assessment_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(assessment_id,record_type,record_id),FOREIGN KEY(assessment_id) REFERENCES thesis_review_assessment_records);CREATE TABLE thesis_review_assessment_dependencies(assessment_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(assessment_id,record_type,record_id),FOREIGN KEY(assessment_id) REFERENCES thesis_review_assessment_records);""")
  self.connection.execute("INSERT INTO thesis_review_assessment_store_meta VALUES(1,?,?,?,?,?)",(STORE_SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,DECISION_SEMANTICS_VERSION,AUTHORITY));self.connection.execute("INSERT INTO thesis_review_assessment_policies VALUES(?,?,?)",(POLICY_ID,self.policy_hash,self.policy_json));self.connection.execute("INSERT INTO thesis_review_assessment_contracts VALUES(?,?,?)",(CONTRACT_VERSION,self.contract_hash,self.contract_json))
  for t in TABLES:self.connection.executescript(f"CREATE TRIGGER protect_{t}_update BEFORE UPDATE ON {t} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;CREATE TRIGGER protect_{t}_delete BEFORE DELETE ON {t} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;")
  self.connection.commit()
 def _singletons(self):
  m=self.connection.execute("SELECT * FROM thesis_review_assessment_store_meta").fetchall();p=self.connection.execute("SELECT * FROM thesis_review_assessment_policies").fetchall();c=self.connection.execute("SELECT * FROM thesis_review_assessment_contracts").fetchall()
  if len(m)!=1 or tuple(m[0])!=(1,STORE_SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,DECISION_SEMANTICS_VERSION,AUTHORITY):raise ThesisReviewAssessmentIntegrityFailure("THESIS_REVIEW_ASSESSMENT_METADATA_MISMATCH")
  if len(p)!=1 or tuple(p[0])!=(POLICY_ID,self.policy_hash,self.policy_json):raise ThesisReviewAssessmentIntegrityFailure("THESIS_REVIEW_ASSESSMENT_POLICY_MISMATCH")
  if len(c)!=1 or tuple(c[0])!=(CONTRACT_VERSION,self.contract_hash,self.contract_json):raise ThesisReviewAssessmentIntegrityFailure("THESIS_REVIEW_ASSESSMENT_CONTRACT_MISMATCH")
 def _integrity(self,store,code):
  try:r=store.integrity_check()
  except Exception as exc:raise ThesisReviewAssessmentIntegrityFailure(code) from exc
  if r.get("result")!="PASS":raise ThesisReviewAssessmentIntegrityFailure(code)
 def _load(self,store,table,column,identity,code):
  self._integrity(store,code+"_INTEGRITY_REQUIRED");row=store.connection.execute(f"SELECT canonical_json FROM {table} WHERE {column}=?",(identity,)).fetchone()
  if row is None:raise Stage6ThesisReviewAssessmentError(code+"_NOT_FOUND")
  return json.loads(row[0])
 def _chain(self,review_snapshot_id):
  snapshot=self._load(self.review_store,"thesis_review_input_records","review_snapshot_id",review_snapshot_id,"REVIEW_SNAPSHOT");validate_review_snapshot(snapshot);wrapper=self._load(self.thesis_store,"trade_thesis_records","thesis_id",snapshot["thesis_id"],"PREVIOUS_THESIS");thesis=wrapper["trade_thesis"];validate_trade_thesis(thesis)
  actual=(snapshot["thesis_id"],snapshot["thesis_version"],snapshot["previous_thesis_binding"]["record_id"],snapshot["previous_thesis_binding"]["record_hash"],snapshot["recommendation_id"],snapshot["ticker"],snapshot["prior_decision_cutoff"]);wanted=(thesis["thesis_id"],thesis["version"],thesis["thesis_id"],thesis["record_hash"],thesis["recommendation_id"],thesis["ticker"],thesis["decision_cutoff"])
  if actual!=wanted or thesis["version"]!=1:raise ThesisReviewAssessmentIntegrityFailure("THESIS_REVIEW_CHAIN_MISMATCH")
  return thesis,snapshot
 def assess(self,*,review_snapshot_id,invalidation_assessments,change_assertions):
  self._singletons();thesis,snapshot=self._chain(review_snapshot_id);validate_structured(thesis,snapshot,invalidation_assessments,change_assertions);record=build_assessment(thesis=thesis,snapshot=snapshot,invalidation_assessments=invalidation_assessments,change_assertions=change_assertions,policy_hash=self.policy_hash,contract_hash=self.contract_hash);validate_assessment(record,thesis,snapshot);text=canonical_json(record);logical=canonical_json({"thesis_id":thesis["thesis_id"],"review_snapshot_id":review_snapshot_id});old=self.connection.execute("SELECT canonical_json FROM thesis_review_assessment_records WHERE logical_review_key=?",(logical,)).fetchone()
  if old:
   if old[0]==text:return {"status":"IDEMPOTENT_SUCCESS","review_assessment":record}
   raise ThesisReviewAssessmentConflict("THESIS_REVIEW_ASSESSMENT_CONFLICT")
  bindings=[(TRADE_THESIS_SCHEMA,thesis["thesis_id"],thesis["record_hash"]),(SNAPSHOT_SCHEMA,snapshot["review_snapshot_id"],snapshot["record_hash"])];deps=[*bindings,("STAGE6_6D_POLICY",POLICY_ID,self.policy_hash),("STAGE6_6D_ASSESSMENT_CONTRACT",CONTRACT_VERSION,self.contract_hash)]
  with self.connection:
   self.connection.execute("INSERT INTO thesis_review_assessment_records VALUES(?,?,?,?,?,?)",(record["assessment_id"],logical,record["thesis_id"],review_snapshot_id,record["record_hash"],text));self.connection.executemany("INSERT INTO thesis_review_assessment_assertions VALUES(?,?,?,?)",[(record["assessment_id"],x["assertion_id"],i,canonical_json(x)) for i,x in enumerate(record["change_assertions"])]);self.connection.executemany("INSERT INTO thesis_review_invalidation_assessments VALUES(?,?,?)",[(record["assessment_id"],x["condition_index"],canonical_json(x)) for x in record["invalidation_assessments"]]);self.connection.executemany("INSERT INTO thesis_review_assessment_bindings VALUES(?,?,?,?)",[(record["assessment_id"],*x) for x in bindings]);self.connection.executemany("INSERT INTO thesis_review_assessment_dependencies VALUES(?,?,?,?)",[(record["assessment_id"],*x) for x in deps])
  return {"status":"CREATED","review_assessment":record}
 def integrity_check(self):
  self._singletons()
  if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():raise ThesisReviewAssessmentIntegrityFailure("THESIS_REVIEW_ASSESSMENT_SQLITE_INTEGRITY_FAILED")
  for t in TABLES:
   if {x[0] for x in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(t,))}!={f"protect_{t}_update",f"protect_{t}_delete"}:raise ThesisReviewAssessmentIntegrityFailure("THESIS_REVIEW_ASSESSMENT_TRIGGER_MISSING")
  count=0
  for row in self.connection.execute("SELECT * FROM thesis_review_assessment_records"):
   count+=1;r=json.loads(row["canonical_json"]);thesis,snapshot=self._chain(row["review_snapshot_id"]);validate_assessment(r,thesis,snapshot);rebuilt=build_assessment(thesis=thesis,snapshot=snapshot,invalidation_assessments=r["invalidation_assessments"],change_assertions=r["change_assertions"],policy_hash=self.policy_hash,contract_hash=self.contract_hash)
   if rebuilt!=r or row["canonical_json"]!=canonical_json(r) or tuple(row[k] for k in ("assessment_id","thesis_id","review_snapshot_id","record_hash"))!=(r["assessment_id"],r["thesis_id"],r["review_snapshot_binding"]["record_id"],r["record_hash"]):raise ThesisReviewAssessmentIntegrityFailure("THESIS_REVIEW_ASSESSMENT_REPLAY_MISMATCH")
   assertions=[json.loads(x[0]) for x in self.connection.execute("SELECT canonical_json FROM thesis_review_assessment_assertions WHERE assessment_id=? ORDER BY ordinal",(r["assessment_id"],))];invalidations=[json.loads(x[0]) for x in self.connection.execute("SELECT canonical_json FROM thesis_review_invalidation_assessments WHERE assessment_id=? ORDER BY condition_index",(r["assessment_id"],))]
   if assertions!=r["change_assertions"] or invalidations!=r["invalidation_assessments"]:raise ThesisReviewAssessmentIntegrityFailure("THESIS_REVIEW_ASSESSMENT_CHILD_REPLAY_MISMATCH")
   bindings=[(x["record_type"],x["record_id"],x["record_hash"]) for x in (r["previous_thesis_binding"],r["review_snapshot_binding"])];actual_b=sorted(tuple(x) for x in self.connection.execute("SELECT record_type,record_id,record_hash FROM thesis_review_assessment_bindings WHERE assessment_id=?",(r["assessment_id"],)));expected_d=sorted([*bindings,("STAGE6_6D_POLICY",POLICY_ID,self.policy_hash),("STAGE6_6D_ASSESSMENT_CONTRACT",CONTRACT_VERSION,self.contract_hash)]);actual_d=sorted(tuple(x) for x in self.connection.execute("SELECT record_type,record_id,record_hash FROM thesis_review_assessment_dependencies WHERE assessment_id=?",(r["assessment_id"],)));
   if actual_b!=sorted(bindings) or actual_d!=expected_d:raise ThesisReviewAssessmentIntegrityFailure("THESIS_REVIEW_ASSESSMENT_DEPENDENCY_MISMATCH")
  return {"result":"PASS","review_assessments":count,"authority":AUTHORITY}
 def update_record(self,*_,**__):raise Stage6ThesisReviewAssessmentError("IMMUTABLE_RECORD_UPDATE_PROHIBITED")
