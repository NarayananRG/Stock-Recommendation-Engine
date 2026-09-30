import hashlib,json,sqlite3
from datetime import date,datetime
from pathlib import Path
from .errors import ProspectiveIntegrityFailure,Stage6ProspectiveError
from .policy import CONTROL_SCHEMA

RUN_FIELDS=("run_id","market_session_date","run_started_utc","run_completed_utc","data_provider","market_data_hash","candidate_input_hash","candidate_count","stage4a3_snapshot_id","allocation_run_id","management_session_run_id","recommendation_count","news_status")
def canonical_json(value):return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def payload_sha256(value):return hashlib.sha256(value.encode("utf-8")).hexdigest()
def parse_utc(value):
 if not isinstance(value,str) or not value.endswith("Z"):raise ProspectiveIntegrityFailure("CONTROL_TIMESTAMP_INVALID")
 try:return datetime.fromisoformat(value[:-1]+"+00:00")
 except ValueError as exc:raise ProspectiveIntegrityFailure("CONTROL_TIMESTAMP_INVALID") from exc
class Stage5DControlReader:
 def __init__(self,database):
  self.database=Path(database).resolve()
  if not self.database.is_file():raise Stage6ProspectiveError("CONTROL_DATABASE_REQUIRED")
  self.connection=sqlite3.connect(f"file:{self.database.as_posix()}?mode=ro",uri=True);self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA query_only=ON")
  self.verify_integrity()
 def close(self):self.connection.close()
 def __enter__(self):return self
 def __exit__(self,*_):self.close()
 def _tables(self):return {x[0] for x in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 def verify_integrity(self):
  if self.connection.execute("PRAGMA query_only").fetchone()[0]!=1:raise ProspectiveIntegrityFailure("CONTROL_NOT_QUERY_ONLY")
  if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():raise ProspectiveIntegrityFailure("CONTROL_SQLITE_INVALID")
  required={"ledger_meta","stage5d5_meta","stage5d5_live_runs","allocation_runs","recommendations","recommendation_events"}
  if not required<=self._tables():raise ProspectiveIntegrityFailure("CONTROL_SCHEMA_INCOMPLETE")
  meta=self.connection.execute("SELECT schema_version,database_id FROM ledger_meta WHERE singleton=1").fetchall();marker=self.connection.execute("SELECT schema_version FROM stage5d5_meta WHERE singleton=1").fetchall()
  if len(meta)!=1 or not meta[0][1] or len(marker)!=1 or marker[0][0]!=CONTROL_SCHEMA:raise ProspectiveIntegrityFailure("CONTROL_METADATA_INVALID")
  previous=None;seen=set()
  for row in self.connection.execute("SELECT * FROM stage5d5_live_runs ORDER BY market_session_date"):
   payload=self._canonical(row["canonical_payload_json"],row["payload_sha256"],"CONTROL_RUN")
   if any(payload.get(k)!=row[k] for k in RUN_FIELDS):raise ProspectiveIntegrityFailure("CONTROL_RUN_TYPED_BINDING_INVALID")
   session=row["market_session_date"]
   try:valid=date.fromisoformat(session).isoformat()==session
   except ValueError:valid=False
   if not valid or session in seen or (previous and session<=previous):raise ProspectiveIntegrityFailure("CONTROL_SESSION_ORDER_INVALID")
   if type(row["candidate_count"]) is not int or type(row["recommendation_count"]) is not int or row["candidate_count"]<0 or row["recommendation_count"]<0:raise ProspectiveIntegrityFailure("CONTROL_RUN_COUNT_INVALID")
   parse_utc(row["run_started_utc"]);parse_utc(row["run_completed_utc"]);seen.add(session);previous=session
  for row in self.connection.execute("SELECT * FROM recommendations"):
   payload=self._canonical(row["canonical_payload_json"],row["payload_sha256"],"CONTROL_RECOMMENDATION")
   for key in ("recommendation_id","allocation_run_id","signal_id","ticker","signal_date","decision_date","portfolio_action_status","recommended_quantity","selected_horizon"):
    if str(payload.get(key))!=str(row[key]):raise ProspectiveIntegrityFailure("CONTROL_RECOMMENDATION_TYPED_BINDING_INVALID")
   parse_utc(row["persisted_at_utc"])
  last={}
  for row in self.connection.execute("SELECT * FROM recommendation_events ORDER BY recommendation_id,event_sequence"):
   payload=self._canonical(row["payload_json"],row["payload_sha256"],"CONTROL_EVENT")
   if any(str(payload.get(k))!=str(row[k]) for k in ("recommendation_id","event_type","effective_date")):raise ProspectiveIntegrityFailure("CONTROL_EVENT_TYPED_BINDING_INVALID")
   if row["event_sequence"]<=last.get(row["recommendation_id"],0):raise ProspectiveIntegrityFailure("CONTROL_EVENT_SEQUENCE_INVALID")
   parse_utc(row["recorded_at_utc"]);last[row["recommendation_id"]]=row["event_sequence"]
  return {"result":"PASS","database_id":meta[0][1],"query_only":True}
 def _canonical(self,text,digest,code):
  try:value=json.loads(text)
  except Exception as exc:raise ProspectiveIntegrityFailure(code+"_JSON_INVALID") from exc
  if not isinstance(value,dict) or canonical_json(value)!=text or payload_sha256(text)!=digest:raise ProspectiveIntegrityFailure(code+"_HASH_INVALID")
  return value
 def database_id(self):return self.connection.execute("SELECT database_id FROM ledger_meta WHERE singleton=1").fetchone()[0]
 def get_run(self,run_id):
  if not isinstance(run_id,str) or not run_id:raise Stage6ProspectiveError("CONTROL_RUN_ID_REQUIRED")
  row=self.connection.execute("SELECT * FROM stage5d5_live_runs WHERE run_id=?",(run_id,)).fetchone()
  if row is None:raise Stage6ProspectiveError("CONTROL_RUN_NOT_FOUND")
  self.verify_integrity();return dict(row)
 def eligible_runs(self,activation_date_ist,activated_at_utc):
  start=parse_utc(activated_at_utc);return [dict(x) for x in self.connection.execute("SELECT * FROM stage5d5_live_runs ORDER BY market_session_date") if x["market_session_date"]>activation_date_ist and parse_utc(x["run_started_utc"])>start and parse_utc(x["run_completed_utc"])>=parse_utc(x["run_started_utc"])]
 def get_recommendation(self,recommendation_id):
  if not isinstance(recommendation_id,str) or not recommendation_id:raise Stage6ProspectiveError("CONTROL_RECOMMENDATION_ID_REQUIRED")
  row=self.connection.execute("SELECT * FROM recommendations WHERE recommendation_id=?",(recommendation_id,)).fetchone()
  if row is None:raise Stage6ProspectiveError("CONTROL_RECOMMENDATION_NOT_FOUND")
  self.verify_integrity();return dict(row)
 def get_pending_event(self,recommendation_id):
  rows=self.connection.execute("SELECT * FROM recommendation_events WHERE recommendation_id=? AND event_type='PENDING_ENTRY' ORDER BY event_sequence",(recommendation_id,)).fetchall()
  if len(rows)!=1:raise Stage6ProspectiveError("CONTROL_PENDING_EVENT_REQUIRED")
  self.verify_integrity();return dict(rows[0])
