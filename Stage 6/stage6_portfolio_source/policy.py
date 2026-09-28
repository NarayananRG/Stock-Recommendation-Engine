import hashlib
import json
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json
from .errors import PortfolioSourceIntegrityFailure

SCHEMA_VERSION = "STAGE6_PORTFOLIO_SOURCE_SNAPSHOT_V1"
STORE_SCHEMA_VERSION = "STAGE6_5A_PORTFOLIO_SOURCE_STORE_V1"
PROCESSOR_VERSION = "STAGE6_5A_PORTFOLIO_SOURCE_FREEZER_V1"
POLICY_ID = "S6PORTSRCPOL_STAGE6_5A_V1"
CONSTITUENT_CONTRACT_VERSION = "STAGE6_PORTFOLIO_CONSTITUENT_CONTRACT_V1"
AUTHORITY = "SHADOW_ONLY"
BASELINE_COMMIT = "f150608994fbeea3b79d2a078642dee89e4f6a59"
STAGE5D5_REFERENCE_COMMIT = "74b2710f0e19bd403978da81e87f25a3059ace06"
PORTFOLIO_CONTEXT_BLOB = "5900278a891dc70c63ce02f69002b5e9dec13799"
EXPECTED_POLICY_HASH_V1 = "1a9630e451429004d511bc9dab3124d70e2fef28b30adee3935741f30af537f2"
EXPECTED_CONSTITUENT_CONTRACT_HASH_V1 = "20e84549c4a1d5c5a526bad63cd92e798403fa92805e9e4f4af35bbaa062ed0c"


def _git_blob(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def _load(name: str, expected_hash: str) -> tuple[dict, str, str]:
    value = json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"))
    digest = canonical_hash(value)
    if digest != expected_hash:
        raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_CONFIGURATION_HASH_INVALID")
    return value, canonical_json(value), digest


def load_policy() -> tuple[dict, str, str]:
    value, text, digest = _load("portfolio_source_policy_v1.json", EXPECTED_POLICY_HASH_V1)
    expected = (POLICY_ID, PROCESSOR_VERSION, AUTHORITY, BASELINE_COMMIT, STAGE5D5_REFERENCE_COMMIT)
    actual = tuple(value.get(k) for k in (
        "policy_id", "processor_version", "authority", "development_baseline",
        "stage5d5_reference_commit"))
    if actual != expected:
        raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_POLICY_INVALID")
    contracts = Path(__file__).resolve().parents[1] / "contracts"
    if _git_blob(contracts / "portfolio_context.schema.json") != PORTFOLIO_CONTEXT_BLOB:
        raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_FROZEN_CONTRACT_CHANGED")
    return value, text, digest


def load_constituent_contract() -> tuple[dict, str, str]:
    value, text, digest = _load("portfolio_constituent_contract_v1.json", EXPECTED_CONSTITUENT_CONTRACT_HASH_V1)
    if value.get("contract_version") != CONSTITUENT_CONTRACT_VERSION:
        raise PortfolioSourceIntegrityFailure("PORTFOLIO_CONSTITUENT_CONTRACT_INVALID")
    return value, text, digest
