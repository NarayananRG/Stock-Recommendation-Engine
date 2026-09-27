from stage6_ingestion.canonical import canonical_hash,without
from .errors import MarketContextIntegrityFailure
from .market_context_builder import PAYLOAD_FIELDS,SCHEMA_VERSION,SAFETY
def validate_record(record):
 p=record.get("contract_payload")
 if not isinstance(p,dict) or set(p)!=PAYLOAD_FIELDS or p.get("schema_version")!=SCHEMA_VERSION or p.get("market_context_id")!=record.get("market_context_record_id"):raise MarketContextIntegrityFailure("MARKET_CONTEXT_CONTRACT_INVALID")
 if any(record.get(k)!=v for k,v in SAFETY.items()):raise MarketContextIntegrityFailure("MARKET_CONTEXT_SAFETY_INVALID")
 if record.get("record_hash")!=canonical_hash(without(record,"record_hash")):raise MarketContextIntegrityFailure("MARKET_CONTEXT_RECORD_HASH_INVALID")
 return record
