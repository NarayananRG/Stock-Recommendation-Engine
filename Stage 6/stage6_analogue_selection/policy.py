import hashlib
import json
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json

from .errors import Stage6AnalogueSelectionError

SCHEMA_VERSION = "STAGE6_ANALOGUE_SELECTION_V1"
STORE_SCHEMA_VERSION = "STAGE6_4C_ANALOGUE_SELECTION_STORE_V1"
PROCESSOR_VERSION = "STAGE6_4C_ANALOGUE_SELECTOR_V1"
POLICY_ID = "S6ANSELPOL_STAGE6_4C_V1"
COMPARISON_CONTRACT_VERSION = "STAGE6_ANALOGUE_COMPARISON_CONTRACT_V1"
METRIC = "STAGE6_MIXED_DISTANCE_V1"
AUTHORITY = "SHADOW_ONLY"
BASELINE_COMMIT = "74f9a4bf4a9e669e9982fc58ba610934d54fc2f2"
FEATURE_SCHEMA = "STAGE6_ANALOGUE_FEATURE_SNAPSHOT_V1"
FEATURE_PROCESSOR = "STAGE6_4B_ANALOGUE_FEATURE_FREEZER_V1"
FEATURE_POLICY_ID = "S6ANFEATPOL_STAGE6_4B_V1"
FEATURE_POLICY_HASH = "ee9b8a5cfb5500d88e9002ffd984d8e37cc690496201fe7913e164f188281f16"
FEATURE_CONTRACT_VERSION = "STAGE6_ANALOGUE_FEATURE_CONTRACT_V1"
FEATURE_CONTRACT_HASH = "4a263fb50e4db4eb44e2e474087cd0cd1e08a68b02298d019ad9d02e8f45484f"
HISTORICAL_BLOB = "85a2b0d00cacd6a3caea484e3ef3071eb16fe01d"
MARKET_BLOB = "a141b221228718b8276b3d05b2f028d21adcfc3f"
EXPECTED_POLICY_HASH_V1 = "36dfffc457342314e0907e31bebb7e54bd21747134dbaded7d34b822e6bcc9b2"
EXPECTED_COMPARISON_CONTRACT_HASH_V1 = "115ae49b1ac8cc005ca1bdb876576600603d593ec2e1ed09c2fee4c6d79b1401"


def _blob(path):
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def _load(name, expected_hash):
    value = json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"))
    digest = canonical_hash(value)
    if digest != expected_hash:
        raise Stage6AnalogueSelectionError("ANALOGUE_SELECTION_CONFIGURATION_HASH_INVALID")
    return value, canonical_json(value), digest


def load_policy():
    value, text, digest = _load("analogue_selection_policy_v1.json", EXPECTED_POLICY_HASH_V1)
    expected = (POLICY_ID, PROCESSOR_VERSION, AUTHORITY, BASELINE_COMMIT)
    actual = tuple(value.get(x) for x in ("policy_id", "processor_version", "authority", "development_baseline"))
    if actual != expected:
        raise Stage6AnalogueSelectionError("ANALOGUE_SELECTION_POLICY_INVALID")
    root = Path(__file__).resolve().parents[1] / "contracts"
    if _blob(root / "historical_analogue.schema.json") != HISTORICAL_BLOB:
        raise Stage6AnalogueSelectionError("HISTORICAL_ANALOGUE_CONTRACT_CHANGED")
    if _blob(root / "market_context.schema.json") != MARKET_BLOB:
        raise Stage6AnalogueSelectionError("MARKET_CONTEXT_CONTRACT_CHANGED")
    return value, text, digest


def load_comparison_contract():
    value, text, digest = _load("analogue_comparison_contract_v1.json", EXPECTED_COMPARISON_CONTRACT_HASH_V1)
    if value.get("contract_version") != COMPARISON_CONTRACT_VERSION or value.get("metric") != METRIC:
        raise Stage6AnalogueSelectionError("ANALOGUE_COMPARISON_CONTRACT_INVALID")
    if len(value.get("feature_weights", {})) != 12 or set(value["feature_weights"].values()) != {1.0}:
        raise Stage6AnalogueSelectionError("ANALOGUE_COMPARISON_WEIGHTS_INVALID")
    return value, text, digest
