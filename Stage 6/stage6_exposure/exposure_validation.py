"""Strict runtime semantics for frozen STAGE6_EXPOSURE_V2."""
from __future__ import annotations
import math,re
from datetime import date
from stage6_ingestion.canonical import canonical_hash, canonical_json, parse_utc, utc_timestamp, without
from .errors import ExposureIntegrityFailure,Stage6ExposureError
from .exposure_builder import EXPOSURE_SCHEMA_VERSION,_assertion_key,_relationship_key,deterministic_exposure_id

HASH=re.compile(r"^[a-f0-9]{64}$")
ROOT={"schema_version","exposure_id","exposure_version","company_entity_id","sector_entity_id","subsector_entity_id","as_of_timestamp","data_cutoff_timestamp","entity_registry_snapshot_id","entity_registry_version","entity_registry_hash","input_evidence_ids","assertions","relationships","previous_version_hash","record_hash"}
ASSERTION={"exposure_type","value_type","measurement","qualitative_value","evidence_ids","confidence","effective_date","review_or_expiry_date"}
RELATIONSHIP={"relationship_type","related_entity_id","evidence_ids","confidence","effective_date","review_or_expiry_date"}
MEASUREMENT={"value","unit","basis","declared_unit"}
TYPES={"REVENUE_GEOGRAPHY","EXPORT_DEPENDENCY","IMPORT_DEPENDENCY","CURRENCY","COMMODITY","ENERGY_SENSITIVITY","INTEREST_RATE_SENSITIVITY","GOVERNMENT_SPENDING","MAJOR_CUSTOMER_INDUSTRY","MAJOR_SUPPLIER_INDUSTRY","GEOPOLITICAL","DEBT_SENSITIVITY","FREIGHT_SENSITIVITY","INPUT_COST_SENSITIVITY"}
UNITS={"PERCENT_REVENUE","FRACTION_REVENUE","PERCENT_COST","FRACTION_COST","INR","USD","PERCENT_IMPORTS","PERCENT_EXPORTS","PERCENT_DEBT","BASIS_POINTS","CORRELATION","BETA_SENSITIVITY","OTHER_DECLARED"}
QUAL={"LOW","MEDIUM","HIGH","MIXED","UNKNOWN"};REL={"PARENT","SUBSIDIARY","GROUP_COMPANY"}

def _ids(value,field):
    if not isinstance(value,list) or not value or any(not isinstance(x,str) or not x for x in value) or value!=sorted(value) or len(value)!=len(set(value)):raise Stage6ExposureError("EXPOSURE_IDS_INVALID:"+field)
    return value
def _period(start,end,as_of,field):
    try:s,e=date.fromisoformat(start),date.fromisoformat(end)
    except Exception as exc:raise Stage6ExposureError("EXPOSURE_DATE_INVALID:"+field) from exc
    if s>e or not s<=as_of<=e:raise Stage6ExposureError("EXPOSURE_PERIOD_INVALID:"+field)

def validate_exposure(record:dict,*,verify_hash:bool=True)->dict:
    if not isinstance(record,dict) or set(record)!=ROOT:raise Stage6ExposureError("EXPOSURE_FIELDS_MISMATCH")
    if record["schema_version"]!=EXPOSURE_SCHEMA_VERSION:raise Stage6ExposureError("EXPOSURE_SCHEMA_INVALID")
    if record["exposure_id"]!=deterministic_exposure_id(record["company_entity_id"]):raise ExposureIntegrityFailure("EXPOSURE_ID_MISMATCH")
    if type(record["exposure_version"]) is not int or record["exposure_version"]<1:raise Stage6ExposureError("EXPOSURE_VERSION_INVALID")
    if record["exposure_version"]==1 and record["previous_version_hash"] is not None:raise Stage6ExposureError("EXPOSURE_V1_PREDECESSOR_INVALID")
    if record["exposure_version"]>1 and (not isinstance(record["previous_version_hash"],str) or not HASH.fullmatch(record["previous_version_hash"])):raise Stage6ExposureError("EXPOSURE_PREDECESSOR_REQUIRED")
    for f in ("record_hash","entity_registry_hash"):
        if not isinstance(record[f],str) or not HASH.fullmatch(record[f]):raise Stage6ExposureError("EXPOSURE_HASH_INVALID:"+f)
    if not isinstance(record["sector_entity_id"],str) or not record["sector_entity_id"] or (record["subsector_entity_id"] is not None and (not isinstance(record["subsector_entity_id"],str) or not record["subsector_entity_id"])):raise Stage6ExposureError("EXPOSURE_SECTOR_FIELDS_INVALID")
    if type(record["entity_registry_version"]) is not int or record["entity_registry_version"]<1:raise Stage6ExposureError("EXPOSURE_REGISTRY_VERSION_INVALID")
    asof=utc_timestamp(record["as_of_timestamp"],"as_of_timestamp");cutoff=utc_timestamp(record["data_cutoff_timestamp"],"data_cutoff_timestamp")
    if asof!=record["as_of_timestamp"] or cutoff!=record["data_cutoff_timestamp"] or parse_utc(cutoff,"cutoff")>parse_utc(asof,"asof"):raise Stage6ExposureError("EXPOSURE_TIMESTAMP_INVALID")
    asdate=parse_utc(asof,"asof").date();root=set(_ids(record["input_evidence_ids"],"input"));used=set()
    if not isinstance(record["assertions"],list) or not isinstance(record["relationships"],list) or not (record["assertions"] or record["relationships"]):raise Stage6ExposureError("EXPOSURE_CONTENT_REQUIRED")
    if record["assertions"]!=sorted(record["assertions"],key=_assertion_key):raise Stage6ExposureError("ASSERTION_ORDER_INVALID")
    for a in record["assertions"]:
        if not isinstance(a,dict) or set(a)!=ASSERTION or a["exposure_type"] not in TYPES or a["value_type"] not in {"QUANTITATIVE","QUALITATIVE"}:raise Stage6ExposureError("ASSERTION_FIELDS_INVALID")
        ids=set(_ids(a["evidence_ids"],"assertion"));used|=ids
        if not ids<=root:raise Stage6ExposureError("ASSERTION_EVIDENCE_UNDECLARED")
        if type(a["confidence"]) not in (int,float) or isinstance(a["confidence"],bool) or a["confidence"]!=0.0:raise Stage6ExposureError("ASSERTION_CONFIDENCE_MUST_BE_ZERO")
        _period(a["effective_date"],a["review_or_expiry_date"],asdate,"assertion")
        if a["value_type"]=="QUANTITATIVE":
            m=a["measurement"]
            if a["qualitative_value"] is not None or not isinstance(m,dict) or set(m)!=MEASUREMENT:raise Stage6ExposureError("QUANTITATIVE_ASSERTION_INVALID")
            v=m["value"]
            if type(v) not in (int,float) or isinstance(v,bool) or not math.isfinite(v) or m["unit"] not in UNITS or not isinstance(m["basis"],str) or not m["basis"].strip():raise Stage6ExposureError("MEASUREMENT_INVALID")
            if (m["unit"]=="OTHER_DECLARED" and (not isinstance(m["declared_unit"],str) or not m["declared_unit"].strip())) or (m["unit"]!="OTHER_DECLARED" and m["declared_unit"] is not None):raise Stage6ExposureError("MEASUREMENT_DECLARED_UNIT_INVALID")
        elif a["measurement"] is not None or a["qualitative_value"] not in QUAL:raise Stage6ExposureError("QUALITATIVE_ASSERTION_INVALID")
    if record["relationships"]!=sorted(record["relationships"],key=_relationship_key):raise Stage6ExposureError("RELATIONSHIP_ORDER_INVALID")
    for rel in record["relationships"]:
        if not isinstance(rel,dict) or set(rel)!=RELATIONSHIP or rel["relationship_type"] not in REL or not isinstance(rel["related_entity_id"],str) or not rel["related_entity_id"]:raise Stage6ExposureError("RELATIONSHIP_FIELDS_INVALID")
        ids=set(_ids(rel["evidence_ids"],"relationship"));used|=ids
        if not ids<=root:raise Stage6ExposureError("RELATIONSHIP_EVIDENCE_UNDECLARED")
        if type(rel["confidence"]) not in (int,float) or isinstance(rel["confidence"],bool) or rel["confidence"]!=0.0:raise Stage6ExposureError("RELATIONSHIP_CONFIDENCE_MUST_BE_ZERO")
        _period(rel["effective_date"],rel["review_or_expiry_date"],asdate,"relationship")
    if used!=root:raise Stage6ExposureError("EXPOSURE_EVIDENCE_COVERAGE_MISMATCH")
    if verify_hash and record["record_hash"]!=canonical_hash(without(record,"record_hash")):raise ExposureIntegrityFailure("EXPOSURE_RECORD_HASH_MISMATCH")
    return record
