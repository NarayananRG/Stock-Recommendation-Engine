from copy import deepcopy
from stage6_ingestion.canonical import canonical_hash,parse_utc,utc_timestamp,without
from .errors import Stage6MarketContextError
SCHEMA_VERSION="STAGE6_MARKET_CONTEXT_V2"
PAYLOAD_FIELDS={"schema_version","market_context_id","ticker","as_of_timestamp","data_cutoff_timestamp","stock_returns","sector_returns","nifty_returns","volume_anomaly","volatility","gap","technical_context","relative_strength","commodity_context","currency_context","rate_context","market_regime","source_evidence_ids","pit_verified"}
RET_FIELDS={"unit","1D","3D","5D","20D","observed_at_utc","method"};MEAS_FIELDS={"value","unit","observed_at_utc","method"};NAMED_FIELDS={"name",*MEAS_FIELDS};CTX_FIELDS={"value","observed_at_utc","method"}
SAFETY={"historical_analogue_selection_status":"NOT_EVALUATED","future_outcomes_status":"NOT_ATTACHED","expected_return_status":"NOT_EVALUATED","stock_direction_status":"NOT_EVALUATED","portfolio_influence_status":"NOT_EVALUATED","trading_authority":False}
def _timestamp(v,n):
 try:return utc_timestamp(v,n)
 except Exception as exc:raise Stage6MarketContextError(f"MARKET_CONTEXT_TIMESTAMP_INVALID:{n}") from exc
def _scalar(v,n):
 if isinstance(v,(dict,list)):raise Stage6MarketContextError(f"MARKET_CONTEXT_HIDDEN_STRUCTURE_PROHIBITED:{n}")
def _observed(x,fields,cutoff,name):
 if not isinstance(x,dict) or set(x)!=fields:raise Stage6MarketContextError(f"MARKET_CONTEXT_FIELDS_INVALID:{name}")
 y=deepcopy(x);y["observed_at_utc"]=_timestamp(y["observed_at_utc"],f"{name}.observed_at_utc")
 if parse_utc(y["observed_at_utc"],name)>parse_utc(cutoff,"cutoff"):raise Stage6MarketContextError(f"MARKET_CONTEXT_FUTURE_OBSERVATION:{name}")
 if not isinstance(y["method"],str) or not y["method"]:raise Stage6MarketContextError(f"MARKET_CONTEXT_METHOD_INVALID:{name}")
 return y
def normalize_payload(raw,policy):
 if not isinstance(raw,dict):raise Stage6MarketContextError("MARKET_CONTEXT_PAYLOAD_INVALID")
 supplied=set(raw);allowed=PAYLOAD_FIELDS-{"market_context_id"}
 if supplied!=allowed:raise Stage6MarketContextError("MARKET_CONTEXT_PAYLOAD_FIELDS_INVALID")
 p=deepcopy(raw)
 if p.get("schema_version")!=SCHEMA_VERSION:raise Stage6MarketContextError("MARKET_CONTEXT_SCHEMA_INVALID")
 if not isinstance(p["ticker"],str) or not p["ticker"]:raise Stage6MarketContextError("MARKET_CONTEXT_TICKER_INVALID")
 p["as_of_timestamp"]=_timestamp(p["as_of_timestamp"],"as_of_timestamp");p["data_cutoff_timestamp"]=_timestamp(p["data_cutoff_timestamp"],"data_cutoff_timestamp")
 if parse_utc(p["data_cutoff_timestamp"],"cutoff")>parse_utc(p["as_of_timestamp"],"asof"):raise Stage6MarketContextError("MARKET_CONTEXT_CUTOFF_AFTER_ASOF")
 cutoff=p["data_cutoff_timestamp"]
 for key in ("stock_returns","sector_returns","nifty_returns"):
  x=_observed(p[key],RET_FIELDS,cutoff,key)
  if x["unit"] not in policy["return_units"]:raise Stage6MarketContextError(f"MARKET_CONTEXT_RETURN_UNIT_INVALID:{key}")
  for h in policy["return_horizons"]:
   if x[h] is not None and (type(x[h]) not in (int,float) or isinstance(x[h],bool)):raise Stage6MarketContextError(f"MARKET_CONTEXT_NUMERIC_INVALID:{key}.{h}")
  p[key]=x
 for key in ("volume_anomaly","volatility","gap","relative_strength"):
  x=_observed(p[key],MEAS_FIELDS,cutoff,key)
  if x["unit"] not in policy["allowed_units"]:raise Stage6MarketContextError(f"MARKET_CONTEXT_UNIT_INVALID:{key}")
  if x["value"] is not None and (type(x["value"]) not in (int,float) or isinstance(x["value"],bool)):raise Stage6MarketContextError(f"MARKET_CONTEXT_NUMERIC_INVALID:{key}")
  p[key]=x
 for key in ("technical_context","market_regime"):
  x=_observed(p[key],CTX_FIELDS,cutoff,key);_scalar(x["value"],key);p[key]=x
 for key in ("commodity_context","currency_context","rate_context"):
  if not isinstance(p[key],list):raise Stage6MarketContextError(f"MARKET_CONTEXT_ARRAY_INVALID:{key}")
  values=[];names=[]
  for i,item in enumerate(p[key]):
   x=_observed(item,NAMED_FIELDS,cutoff,f"{key}[{i}]")
   if not isinstance(x["name"],str) or not x["name"]:raise Stage6MarketContextError(f"MARKET_CONTEXT_NAME_INVALID:{key}")
   if x["unit"] not in policy["allowed_units"]:raise Stage6MarketContextError(f"MARKET_CONTEXT_UNIT_INVALID:{key}")
   if x["value"] is not None and (type(x["value"]) not in (int,float) or isinstance(x["value"],bool)):raise Stage6MarketContextError(f"MARKET_CONTEXT_NUMERIC_INVALID:{key}")
   values.append(x);names.append(x["name"].casefold())
  if len(names)!=len(set(names)):raise Stage6MarketContextError(f"MARKET_CONTEXT_DUPLICATE_NAMED_MEASUREMENT:{key}")
  p[key]=sorted(values,key=lambda x:(x["name"].casefold(),x["unit"],x["observed_at_utc"],x["method"]))
 ids=p["source_evidence_ids"]
 if not isinstance(ids,list) or not ids or any(not isinstance(x,str) or not x for x in ids) or len(ids)!=len(set(ids)):raise Stage6MarketContextError("MARKET_CONTEXT_EVIDENCE_IDS_INVALID")
 p["source_evidence_ids"]=sorted(ids);p["pit_verified"]=p["pit_verified"] is True
 if p["pit_verified"] is not True:raise Stage6MarketContextError("MARKET_CONTEXT_PIT_FLAG_REQUIRED")
 p["market_context_id"]=""
 return p
def build_record(*,payload,company_entity,registry,mapping,evidence_bindings,policy,policy_hash):
 body=deepcopy(payload);identity={"schema_version":SCHEMA_VERSION,"company_entity_id":company_entity["entity_id"],"company_entity_record_hash":company_entity["record_hash"],"entity_registry_snapshot_id":registry["registry_snapshot_id"],"entity_registry_hash":registry["registry_hash"],"ticker_mapping":mapping,"payload":without(body,"market_context_id"),"evidence_bindings":evidence_bindings,"policy_hash":policy_hash,"processor_version":policy["processor_version"]};context_id="S6MCTX_"+canonical_hash(identity)[:24];body["market_context_id"]=context_id
 out={"market_context_record_id":context_id,"record_hash":"0"*64,"logical_context_key":"S6MCTXLOG_"+canonical_hash({"company_entity_id":company_entity["entity_id"],"exchange":mapping["exchange"],"ticker":mapping["ticker"],"as_of_timestamp":body["as_of_timestamp"],"data_cutoff_timestamp":body["data_cutoff_timestamp"]})[:24],"contract_payload":body,"company_entity_id":company_entity["entity_id"],"company_entity_record_version":company_entity["entity_record_version"],"company_entity_record_hash":company_entity["record_hash"],"entity_registry_snapshot_id":registry["registry_snapshot_id"],"entity_registry_version":registry["registry_version"],"entity_registry_hash":registry["registry_hash"],"exchange":mapping["exchange"],"ticker_mapping":mapping,"evidence_bindings":evidence_bindings,**SAFETY,"policy_id":policy["policy_id"],"policy_hash":policy_hash,"processor_version":policy["processor_version"],"authority":policy["authority"]};out["record_hash"]=canonical_hash(without(out,"record_hash"));return out
