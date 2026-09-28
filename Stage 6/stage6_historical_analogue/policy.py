import hashlib,json,subprocess
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json
from .errors import Stage6HistoricalAnalogueError
SCHEMA_VERSION="STAGE6_HISTORICAL_ANALOGUE_V2";STORE_SCHEMA_VERSION="STAGE6_4E_HISTORICAL_ANALOGUE_STORE_V1";PROCESSOR_VERSION="STAGE6_4E_HISTORICAL_ANALOGUE_AGGREGATOR_V1";POLICY_ID="S6ANAGGPOL_STAGE6_4E_V1";AGGREGATION_CONTRACT_VERSION="STAGE6_ANALOGUE_AGGREGATION_CONTRACT_V1";AUTHORITY="SHADOW_ONLY";BASELINE_COMMIT="10860dae29d1d0d3b1f1b595d1aad37e34aed6c9";SELECTION_ENGINE_COMMIT="ecdbb6cba292ee52a25b3e73bab901eeb1721f87";OUTCOME_ATTACHMENT_COMMIT=BASELINE_COMMIT;HISTORICAL_BLOB="85a2b0d00cacd6a3caea484e3ef3071eb16fe01d";MARKET_BLOB="a141b221228718b8276b3d05b2f028d21adcfc3f"
EXPECTED_POLICY_HASH_V1="41dacb0dfa0dcf09d5311b78573a50865372ada0bbf917d9c95e03edc4c0173f";EXPECTED_AGGREGATION_CONTRACT_HASH_V1="028f3829634793af67c33f7ab041ae8c8732e9d8ea3502c058a478ea9316b981"
def _blob(path):
 data=path.read_bytes();return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
def _load(name,expected):
 value=json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"));digest=canonical_hash(value)
 if digest!=expected:raise Stage6HistoricalAnalogueError("HISTORICAL_ANALOGUE_CONFIGURATION_HASH_INVALID")
 return value,canonical_json(value),digest
def _ancestor(commit):
 repo=Path(__file__).resolve().parents[2]
 try:value=subprocess.check_output(["git","merge-base","HEAD",commit],cwd=repo,text=True).strip()
 except (OSError,subprocess.CalledProcessError) as exc:raise Stage6HistoricalAnalogueError("HISTORICAL_ANALOGUE_ANCESTRY_UNVERIFIED") from exc
 if value!=commit:raise Stage6HistoricalAnalogueError("HISTORICAL_ANALOGUE_COMMIT_NOT_ANCESTOR")
def load_policy():
 value,text,digest=_load("historical_analogue_policy_v1.json",EXPECTED_POLICY_HASH_V1)
 if tuple(value.get(k) for k in ("policy_id","processor_version","authority","development_baseline","selection_engine_commit","outcome_attachment_commit"))!=(POLICY_ID,PROCESSOR_VERSION,AUTHORITY,BASELINE_COMMIT,SELECTION_ENGINE_COMMIT,OUTCOME_ATTACHMENT_COMMIT):raise Stage6HistoricalAnalogueError("HISTORICAL_ANALOGUE_POLICY_INVALID")
 contracts=Path(__file__).resolve().parents[1]/"contracts"
 if _blob(contracts/"historical_analogue.schema.json")!=HISTORICAL_BLOB or _blob(contracts/"market_context.schema.json")!=MARKET_BLOB:raise Stage6HistoricalAnalogueError("HISTORICAL_ANALOGUE_FROZEN_CONTRACT_CHANGED")
 _ancestor(SELECTION_ENGINE_COMMIT);_ancestor(OUTCOME_ATTACHMENT_COMMIT);return value,text,digest
def load_aggregation_contract():
 value,text,digest=_load("analogue_aggregation_contract_v1.json",EXPECTED_AGGREGATION_CONTRACT_HASH_V1)
 if value.get("contract_version")!=AGGREGATION_CONTRACT_VERSION:return (_ for _ in ()).throw(Stage6HistoricalAnalogueError("ANALOGUE_AGGREGATION_CONTRACT_INVALID"))
 return value,text,digest
