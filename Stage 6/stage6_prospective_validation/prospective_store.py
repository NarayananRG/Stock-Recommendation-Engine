import json,sqlite3
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json,without
from .activation import verify_activation_record
from .control_reader import Stage5DControlReader,parse_utc,payload_sha256
from .stage6_shadow_reader import Stage6ShadowReader
from .errors import ProspectiveConflict,ProspectiveIntegrityFailure,Stage6ProspectiveError
from .policy import *
from .enrollment_builder import build_session,build_submission,build_case,now_utc
from .enrollment_validation import validate_run_eligibility,validate_session,validate_control_case,validate_pairing,validate_case

TABLES=("prospective_store_meta","prospective_protocols","prospective_policies","prospective_contracts","prospective_activations","prospective_sessions","prospective_control_recommendations","prospective_pending_events","prospective_shadow_submissions","prospective_cases","prospective_case_dependencies","prospective_audits")
class ProspectiveValidationStore:
 def __init__(self,database,activation_record):
  self.database=Path(database);self.activation_path=Path(activation_record)
  if not self.activation_path.is_file():raise Stage6ProspectiveError("VERIFIED_ACTIVATION_REQUIRED")
  self.activation=verify_activation_record(self.activation_path);self.protocol,self.protocol_json,self.protocol_hash=load_protocol();self.policy,self.policy_json,self.policy_hash=load_policy();self.contract,self.contract_json,self.contract_hash=load_contract()
  new=not self.database.exists();self.database.parent.mkdir(parents=True,exist_ok=True);self.connection=sqlite3.connect(self.database);self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA foreign_keys=ON")
  if new:self._initialize()
  self._singletons()
 def close(self):self.connection.close()
 def __enter__(self):return self
 def __exit__(self,*_):self.close()
 def _initialize(self):
  self.connection.executescript("""
CREATE TABLE prospective_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema TEXT NOT NULL,processor TEXT NOT NULL,authority TEXT NOT NULL,baseline TEXT NOT NULL,control_commit TEXT NOT NULL);
CREATE TABLE prospective_protocols(protocol_id TEXT PRIMARY KEY,protocol_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE prospective_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE prospective_contracts(contract_id TEXT PRIMARY KEY,contract_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE prospective_activations(activation_id TEXT PRIMARY KEY,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE prospective_sessions(enrollment_id TEXT PRIMARY KEY,run_id TEXT UNIQUE NOT NULL,market_session_date TEXT UNIQUE NOT NULL,session_ordinal INTEGER UNIQUE NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE prospective_control_recommendations(recommendation_id TEXT PRIMARY KEY,payload_sha256 TEXT NOT NULL,canonical_payload_json TEXT NOT NULL,canonical_row_json TEXT NOT NULL);
CREATE TABLE prospective_pending_events(event_id TEXT PRIMARY KEY,recommendation_id TEXT UNIQUE NOT NULL,payload_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL,canonical_row_json TEXT NOT NULL);
CREATE TABLE prospective_shadow_submissions(submission_id TEXT PRIMARY KEY,proposal_id TEXT UNIQUE NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE prospective_cases(case_id TEXT PRIMARY KEY,recommendation_id TEXT UNIQUE NOT NULL,enrollment_id TEXT NOT NULL,state TEXT NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL,FOREIGN KEY(enrollment_id) REFERENCES prospective_sessions);
CREATE TABLE prospective_case_dependencies(case_id TEXT NOT NULL,dependency_ordinal INTEGER NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(case_id,dependency_ordinal),FOREIGN KEY(case_id) REFERENCES prospective_cases);
CREATE TABLE prospective_audits(record_type TEXT NOT NULL,record_id TEXT NOT NULL,canonical_json TEXT NOT NULL,PRIMARY KEY(record_type,record_id));
""")
  self.connection.execute("INSERT INTO prospective_store_meta VALUES(1,?,?,?,?,?)",(STORE_SCHEMA,PROCESSOR,AUTHORITY,BASELINE,CONTROL_COMMIT));self.connection.execute("INSERT INTO prospective_protocols VALUES(?,?,?)",(PROTOCOL_ID,self.protocol_hash,self.protocol_json));self.connection.execute("INSERT INTO prospective_policies VALUES(?,?,?)",(POLICY_ID,self.policy_hash,self.policy_json));self.connection.execute("INSERT INTO prospective_contracts VALUES(?,?,?)",(CONTRACT_VERSION,self.contract_hash,self.contract_json));self.connection.execute("INSERT INTO prospective_activations VALUES(?,?,?)",(self.activation["activation_id"],self.activation["record_hash"],canonical_json(self.activation)))
  for table in TABLES:self.connection.executescript(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;")
  self.connection.commit()
 def _singletons(self):
  expected=(1,STORE_SCHEMA,PROCESSOR,AUTHORITY,BASELINE,CONTROL_COMMIT);meta=self.connection.execute("SELECT * FROM prospective_store_meta").fetchall();p=self.connection.execute("SELECT * FROM prospective_protocols").fetchall();y=self.connection.execute("SELECT * FROM prospective_policies").fetchall();c=self.connection.execute("SELECT * FROM prospective_contracts").fetchall();a=self.connection.execute("SELECT * FROM prospective_activations").fetchall()
  if len(meta)!=1 or tuple(meta[0])!=expected:raise ProspectiveIntegrityFailure("PROSPECTIVE_METADATA_INVALID")
  if len(p)!=1 or tuple(p[0])!=(PROTOCOL_ID,self.protocol_hash,self.protocol_json):raise ProspectiveIntegrityFailure("PROSPECTIVE_PROTOCOL_INVALID")
  if len(y)!=1 or tuple(y[0])!=(POLICY_ID,self.policy_hash,self.policy_json):raise ProspectiveIntegrityFailure("PROSPECTIVE_POLICY_INVALID")
  if len(c)!=1 or tuple(c[0])!=(CONTRACT_VERSION,self.contract_hash,self.contract_json):raise ProspectiveIntegrityFailure("PROSPECTIVE_CONTRACT_INVALID")
  if len(a)!=1 or tuple(a[0])!=(self.activation["activation_id"],self.activation["record_hash"],canonical_json(self.activation)):raise ProspectiveIntegrityFailure("PROSPECTIVE_ACTIVATION_INVALID")
 def enroll_session(self,*,control_database,run_id):
  self._singletons()
  with Stage5DControlReader(control_database) as control:
   run=control.get_run(run_id);validate_run_eligibility(self.activation,run);eligible=control.eligible_runs(self.activation["activation_date_ist"],self.activation["activated_at_utc"]);wanted=[x for x in eligible if x["run_id"]==run_id]
   if len(wanted)!=1:raise Stage6ProspectiveError("CONTROL_RUN_NOT_ELIGIBLE")
   prior=[x["market_session_date"] for x in eligible if x["market_session_date"]<run["market_session_date"]];enrolled=[x[0] for x in self.connection.execute("SELECT market_session_date FROM prospective_sessions ORDER BY market_session_date")]
   old=self.connection.execute("SELECT canonical_json FROM prospective_sessions WHERE run_id=?",(run_id,)).fetchone()
   ordinal=len(prior)+1;record=build_session(self.activation,self.protocol_hash,control.database_id(),run,ordinal);validate_session(record,self.activation,self.protocol_hash,control.database_id(),run,ordinal)
   if old:
    if old[0]==canonical_json(record):return {"status":"IDEMPOTENT_SUCCESS","session":record}
    raise ProspectiveConflict("PROSPECTIVE_SESSION_CONFLICT")
   if enrolled!=prior:raise Stage6ProspectiveError("PROSPECTIVE_SESSION_COMPLETENESS_FAILURE")
   audit={"record_type":SESSION_SCHEMA,"record_id":record["enrollment_id"],"prospective_eligibility":"PASS","outcome_status":"NOT_ATTACHED","authority":AUTHORITY}
   with self.connection:self.connection.execute("INSERT INTO prospective_sessions VALUES(?,?,?,?,?,?)",(record["enrollment_id"],run_id,run["market_session_date"],ordinal,record["record_hash"],canonical_json(record)));self.connection.execute("INSERT INTO prospective_audits VALUES(?,?,?)",(SESSION_SCHEMA,record["enrollment_id"],canonical_json(audit)))
   return {"status":"CREATED","session":record}
 def enroll_case(self,*,control_database,session_enrollment_id,recommendation_id,shadow_database=None,shadow_runtime_root=None,proposal_id=None):
  self._singletons();old=self.connection.execute("SELECT canonical_json FROM prospective_cases WHERE recommendation_id=?",(recommendation_id,)).fetchone()
  if old:
   record=json.loads(old[0]);supplied=all(x is not None for x in (shadow_database,shadow_runtime_root,proposal_id))
   if any(x is not None for x in (shadow_database,shadow_runtime_root,proposal_id)) and not supplied:raise ProspectiveConflict("PROSPECTIVE_CASE_CONFLICT")
   existing=record["shadow_submission_binding"] is not None
   if record["control_session_binding"]["record_id"]!=session_enrollment_id or existing!=supplied:raise ProspectiveConflict("PROSPECTIVE_CASE_CONFLICT")
   if supplied:
    sr=self.connection.execute("SELECT canonical_json FROM prospective_shadow_submissions WHERE submission_id=?",(record["shadow_submission_binding"]["record_id"],)).fetchone();submission=json.loads(sr[0]) if sr else None
    if submission is None or submission["proposal_binding"]["record_id"]!=proposal_id:raise ProspectiveConflict("PROSPECTIVE_CASE_CONFLICT")
   return {"status":"IDEMPOTENT_SUCCESS","case":record}
  srow=self.connection.execute("SELECT canonical_json FROM prospective_sessions WHERE enrollment_id=?",(session_enrollment_id,)).fetchone()
  if srow is None:raise Stage6ProspectiveError("PROSPECTIVE_SESSION_REQUIRED")
  session=json.loads(srow[0])
  with Stage5DControlReader(control_database) as control:
   if control.database_id()!=session["control_database_id"]:raise Stage6ProspectiveError("CONTROL_DATABASE_MISMATCH")
   recommendation=control.get_recommendation(recommendation_id);pending=control.get_pending_event(recommendation_id);validate_control_case(self.activation,session,recommendation,pending)
  supplied=[shadow_database is not None,shadow_runtime_root is not None,proposal_id is not None]
  if any(supplied) and not all(supplied):raise Stage6ProspectiveError("COMPLETE_SHADOW_SUBMISSION_REQUIRED")
  submission=None
  if all(supplied):
   with Stage6ShadowReader(shadow_database,shadow_runtime_root,self.activation) as shadow:proposal=shadow.get_proposal(proposal_id)
   submitted=now_utc();validate_pairing(self.activation,session,recommendation,proposal,submitted);submission=build_submission(self.activation,proposal,submitted)
  record=build_case(self.activation,self.protocol_hash,session,recommendation,pending,submission);validate_case(record,self.activation,self.protocol_hash,session,recommendation,pending,submission)
  audit={"record_type":CASE_SCHEMA,"record_id":record["case_id"],"case_state":record["case_state"],"outcome_status":"NOT_ATTACHED","authority":AUTHORITY}
  with self.connection:
   self.connection.execute("INSERT INTO prospective_control_recommendations VALUES(?,?,?,?)",(recommendation_id,recommendation["payload_sha256"],recommendation["canonical_payload_json"],canonical_json(recommendation)));self.connection.execute("INSERT INTO prospective_pending_events VALUES(?,?,?,?,?)",(pending["event_id"],recommendation_id,pending["payload_sha256"],pending["payload_json"],canonical_json(pending)))
   if submission:self.connection.execute("INSERT INTO prospective_shadow_submissions VALUES(?,?,?,?)",(submission["submission_id"],proposal_id,submission["record_hash"],canonical_json(submission)))
   self.connection.execute("INSERT INTO prospective_cases VALUES(?,?,?,?,?,?)",(record["case_id"],recommendation_id,session_enrollment_id,record["case_state"],record["record_hash"],canonical_json(record)));self.connection.executemany("INSERT INTO prospective_case_dependencies VALUES(?,?,?,?,?)",[(record["case_id"],i,x["record_type"],x["record_id"],x["record_hash"]) for i,x in enumerate(record["direct_dependencies"])]);self.connection.execute("INSERT INTO prospective_audits VALUES(?,?,?)",(CASE_SCHEMA,record["case_id"],canonical_json(audit)))
  return {"status":"CREATED","case":record,"shadow_submission":submission}
 def integrity_check(self):
  self._singletons()
  if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():raise ProspectiveIntegrityFailure("PROSPECTIVE_SQLITE_INVALID")
  for table in TABLES:
   names={x[0] for x in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,))}
   if names!={f"protect_{table}_update",f"protect_{table}_delete"}:raise ProspectiveIntegrityFailure("PROSPECTIVE_TRIGGER_MISSING")
  previous=None
  for row in self.connection.execute("SELECT * FROM prospective_sessions ORDER BY session_ordinal"):
   record=json.loads(row["canonical_json"])
   if (row["enrollment_id"],row["run_id"],row["market_session_date"],row["session_ordinal"],row["record_hash"])!=(record["enrollment_id"],record["stage5d5_run_id"],record["market_session_date"],record["session_ordinal_since_activation"],record["record_hash"]) or record["record_hash"]!=canonical_hash(without(record,"record_hash")) or row["session_ordinal"]!=(previous or 0)+1:raise ProspectiveIntegrityFailure("PROSPECTIVE_SESSION_INVALID")
   previous=row["session_ordinal"]
  for row in self.connection.execute("SELECT * FROM prospective_cases"):
   record=json.loads(row["canonical_json"]);s=json.loads(self.connection.execute("SELECT canonical_json FROM prospective_sessions WHERE enrollment_id=?",(row["enrollment_id"],)).fetchone()[0]);recrow=self.connection.execute("SELECT canonical_row_json FROM prospective_control_recommendations WHERE recommendation_id=?",(row["recommendation_id"],)).fetchone();evrow=self.connection.execute("SELECT canonical_row_json FROM prospective_pending_events WHERE recommendation_id=?",(row["recommendation_id"],)).fetchone()
   if recrow is None or evrow is None:raise ProspectiveIntegrityFailure("PROSPECTIVE_CONTROL_COPY_MISSING")
   rec=json.loads(recrow[0]);event=json.loads(evrow[0]);sub=None
   if record["shadow_submission_binding"] is not None:
    sr=self.connection.execute("SELECT canonical_json FROM prospective_shadow_submissions WHERE submission_id=?",(record["shadow_submission_binding"]["record_id"],)).fetchone()
    if sr is None:raise ProspectiveIntegrityFailure("PROSPECTIVE_SUBMISSION_MISSING")
    sub=json.loads(sr[0])
   validate_case(record,self.activation,self.protocol_hash,s,rec,event,sub);deps=[tuple(x) for x in self.connection.execute("SELECT record_type,record_id,record_hash FROM prospective_case_dependencies WHERE case_id=? ORDER BY dependency_ordinal",(record["case_id"],))]
   if deps!=[(x["record_type"],x["record_id"],x["record_hash"]) for x in record["direct_dependencies"]] or row["state"]!=record["case_state"] or row["record_hash"]!=record["record_hash"]:raise ProspectiveIntegrityFailure("PROSPECTIVE_CASE_CHILD_INVALID")
  for row in self.connection.execute("SELECT * FROM prospective_control_recommendations"):
   value=json.loads(row["canonical_row_json"])
   if canonical_json(value)!=row["canonical_row_json"] or value.get("recommendation_id")!=row["recommendation_id"] or value.get("payload_sha256")!=row["payload_sha256"] or value.get("canonical_payload_json")!=row["canonical_payload_json"] or payload_sha256(row["canonical_payload_json"])!=row["payload_sha256"]:raise ProspectiveIntegrityFailure("PROSPECTIVE_RECOMMENDATION_COPY_INVALID")
  for row in self.connection.execute("SELECT * FROM prospective_pending_events"):
   value=json.loads(row["canonical_row_json"])
   if canonical_json(value)!=row["canonical_row_json"] or value.get("event_id")!=row["event_id"] or value.get("recommendation_id")!=row["recommendation_id"] or value.get("payload_sha256")!=row["payload_sha256"] or value.get("payload_json")!=row["payload_json"] or payload_sha256(row["payload_json"])!=row["payload_sha256"]:raise ProspectiveIntegrityFailure("PROSPECTIVE_PENDING_COPY_INVALID")
  for row in self.connection.execute("SELECT * FROM prospective_shadow_submissions"):
   value=json.loads(row["canonical_json"])
   if canonical_json(value)!=row["canonical_json"] or (value.get("submission_id"),value.get("proposal_binding",{}).get("record_id"),value.get("record_hash"))!=(row["submission_id"],row["proposal_id"],row["record_hash"]) or value.get("record_hash")!=canonical_hash(without(value,"record_hash")):raise ProspectiveIntegrityFailure("PROSPECTIVE_SUBMISSION_INVALID")
  for row in self.connection.execute("SELECT * FROM prospective_audits"):
   if canonical_json(json.loads(row["canonical_json"]))!=row["canonical_json"]:raise ProspectiveIntegrityFailure("PROSPECTIVE_AUDIT_INVALID")
  return {"result":"PASS","sessions":self.connection.execute("SELECT count(*) FROM prospective_sessions").fetchone()[0],"cases":self.connection.execute("SELECT count(*) FROM prospective_cases").fetchone()[0],"authority":AUTHORITY}
