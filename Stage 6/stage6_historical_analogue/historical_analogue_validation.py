import re
from stage6_ingestion.canonical import canonical_hash,parse_utc,without
from .errors import HistoricalAnalogueIntegrityFailure
from .policy import AUTHORITY,SCHEMA_VERSION,SELECTION_ENGINE_COMMIT
from .historical_analogue_builder import HORIZONS,SAFETY
DIST_FIELDS={"unit","count","median","mean","standard_deviation","p10","p25","p75","p90","minimum","maximum"};MEAS_FIELDS={"value","unit"}
FINAL_FIELDS={"schema_version","historical_analogue_id","as_of_timestamp","selection_cutoff","analogue_engine_version","code_commit","feature_contract_version","feature_snapshot_hash","similarity_metric","feature_weights","selection_thresholds","eligible_universe_definition","eligible_date_range","exclusion_rules","selection_input_snapshot","selection_input_hash","selected_analogues","analogue_count","minimum_required_analogue_count","outcome_definition_version","outcome_unit","future_outcome_labels","maximum_adverse_excursion","maximum_favourable_excursion","recovery_time","relative_return_vs_sector","relative_return_vs_nifty","record_hash","pit_verified","authority_mode"}
def validate_final_payload(p):
 if not isinstance(p,dict) or set(p)!=FINAL_FIELDS or p.get("schema_version")!=SCHEMA_VERSION or p.get("code_commit")!=SELECTION_ENGINE_COMMIT or p.get("analogue_engine_version")!="STAGE6_4C_ANALOGUE_SELECTOR_V1" or p.get("authority_mode")!=AUTHORITY or p.get("pit_verified") is not True:raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_SCHEMA_INVALID")
 parse_utc(p["as_of_timestamp"],"as_of");parse_utc(p["selection_cutoff"],"cutoff")
 if len(p.get("selected_analogues",[]))!=p.get("analogue_count") or p.get("minimum_required_analogue_count",0)<1:raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_COUNT_INVALID")
 if set(p.get("future_outcome_labels",{}))!=set(HORIZONS) or set(p.get("relative_return_vs_sector",{}))!=set(HORIZONS) or set(p.get("relative_return_vs_nifty",{}))!=set(HORIZONS):raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_HORIZONS_INVALID")
 distributions=list(p["future_outcome_labels"].values())+[p["maximum_adverse_excursion"],p["maximum_favourable_excursion"],p["recovery_time"]]
 if any(set(x)!=DIST_FIELDS or type(x["count"]) is not int or x["count"]<0 for x in distributions):raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_DISTRIBUTION_SCHEMA_INVALID")
 if p["recovery_time"]["unit"]!="TRADING_SESSIONS" or any(set(x)!=MEAS_FIELDS for x in list(p["relative_return_vs_sector"].values())+list(p["relative_return_vs_nifty"].values())):raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_MEASUREMENT_SCHEMA_INVALID")
 identity=canonical_hash(without(p,"historical_analogue_id","record_hash"))
 if p["historical_analogue_id"]!="S6HAN_"+identity[:24] or not re.fullmatch(r"[a-f0-9]{64}",p["record_hash"]) or p["record_hash"]!=canonical_hash(without(p,"record_hash")):raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_HASH_INVALID")
 return p
def validate_wrapper(r):
 validate_final_payload(r["historical_analogue_payload"])
 if any(r.get(k)!=v for k,v in SAFETY.items()) or r.get("authority")!=AUTHORITY:raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_SAFETY_INVALID")
 core=without(r,"wrapper_id","wrapper_hash","record_hash");digest=canonical_hash(core)
 if r.get("wrapper_hash")!=digest or r.get("wrapper_id")!="S6HANWRAP_"+digest[:24] or r.get("record_hash")!=canonical_hash(without(r,"record_hash")):raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_WRAPPER_HASH_INVALID")
 return r
