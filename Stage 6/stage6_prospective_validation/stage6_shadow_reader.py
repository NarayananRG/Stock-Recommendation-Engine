import json,sqlite3
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,without
from .errors import ProspectiveIntegrityFailure,Stage6ProspectiveError
from .activation import verify_activation_record
from .policy import *

ORIGIN_SCHEMA="STAGE6_7B_PROSPECTIVE_RUNTIME_ORIGIN_V1"
def create_runtime_origin_marker(runtime_root,database,activation_record):
 root=Path(runtime_root).resolve();db=Path(database).resolve();activation=verify_activation_record(activation_record)
 if not db.is_file() or root not in db.parents:raise Stage6ProspectiveError("SHADOW_RUNTIME_DATABASE_REQUIRED")
 marker=root/"runtime_origin.json"
 if marker.exists():raise Stage6ProspectiveError("SHADOW_RUNTIME_ORIGIN_ALREADY_EXISTS")
 value={"schema_version":ORIGIN_SCHEMA,"origin":"REAL_PROSPECTIVE_RUNTIME","activation_id":activation["activation_id"],"activation_record_hash":activation["record_hash"],"record_hash":""};value["record_hash"]=canonical_hash(without(value,"record_hash"));marker.write_text(json.dumps(value,sort_keys=True,indent=2)+"\n",encoding="utf-8");return value
class Stage6ShadowReader:
 def __init__(self,database,runtime_root,activation=None):
  self.database=Path(database).resolve();self.runtime_root=Path(runtime_root).resolve()
  if not self.database.is_file() or self.runtime_root not in self.database.parents:raise Stage6ProspectiveError("SHADOW_RUNTIME_DATABASE_REQUIRED")
  marker=self.runtime_root/"runtime_origin.json"
  if not marker.is_file():raise Stage6ProspectiveError("SHADOW_RUNTIME_ORIGIN_REQUIRED")
  origin=json.loads(marker.read_text(encoding="utf-8"))
  bound=(origin.get("activation_id"),origin.get("activation_record_hash"))
  if origin.get("schema_version")!=ORIGIN_SCHEMA or origin.get("origin")!="REAL_PROSPECTIVE_RUNTIME" or origin.get("record_hash")!=canonical_hash(without(origin,"record_hash")) or activation is None or bound!=(activation.get("activation_id"),activation.get("record_hash")):raise ProspectiveIntegrityFailure("SHADOW_RUNTIME_ORIGIN_INVALID")
  self.connection=sqlite3.connect(f"file:{self.database.as_posix()}?mode=ro",uri=True);self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA query_only=ON");self.verify_integrity()
 def close(self):self.connection.close()
 def __enter__(self):return self
 def __exit__(self,*_):self.close()
 def verify_integrity(self):
  if self.connection.execute("PRAGMA query_only").fetchone()[0]!=1 or self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():raise ProspectiveIntegrityFailure("SHADOW_SQLITE_INVALID")
  meta=self.connection.execute("SELECT * FROM morning_revalidation_proposal_store_meta").fetchall();p=self.connection.execute("SELECT * FROM morning_revalidation_proposal_policies").fetchall();c=self.connection.execute("SELECT * FROM morning_revalidation_proposal_contracts").fetchall();m=self.connection.execute("SELECT * FROM morning_revalidation_code_manifests").fetchall()
  if len(meta)!=1 or meta[0][1]!="STAGE6_7B_MORNING_REVALIDATION_PROPOSAL_STORE_V1" or len(p)!=1 or (p[0][0],p[0][1])!=(SHADOW_POLICY,SHADOW_POLICY_HASH) or len(c)!=1 or (c[0][0],c[0][1])!=(SHADOW_CONTRACT,SHADOW_CONTRACT_HASH) or len(m)!=1 or m[0][1]!=SHADOW_CODE_HASH:raise ProspectiveIntegrityFailure("SHADOW_STORE_IDENTITY_INVALID")
  return {"result":"PASS","query_only":True}
 def get_proposal(self,proposal_id):
  if not isinstance(proposal_id,str) or not proposal_id:raise Stage6ProspectiveError("SHADOW_PROPOSAL_ID_REQUIRED")
  row=self.connection.execute("SELECT canonical_json FROM morning_revalidation_proposals WHERE proposal_id=?",(proposal_id,)).fetchone()
  if row is None:raise Stage6ProspectiveError("SHADOW_PROPOSAL_NOT_FOUND")
  value=json.loads(row[0])
  required=(value.get("schema_version")==SHADOW_SCHEMA and value.get("policy_id")==SHADOW_POLICY and value.get("policy_hash")==SHADOW_POLICY_HASH and value.get("contract_version")==SHADOW_CONTRACT and value.get("contract_hash")==SHADOW_CONTRACT_HASH and value.get("decision_engine_version")==SHADOW_ENGINE and value.get("decision_code_hash")==SHADOW_CODE_HASH and value.get("authority")==AUTHORITY and value.get("trading_authority") is False and value.get("execution_status")=="NOT_AUTHORIZED" and value.get("stage5d_mutation_status")=="PROHIBITED")
  if not required or value.get("record_hash")!=canonical_hash(without(value,"record_hash")):raise ProspectiveIntegrityFailure("SHADOW_PROPOSAL_INVALID")
  return value
