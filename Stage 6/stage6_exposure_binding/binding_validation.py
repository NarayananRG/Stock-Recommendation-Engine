"""Pure runtime validation for Stage 6.3B binding records."""
from __future__ import annotations
import re
from datetime import date
from stage6_ingestion.canonical import canonical_hash,parse_utc,utc_timestamp,without
from .binding_builder import BINDING_SCHEMA_VERSION,deterministic_binding_id
from .errors import BindingIntegrityFailure,Stage6BindingError
from .policy import AUTHORITY,CHANNELS,POLICY_ID,PROCESSOR_VERSION

HASH=re.compile(r"^[a-f0-9]{64}$")
ROOT={"schema_version","binding_id","record_hash","event_id","event_version","event_hash","event_type","event_status","exposure_id","exposure_version","exposure_hash","company_entity_id","sector_entity_id","subsector_entity_id","binding_channel","binding_basis","selected_assertions","supporting_evidence_ids","binding_cutoff_timestamp","entity_registry_snapshot_id","entity_registry_version","entity_registry_hash","semantic_compatibility_status","directional_effect_status","causal_effect_status","policy_id","policy_hash","processor_version","authority"}
REF={"assertion_hash","exposure_type","value_type","evidence_ids"}

def _ids(value,field,nonempty=True):
    if not isinstance(value,list) or (nonempty and not value) or any(not isinstance(x,str) or not x for x in value) or value!=sorted(value) or len(value)!=len(set(value)):raise Stage6BindingError("BINDING_IDS_INVALID:"+field)
    return value

def validate_binding(record:dict,*,event:dict|None=None,exposure:dict|None=None,expected_policy_hash:str|None=None)->dict:
    if not isinstance(record,dict) or set(record)!=ROOT:raise Stage6BindingError("BINDING_FIELDS_INVALID")
    if record["schema_version"]!=BINDING_SCHEMA_VERSION:raise Stage6BindingError("BINDING_SCHEMA_INVALID")
    for f in ("record_hash","event_hash","exposure_hash","entity_registry_hash","policy_hash"):
        if not isinstance(record[f],str) or not HASH.fullmatch(record[f]):raise Stage6BindingError("BINDING_HASH_INVALID:"+f)
    if any(type(record[x]) is not int or record[x]<1 for x in ("event_version","exposure_version","entity_registry_version")):raise Stage6BindingError("BINDING_VERSION_INVALID")
    if record["event_status"]!="CANDIDATE":raise Stage6BindingError("BINDING_EVENT_STATUS_UNSUPPORTED")
    if record["binding_channel"] not in CHANNELS:raise Stage6BindingError("BINDING_CHANNEL_INVALID")
    constants=(record["binding_basis"],record["semantic_compatibility_status"],record["directional_effect_status"],record["causal_effect_status"],record["policy_id"],record["processor_version"],record["authority"])
    if constants!=("EXPLICIT_ASSERTION_SELECTION","NOT_EVALUATED","NOT_EVALUATED","NOT_EVALUATED",POLICY_ID,PROCESSOR_VERSION,AUTHORITY):raise Stage6BindingError("BINDING_SAFETY_CONSTANT_INVALID")
    cutoff=utc_timestamp(record["binding_cutoff_timestamp"],"binding_cutoff_timestamp")
    if cutoff!=record["binding_cutoff_timestamp"]:raise Stage6BindingError("BINDING_CUTOFF_NONCANONICAL")
    refs=record["selected_assertions"]
    if not isinstance(refs,list) or not refs or refs!=sorted(refs,key=lambda x:x.get("assertion_hash","")):raise Stage6BindingError("BINDING_ASSERTION_ORDER_INVALID")
    hashes=[];evidence=set()
    for ref in refs:
        if not isinstance(ref,dict) or set(ref)!=REF or not HASH.fullmatch(str(ref["assertion_hash"])) or ref["value_type"] not in {"QUANTITATIVE","QUALITATIVE"}:raise Stage6BindingError("BINDING_ASSERTION_REFERENCE_INVALID")
        hashes.append(ref["assertion_hash"]);evidence.update(_ids(ref["evidence_ids"],"assertion_evidence"))
    if len(hashes)!=len(set(hashes)):raise Stage6BindingError("BINDING_ASSERTION_HASH_DUPLICATE")
    if _ids(record["supporting_evidence_ids"],"supporting_evidence")!=sorted(evidence):raise Stage6BindingError("BINDING_SUPPORTING_EVIDENCE_MISMATCH")
    if expected_policy_hash is not None and record["policy_hash"]!=expected_policy_hash:raise BindingIntegrityFailure("BINDING_POLICY_HASH_MISMATCH")
    if event is not None:
        if (record["event_id"],record["event_version"],record["event_hash"],record["event_type"],record["event_status"])!=(event["event_id"],event["event_version"],event["record_hash"],event["event_type"],event["event_status"]):raise BindingIntegrityFailure("BINDING_EVENT_MISMATCH")
        if parse_utc(event["last_updated_timestamp"],"event.last_updated")>parse_utc(cutoff,"cutoff"):raise Stage6BindingError("BINDING_EVENT_FROM_FUTURE")
    if exposure is not None:
        copied=("exposure_id","exposure_version","record_hash","company_entity_id","sector_entity_id","subsector_entity_id","entity_registry_snapshot_id","entity_registry_version","entity_registry_hash")
        actual=(record["exposure_id"],record["exposure_version"],record["exposure_hash"],record["company_entity_id"],record["sector_entity_id"],record["subsector_entity_id"],record["entity_registry_snapshot_id"],record["entity_registry_version"],record["entity_registry_hash"])
        if actual!=tuple(exposure[x] for x in copied):raise BindingIntegrityFailure("BINDING_EXPOSURE_MISMATCH")
        if max(parse_utc(exposure["data_cutoff_timestamp"],"exposure.cutoff"),parse_utc(exposure["as_of_timestamp"],"exposure.asof"))>parse_utc(cutoff,"cutoff"):raise Stage6BindingError("BINDING_EXPOSURE_FROM_FUTURE")
        index={}
        for assertion in exposure["assertions"]:index.setdefault(canonical_hash(assertion),[]).append(assertion)
        day=parse_utc(cutoff,"cutoff").date()
        for ref in refs:
            matches=index.get(ref["assertion_hash"],[])
            if not matches:raise Stage6BindingError("SELECTED_ASSERTION_NOT_FOUND")
            if len(matches)!=1:raise Stage6BindingError("ASSERTION_HASH_AMBIGUOUS")
            assertion=matches[0];expected={"assertion_hash":ref["assertion_hash"],"exposure_type":assertion["exposure_type"],"value_type":assertion["value_type"],"evidence_ids":assertion["evidence_ids"]}
            if ref!=expected:raise BindingIntegrityFailure("BINDING_ASSERTION_REFERENCE_MISMATCH")
            if not date.fromisoformat(assertion["effective_date"])<=day<=date.fromisoformat(assertion["review_or_expiry_date"]):raise Stage6BindingError("SELECTED_ASSERTION_OUTSIDE_BINDING_PERIOD")
    if event is not None and exposure is not None:
        identity=dict(event=event,exposure=exposure,selected_assertion_hashes=hashes,binding_channel=record["binding_channel"],binding_cutoff_timestamp=cutoff,policy_hash=record["policy_hash"],processor_version=record["processor_version"],binding_basis=record["binding_basis"])
        if record["binding_id"]!=deterministic_binding_id(**identity):raise BindingIntegrityFailure("BINDING_ID_MISMATCH")
    if record["record_hash"]!=canonical_hash(without(record,"record_hash")):raise BindingIntegrityFailure("BINDING_RECORD_HASH_MISMATCH")
    return record
