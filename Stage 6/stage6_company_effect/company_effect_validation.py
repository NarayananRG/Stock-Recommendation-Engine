from stage6_ingestion.canonical import canonical_hash,without
from .company_effect_builder import SCHEMA_VERSION,build_company_effect
from .errors import CompanyEffectIntegrityFailure,Stage6CompanyEffectError
def validate_company_effect(record,source_family,source,match,policy,policy_hash):
 if record.get("schema_version")!=SCHEMA_VERSION or record.get("source_family")!=source_family:raise CompanyEffectIntegrityFailure("COMPANY_EFFECT_SCHEMA_OR_SOURCE_INVALID")
 for k in ("stock_direction_status","market_reaction_status","magnitude_status","expected_return_status","causal_effect_status","portfolio_influence_status","security_ranking_status"):
  if record.get(k)!="NOT_EVALUATED":raise Stage6CompanyEffectError("COMPANY_EFFECT_SAFETY_INVALID")
 if record.get("trading_authority") is not False:raise Stage6CompanyEffectError("COMPANY_EFFECT_TRADING_INVALID")
 replay=build_company_effect(source_family=source_family,source=source,match=match,policy=policy,policy_hash=policy_hash)
 if replay!=record or record["record_hash"]!=canonical_hash(without(record,"record_hash")):raise CompanyEffectIntegrityFailure("COMPANY_EFFECT_REPLAY_MISMATCH")
 return record
