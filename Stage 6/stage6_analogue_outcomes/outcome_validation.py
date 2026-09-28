from stage6_ingestion.canonical import canonical_hash, without

from .errors import AnalogueOutcomeIntegrityFailure
from .outcome_builder import HORIZONS, RETURN_NAMES, SAFETY
from .policy import AUTHORITY, OUTCOME_DEFINITION_VERSION, POLICY_ID, PROCESSOR_VERSION, SCHEMA_VERSION, SELECTION_ENGINE_COMMIT


def validate_outcome_record(record):
    expected = (SCHEMA_VERSION, POLICY_ID, PROCESSOR_VERSION, AUTHORITY, OUTCOME_DEFINITION_VERSION, SELECTION_ENGINE_COMMIT)
    actual = tuple(record.get(key) for key in ("schema_version", "policy_id", "processor_version", "authority", "outcome_definition_version", "selection_engine_commit"))
    if actual != expected:
        raise AnalogueOutcomeIntegrityFailure("ANALOGUE_OUTCOME_IDENTITY_INVALID")
    attachments = record.get("analogue_attachments", [])
    if len(attachments) != record.get("selected_analogue_count"):
        raise AnalogueOutcomeIntegrityFailure("ANALOGUE_OUTCOME_COVERAGE_INVALID")
    if [item.get("selection_rank") for item in attachments] != list(range(1, len(attachments) + 1)):
        raise AnalogueOutcomeIntegrityFailure("ANALOGUE_OUTCOME_RANK_INVALID")
    if len({item.get("analogue_id") for item in attachments}) != len(attachments):
        raise AnalogueOutcomeIntegrityFailure("ANALOGUE_OUTCOME_DUPLICATE_ANALOGUE")
    for attachment in attachments:
        if set(attachment.get("horizons", {})) != set(HORIZONS):
            raise AnalogueOutcomeIntegrityFailure("ANALOGUE_OUTCOME_HORIZONS_INVALID")
        if any(set(attachment["horizons"][horizon]) != set(RETURN_NAMES) for horizon in HORIZONS):
            raise AnalogueOutcomeIntegrityFailure("ANALOGUE_OUTCOME_MEASUREMENTS_INVALID")
    if any(record.get(key) != value for key, value in SAFETY.items()) or record.get("pit_verified") is not True or record.get("leakage_status") != "PASS":
        raise AnalogueOutcomeIntegrityFailure("ANALOGUE_OUTCOME_SAFETY_INVALID")
    core = without(record, "attachment_set_id", "attachment_set_hash", "logical_attachment_key", "record_hash")
    digest = canonical_hash(core)
    if record.get("attachment_set_hash") != digest or record.get("attachment_set_id") != "S6ANOUT_" + digest[:24]:
        raise AnalogueOutcomeIntegrityFailure("ANALOGUE_OUTCOME_ATTACHMENT_HASH_INVALID")
    if record.get("record_hash") != canonical_hash(without(record, "record_hash")):
        raise AnalogueOutcomeIntegrityFailure("ANALOGUE_OUTCOME_RECORD_HASH_INVALID")
    return record
