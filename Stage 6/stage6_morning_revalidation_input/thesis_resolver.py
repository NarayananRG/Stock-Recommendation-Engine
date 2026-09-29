import json
from stage6_recursive_thesis.current_thesis_resolver import resolve_stage6e
from .errors import Stage6MorningInputError,MorningInputIntegrityFailure
from .policy import SOURCE_TYPES,THESIS_SCHEMA,AUTHORITY

def _integrity(store,code):
 if store is None:raise MorningInputIntegrityFailure(code)
 try:result=store.integrity_check()
 except Exception as exc:raise MorningInputIntegrityFailure(code) from exc
 if result.get("result")!="PASS":raise MorningInputIntegrityFailure(code)
def resolve_thesis(source,record_id,thesis_store,stage6e_store,recursive_store):
 if source not in SOURCE_TYPES:raise Stage6MorningInputError("THESIS_SOURCE_INVALID")
 if not isinstance(record_id,str) or not record_id:raise Stage6MorningInputError("VERSION_RECORD_ID_REQUIRED")
 if source=="STAGE6_6B":
  _integrity(thesis_store,"STAGE6_6B_INTEGRITY_REQUIRED");row=thesis_store.connection.execute("SELECT canonical_json FROM trade_thesis_records WHERE materialization_record_id=?",(record_id,)).fetchone()
  if row is None:raise Stage6MorningInputError("STAGE6_6B_RECORD_NOT_FOUND")
  wrapper=json.loads(row[0]);thesis=wrapper["trade_thesis"]
  if thesis.get("version")!=1:raise MorningInputIntegrityFailure("STAGE6_6B_VERSION_INVALID")
 elif source=="STAGE6_6E":
  try:wrapper,thesis=resolve_stage6e(stage6e_store,record_id)
  except Exception as exc:raise MorningInputIntegrityFailure("STAGE6_6E_INTEGRITY_REQUIRED") from exc
 else:
  _integrity(recursive_store,"STAGE6_6F_INTEGRITY_REQUIRED");row=recursive_store.connection.execute("SELECT canonical_json FROM recursive_thesis_versions WHERE version_record_id=?",(record_id,)).fetchone()
  if row is None:raise Stage6MorningInputError("STAGE6_6F_RECORD_NOT_FOUND")
  wrapper=json.loads(row[0]);thesis=wrapper["trade_thesis"]
  if type(thesis.get("version")) is not int or thesis["version"]<3:raise MorningInputIntegrityFailure("STAGE6_6F_VERSION_INVALID")
 if thesis.get("schema_version")!=THESIS_SCHEMA or thesis.get("authority_mode")!=AUTHORITY:raise MorningInputIntegrityFailure("TRADE_THESIS_IDENTITY_INVALID")
 return wrapper,thesis
