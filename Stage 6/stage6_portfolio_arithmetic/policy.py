import hashlib
import json
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json
from .errors import PortfolioArithmeticIntegrityFailure

SCHEMA_VERSION = "STAGE6_PORTFOLIO_ARITHMETIC_V1"
STORE_SCHEMA_VERSION = "STAGE6_5B_PORTFOLIO_ARITHMETIC_STORE_V1"
PROCESSOR_VERSION = "STAGE6_5B_PORTFOLIO_ARITHMETIC_AGGREGATOR_V1"
POLICY_ID = "S6PORTARITHPOL_STAGE6_5B_V1"
ARITHMETIC_CONTRACT_VERSION = "STAGE6_PORTFOLIO_ARITHMETIC_CONTRACT_V1"
AUTHORITY = "SHADOW_ONLY"
BASELINE_COMMIT = "93b05ded5042423a6fa208cdb29f5961687fdb9c"
PORTFOLIO_CONTEXT_BLOB = "5900278a891dc70c63ce02f69002b5e9dec13799"
SOURCE_SCHEMA_VERSION = "STAGE6_PORTFOLIO_SOURCE_SNAPSHOT_V1"
SOURCE_PROCESSOR_VERSION = "STAGE6_5A_PORTFOLIO_SOURCE_FREEZER_V1"
SOURCE_POLICY_ID = "S6PORTSRCPOL_STAGE6_5A_V1"
SOURCE_POLICY_HASH = "1a9630e451429004d511bc9dab3124d70e2fef28b30adee3935741f30af537f2"
SOURCE_CONTRACT_VERSION = "STAGE6_PORTFOLIO_CONSTITUENT_CONTRACT_V1"
SOURCE_CONTRACT_HASH = "20e84549c4a1d5c5a526bad63cd92e798403fa92805e9e4f4af35bbaa062ed0c"
EXPECTED_POLICY_HASH_V1 = "dd2dcdcd7cbf00182d9ab62f0eca942fae8246ec570a2004388aa9dd3bdb5d19"
EXPECTED_ARITHMETIC_CONTRACT_HASH_V1 = "72642f1d50d6d1c78e2c15c23f81cefd88a62bf942d5f7d01bfd113665b7da80"


def _git_blob(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def _load(name: str, expected_hash: str) -> tuple[dict, str, str]:
    value = json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"))
    digest = canonical_hash(value)
    if expected_hash != "TO_BE_COMPUTED" and digest != expected_hash:
        raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_CONFIGURATION_HASH_INVALID")
    return value, canonical_json(value), digest


def load_policy() -> tuple[dict, str, str]:
    value, text, digest = _load("portfolio_arithmetic_policy_v1.json", EXPECTED_POLICY_HASH_V1)
    expected = (POLICY_ID, PROCESSOR_VERSION, AUTHORITY, BASELINE_COMMIT, SOURCE_SCHEMA_VERSION,
                SOURCE_PROCESSOR_VERSION, SOURCE_POLICY_ID, SOURCE_POLICY_HASH,
                SOURCE_CONTRACT_VERSION, SOURCE_CONTRACT_HASH)
    actual = tuple(value.get(key) for key in (
        "policy_id", "processor_version", "authority", "development_baseline",
        "source_schema_version", "source_processor_version", "source_policy_id", "source_policy_hash",
        "source_constituent_contract_version", "source_constituent_contract_hash"))
    if actual != expected:
        raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_POLICY_INVALID")
    contract = Path(__file__).resolve().parents[1] / "contracts" / "portfolio_context.schema.json"
    if _git_blob(contract) != PORTFOLIO_CONTEXT_BLOB:
        raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_FROZEN_CONTRACT_CHANGED")
    return value, text, digest


def load_arithmetic_contract() -> tuple[dict, str, str]:
    value, text, digest = _load("portfolio_arithmetic_contract_v1.json", EXPECTED_ARITHMETIC_CONTRACT_HASH_V1)
    if value.get("contract_version") != ARITHMETIC_CONTRACT_VERSION:
        raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_CONTRACT_INVALID")
    return value, text, digest
