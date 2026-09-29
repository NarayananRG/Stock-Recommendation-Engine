import hashlib
import json
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json
from .errors import PortfolioCorrelationIntegrityFailure

SCHEMA_VERSION = "STAGE6_PORTFOLIO_CORRELATION_CONTEXT_V1"
STORE_SCHEMA_VERSION = "STAGE6_5C_PORTFOLIO_CORRELATION_STORE_V1"
PROCESSOR_VERSION = "STAGE6_5C_PORTFOLIO_CORRELATION_CALCULATOR_V1"
POLICY_ID = "S6PORTCORRPOL_STAGE6_5C_V1"
CORRELATION_CONTRACT_VERSION = "STAGE6_PORTFOLIO_CORRELATION_CONTRACT_V1"
METHOD = "PEARSON_PAIRWISE_COMPLETE_V1"
AUTHORITY = "SHADOW_ONLY"
BASELINE_COMMIT = "31527d4c6f61e467306c62607d5d3ab4dd98a9d5"
BASELINE_PARENT = "93b05ded5042423a6fa208cdb29f5961687fdb9c"
PORTFOLIO_CONTEXT_BLOB = "5900278a891dc70c63ce02f69002b5e9dec13799"
SOURCE_SCHEMA_VERSION = "STAGE6_PORTFOLIO_ARITHMETIC_V1"
SOURCE_PROCESSOR_VERSION = "STAGE6_5B_PORTFOLIO_ARITHMETIC_AGGREGATOR_V1"
SOURCE_POLICY_ID = "S6PORTARITHPOL_STAGE6_5B_V1"
SOURCE_POLICY_HASH = "dd2dcdcd7cbf00182d9ab62f0eca942fae8246ec570a2004388aa9dd3bdb5d19"
SOURCE_CONTRACT_VERSION = "STAGE6_PORTFOLIO_ARITHMETIC_CONTRACT_V1"
SOURCE_CONTRACT_HASH = "72642f1d50d6d1c78e2c15c23f81cefd88a62bf942d5f7d01bfd113665b7da80"
EXPECTED_POLICY_HASH_V1 = "b03dd26fdf5d8171dd42bb628f80609a833c9c2bce7c0808ca9ea8e0c87321c0"
EXPECTED_CORRELATION_CONTRACT_HASH_V1 = "9e852563a63c8e8ce1f21ebd542a2355b5330b8e0aa2d7b940d350fa399c234e"


def _git_blob(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def _load(name: str, expected_hash: str):
    value = json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"))
    digest = canonical_hash(value)
    if expected_hash != "TO_BE_COMPUTED" and digest != expected_hash:
        raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_CONFIGURATION_HASH_INVALID")
    return value, canonical_json(value), digest


def load_policy():
    value, text, digest = _load("portfolio_correlation_policy_v1.json", EXPECTED_POLICY_HASH_V1)
    expected = (POLICY_ID, PROCESSOR_VERSION, AUTHORITY, BASELINE_COMMIT, SOURCE_SCHEMA_VERSION,
                SOURCE_PROCESSOR_VERSION, SOURCE_POLICY_ID, SOURCE_POLICY_HASH,
                SOURCE_CONTRACT_VERSION, SOURCE_CONTRACT_HASH)
    actual = tuple(value.get(key) for key in (
        "policy_id", "processor_version", "authority", "development_baseline",
        "source_schema_version", "source_processor_version", "source_policy_id", "source_policy_hash",
        "source_arithmetic_contract_version", "source_arithmetic_contract_hash"))
    if actual != expected:
        raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_POLICY_INVALID")
    contract = Path(__file__).resolve().parents[1] / "contracts" / "portfolio_context.schema.json"
    if _git_blob(contract) != PORTFOLIO_CONTEXT_BLOB:
        raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_FROZEN_CONTRACT_CHANGED")
    return value, text, digest


def load_correlation_contract():
    value, text, digest = _load("portfolio_correlation_contract_v1.json", EXPECTED_CORRELATION_CONTRACT_HASH_V1)
    if value.get("contract_version") != CORRELATION_CONTRACT_VERSION or value.get("method") != METHOD:
        raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_CONTRACT_INVALID")
    return value, text, digest
