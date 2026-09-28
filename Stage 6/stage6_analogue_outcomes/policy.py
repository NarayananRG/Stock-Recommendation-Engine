import hashlib
import json
import subprocess
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json

from .errors import Stage6AnalogueOutcomeError

SCHEMA_VERSION = "STAGE6_ANALOGUE_OUTCOME_ATTACHMENT_V1"
STORE_SCHEMA_VERSION = "STAGE6_4D_ANALOGUE_OUTCOME_STORE_V1"
PROCESSOR_VERSION = "STAGE6_4D_ANALOGUE_OUTCOME_ATTACHER_V1"
POLICY_ID = "S6ANOUTPOL_STAGE6_4D_V1"
OUTCOME_DEFINITION_VERSION = "STAGE6_ANALOGUE_OUTCOME_DEFINITION_V1"
AUTHORITY = "SHADOW_ONLY"
BASELINE_COMMIT = "ecdbb6cba292ee52a25b3e73bab901eeb1721f87"
SELECTION_ENGINE_COMMIT = BASELINE_COMMIT
SELECTION_SCHEMA = "STAGE6_ANALOGUE_SELECTION_V1"
SELECTION_STORE = "STAGE6_4C_ANALOGUE_SELECTION_STORE_V1"
SELECTION_PROCESSOR = "STAGE6_4C_ANALOGUE_SELECTOR_V1"
SELECTION_POLICY_ID = "S6ANSELPOL_STAGE6_4C_V1"
SELECTION_POLICY_HASH = "36dfffc457342314e0907e31bebb7e54bd21747134dbaded7d34b822e6bcc9b2"
COMPARISON_CONTRACT_VERSION = "STAGE6_ANALOGUE_COMPARISON_CONTRACT_V1"
COMPARISON_CONTRACT_HASH = "115ae49b1ac8cc005ca1bdb876576600603d593ec2e1ed09c2fee4c6d79b1401"
METRIC = "STAGE6_MIXED_DISTANCE_V1"
HISTORICAL_BLOB = "85a2b0d00cacd6a3caea484e3ef3071eb16fe01d"
MARKET_BLOB = "a141b221228718b8276b3d05b2f028d21adcfc3f"
EXPECTED_POLICY_HASH_V1 = "3aa6bc70bfd1a8b29287cd609282d6a5d00c9839aeebaaa09d5761b8ce1d0a24"
EXPECTED_OUTCOME_DEFINITION_HASH_V1 = "2535f09dacd8d67215121d4a60a925885ab53ba8e771e8df355c4c14b12ea85a"


def _blob(path):
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def _load(name, expected):
    value = json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"))
    digest = canonical_hash(value)
    if digest != expected:
        raise Stage6AnalogueOutcomeError("ANALOGUE_OUTCOME_CONFIGURATION_HASH_INVALID")
    return value, canonical_json(value), digest


def verify_selection_engine_ancestry():
    repo = Path(__file__).resolve().parents[2]
    try:
        merge_base = subprocess.check_output(["git", "merge-base", "HEAD", SELECTION_ENGINE_COMMIT], cwd=repo, text=True).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Stage6AnalogueOutcomeError("SELECTION_ENGINE_ANCESTRY_UNVERIFIED") from exc
    if merge_base != SELECTION_ENGINE_COMMIT:
        raise Stage6AnalogueOutcomeError("SELECTION_ENGINE_NOT_ANCESTOR")


def load_policy():
    value, text, digest = _load("analogue_outcome_policy_v1.json", EXPECTED_POLICY_HASH_V1)
    expected = (POLICY_ID, PROCESSOR_VERSION, AUTHORITY, BASELINE_COMMIT, SELECTION_ENGINE_COMMIT)
    actual = tuple(value.get(key) for key in ("policy_id", "processor_version", "authority", "development_baseline", "selection_engine_commit"))
    if actual != expected:
        raise Stage6AnalogueOutcomeError("ANALOGUE_OUTCOME_POLICY_INVALID")
    contracts = Path(__file__).resolve().parents[1] / "contracts"
    if _blob(contracts / "historical_analogue.schema.json") != HISTORICAL_BLOB or _blob(contracts / "market_context.schema.json") != MARKET_BLOB:
        raise Stage6AnalogueOutcomeError("ANALOGUE_OUTCOME_FROZEN_CONTRACT_CHANGED")
    verify_selection_engine_ancestry()
    return value, text, digest


def load_outcome_definition():
    value, text, digest = _load("analogue_outcome_definition_v1.json", EXPECTED_OUTCOME_DEFINITION_HASH_V1)
    if value.get("definition_version") != OUTCOME_DEFINITION_VERSION or value.get("automatic_calculation") is not False:
        raise Stage6AnalogueOutcomeError("ANALOGUE_OUTCOME_DEFINITION_INVALID")
    return value, text, digest
