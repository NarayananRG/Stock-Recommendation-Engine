import hashlib
import json
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json
from .errors import PortfolioContextIntegrityFailure

PAYLOAD_SCHEMA_VERSION = "STAGE6_PORTFOLIO_CONTEXT_V2"
WRAPPER_SCHEMA_VERSION = "STAGE6_PORTFOLIO_CONTEXT_ASSEMBLY_RECORD_V1"
STORE_SCHEMA_VERSION = "STAGE6_5D_PORTFOLIO_CONTEXT_STORE_V1"
PROCESSOR_VERSION = "STAGE6_5D_PORTFOLIO_CONTEXT_ASSEMBLER_V1"
POLICY_ID = "S6PORTCTXPOL_STAGE6_5D_V1"
ASSEMBLY_CONTRACT_VERSION = "STAGE6_PORTFOLIO_CONTEXT_ASSEMBLY_CONTRACT_V1"
AUTHORITY = "SHADOW_ONLY"
BASELINE_COMMIT = "a8f282e6b5c5ccccbdfb594a1744a504f14d91ad"
PORTFOLIO_CONTEXT_BLOB = "5900278a891dc70c63ce02f69002b5e9dec13799"
ARITHMETIC_SCHEMA = "STAGE6_PORTFOLIO_ARITHMETIC_V1"
ARITHMETIC_PROCESSOR = "STAGE6_5B_PORTFOLIO_ARITHMETIC_AGGREGATOR_V1"
ARITHMETIC_POLICY_ID = "S6PORTARITHPOL_STAGE6_5B_V1"
ARITHMETIC_POLICY_HASH = "dd2dcdcd7cbf00182d9ab62f0eca942fae8246ec570a2004388aa9dd3bdb5d19"
ARITHMETIC_CONTRACT_VERSION = "STAGE6_PORTFOLIO_ARITHMETIC_CONTRACT_V1"
ARITHMETIC_CONTRACT_HASH = "72642f1d50d6d1c78e2c15c23f81cefd88a62bf942d5f7d01bfd113665b7da80"
CORRELATION_SCHEMA = "STAGE6_PORTFOLIO_CORRELATION_CONTEXT_V1"
CORRELATION_PROCESSOR = "STAGE6_5C_PORTFOLIO_CORRELATION_CALCULATOR_V1"
CORRELATION_POLICY_ID = "S6PORTCORRPOL_STAGE6_5C_V1"
CORRELATION_POLICY_HASH = "b03dd26fdf5d8171dd42bb628f80609a833c9c2bce7c0808ca9ea8e0c87321c0"
CORRELATION_CONTRACT_VERSION = "STAGE6_PORTFOLIO_CORRELATION_CONTRACT_V1"
CORRELATION_CONTRACT_HASH = "9e852563a63c8e8ce1f21ebd542a2355b5330b8e0aa2d7b940d350fa399c234e"
EXPECTED_POLICY_HASH_V1 = "fa76c6f99b6bb7122c59864d725272992a90e0d5c09f4c7b806f42dfea6191c8"
EXPECTED_ASSEMBLY_CONTRACT_HASH_V1 = "e980580a573dea1bedd78108e6ac9aaf2d08277728d5c0ef9e12af6db5f3bc8b"


def git_blob(path):
    data = Path(path).read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def _load(name, expected):
    value = json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"))
    digest = canonical_hash(value)
    if expected != "TO_BE_COMPUTED" and digest != expected:
        raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_CONFIGURATION_HASH_INVALID")
    return value, canonical_json(value), digest


def load_policy():
    value, text, digest = _load("portfolio_context_policy_v1.json", EXPECTED_POLICY_HASH_V1)
    if (value.get("policy_id"), value.get("processor_version"), value.get("authority"),
        value.get("development_baseline"), value.get("payload_schema")) != (
            POLICY_ID, PROCESSOR_VERSION, AUTHORITY, BASELINE_COMMIT, PAYLOAD_SCHEMA_VERSION):
        raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_POLICY_INVALID")
    schema = Path(__file__).resolve().parents[1] / "contracts" / "portfolio_context.schema.json"
    if git_blob(schema) != PORTFOLIO_CONTEXT_BLOB:
        raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_FROZEN_SCHEMA_CHANGED")
    return value, text, digest


def load_assembly_contract():
    value, text, digest = _load("portfolio_context_assembly_contract_v1.json", EXPECTED_ASSEMBLY_CONTRACT_HASH_V1)
    if value.get("contract_version") != ASSEMBLY_CONTRACT_VERSION or value.get("payload_schema") != PAYLOAD_SCHEMA_VERSION:
        raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_ASSEMBLY_CONTRACT_INVALID")
    return value, text, digest
