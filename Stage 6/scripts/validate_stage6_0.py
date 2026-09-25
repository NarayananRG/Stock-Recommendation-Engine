"""Offline Stage 6.0/6.0A documentation and contract validation only."""
from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
EXPECTED_COMMIT = "74b2710f0e19bd403978da81e87f25a3059ace06"
EXPECTED_CONTROL = "stage5d5-live-paper-runner-baseline"
SCHEMAS = (
    "entity_registry.schema.json", "source_registry.schema.json", "evidence.schema.json", "event.schema.json",
    "exposure.schema.json", "market_context.schema.json", "historical_analogue.schema.json",
    "trade_thesis.schema.json", "portfolio_context.schema.json", "shadow_decision.schema.json",
)
NETWORK_MODULES = {"requests", "urllib", "http", "httpx", "aiohttp", "socket", "yfinance"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def enum_at(document: dict, *path: str) -> set[str]:
    value: object = document
    for key in path:
        require(isinstance(value, dict) and key in value, "missing schema path: " + ".".join(path))
        value = value[key]
    require(isinstance(value, list), "enum is not a list: " + ".".join(path))
    return set(value)


def required_at(document: dict, *path: str) -> set[str]:
    value: object = document
    for key in path:
        require(isinstance(value, dict) and key in value, "missing schema path: " + ".".join(path))
        value = value[key]
    require(isinstance(value, list), "required is not a list: " + ".".join(path))
    return set(value)


def validate_schema_structure(document: dict, name: str) -> None:
    """Check local references and required/property consistency without I/O."""
    def visit(value: object) -> None:
        if isinstance(value, dict):
            if "required" in value and "properties" in value:
                require(set(value["required"]) <= set(value["properties"]), f"unknown required property: {name}")
            reference = value.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/"):
                target: object = document
                for token in reference[2:].split("/"):
                    token = token.replace("~1", "/").replace("~0", "~")
                    require(isinstance(target, dict) and token in target, f"unresolved reference {reference}: {name}")
                    target = target[token]
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(document)


def main() -> None:
    parsed = {}
    for name in (*SCHEMAS, "stage6_contract.json"):
        parsed[name] = json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
        if name.endswith(".schema.json"):
            validate_schema_structure(parsed[name], name)
    result = json.loads((ROOT / "results/stage6_0_architecture_contract.json").read_text(encoding="utf-8"))

    contract = parsed["stage6_contract.json"]
    require(contract["stage"] == "6.0" and contract["authority"] == "SHADOW_ONLY", "authority contract")
    require(contract["production_control"] == EXPECTED_CONTROL, "production-control tag")
    require(contract["production_control_commit"] == EXPECTED_COMMIT, "production-control commit")
    require(contract["schemas"] == list(SCHEMAS), "schema inventory")
    for flag in ("network_calls", "trading_actions", "broker_execution", "production_decision_influence", "data_acquisition_implemented", "stage5d5_mutation_allowed"):
        require(contract[flag] is False, "unsafe contract flag: " + flag)
    require(result["authority"] == "SHADOW_ONLY" and result["production_control_commit"] == EXPECTED_COMMIT, "result identity")

    authority = {"PRIMARY_OFFICIAL", "AUTHORITATIVE_INDEPENDENT", "DISCOVERY", "UNVERIFIED"}
    entity = parsed["entity_registry.schema.json"]
    entity_types = enum_at(entity, "$defs", "entity", "properties", "entity_type", "enum")
    require({"COMPANY", "INDEX", "SECTOR", "SUBSECTOR", "COMMODITY", "CURRENCY", "COUNTRY", "REGULATOR", "GOVERNMENT_BODY", "PERSON", "CORPORATE_GROUP"} <= entity_types, "entity taxonomy")
    require({"exchange", "ticker", "effective_from", "effective_to"} <= required_at(entity, "$defs", "ticker_mapping", "required"), "PIT ticker mapping")
    require({"alias", "alias_type", "effective_from", "effective_to"} <= required_at(entity, "$defs", "alias", "required"), "PIT alias mapping")
    registry_snapshot_fields = {"registry_snapshot_id", "registry_version", "as_of_timestamp", "previous_registry_hash", "registry_hash"}
    require(registry_snapshot_fields <= set(entity["required"]), "entity registry snapshot identity")
    require({"entity_record_version", "effective_from", "reviewed_at", "previous_version_hash", "record_hash"} <= required_at(entity, "$defs", "entity", "required"), "entity version identity")

    source = parsed["source_registry.schema.json"]
    require(enum_at(parsed["source_registry.schema.json"], "$defs", "source", "properties", "authority_level", "enum") == authority, "source authority enum")
    require(registry_snapshot_fields <= set(source["required"]), "source registry snapshot identity")
    require({"source_record_version", "effective_from", "effective_to", "reviewed_at_utc", "access_method", "machine_endpoint_type", "licensing_or_terms_status", "automation_allowed_status", "previous_version_hash", "record_hash"} <= required_at(source, "$defs", "source", "required"), "source version identity")

    evidence = parsed["evidence.schema.json"]
    require(enum_at(parsed["evidence.schema.json"], "properties", "authority_level", "enum") == authority, "evidence authority enum")
    evidence_registry_fields = {"source_registry_snapshot_id", "source_registry_version", "source_registry_hash", "entity_registry_snapshot_id", "entity_registry_version", "entity_registry_hash", "source_record_version", "source_record_hash"}
    require(evidence_registry_fields <= set(evidence["required"]), "evidence registry binding")
    require({"raw_payload_reference", "raw_payload_hash", "document_version", "record_hash"} <= set(evidence["required"]), "evidence version identity")
    require(evidence["properties"]["source_registry_version"]["type"] == "integer" and evidence["properties"]["entity_registry_version"]["type"] == "integer", "registry version type parity")
    failure_branch = next(branch for branch in evidence["allOf"] if set(branch.get("if", {}).get("properties", {}).get("retrieval_status", {}).get("enum", [])) == {"NOT_FOUND", "ACCESS_DENIED", "FAILED"})
    require({"failure_reason", "failure_stage", "attempted_at_utc"} <= set(failure_branch["then"]["properties"]), "failed acquisition audit fields")
    require("null" in evidence["$defs"]["nullable_hash"]["type"] and "null" in evidence["properties"]["raw_payload_reference"]["type"], "no-payload failure representable")
    require("runtime validation" in evidence["x-stage6-invariants"][0], "timestamp runtime invariant")

    events = enum_at(parsed["event.schema.json"], "properties", "event_type", "enum")
    require({"EARNINGS_BEAT", "FRAUD_ALLEGATION", "SHORT_SELLER_ALLEGATION", "RATING_UPGRADE", "RATING_DOWNGRADE", "DEFAULT_EVENT", "INSOLVENCY_EVENT", "CYBERSECURITY_EVENT", "PRODUCT_RECALL", "TAX_OR_DUTY_CHANGE", "WAR_ESCALATION", "OIL_SHOCK", "RATE_HIKE", "SUPPLY_CHAIN_DISRUPTION", "OTHER"} <= events, "event taxonomy")
    require({"event_version", "previous_event_version_hash", "record_hash", "last_updated_timestamp", "entity_resolution_version"} <= set(parsed["event.schema.json"]["required"]), "event version identity")
    causality = enum_at(parsed["event.schema.json"], "properties", "causality_assessment", "enum")
    require(causality == {"CONFIRMED_CAUSE", "PLAUSIBLE_CONTRIBUTOR", "CORRELATED_MARKET_MOVE", "NO_SUPPORTED_CAUSE_FOUND"}, "causality enum")
    decisions = enum_at(parsed["shadow_decision.schema.json"], "properties", "decision", "enum")
    require({"ENTRY_VALID", "CANCEL_ENTRY", "HOLD", "REDUCE", "EXIT"} <= decisions, "decision enum")
    require(parsed["shadow_decision.schema.json"]["properties"]["authority_mode"]["const"] == "SHADOW_ONLY", "shadow authority")
    require(parsed["historical_analogue.schema.json"]["properties"]["authority_mode"]["const"] == "SHADOW_ONLY", "analogue authority")
    analogue = parsed["historical_analogue.schema.json"]
    require({"analogue_engine_version", "code_commit", "feature_contract_version", "feature_snapshot_hash", "similarity_metric", "feature_weights", "selection_thresholds", "selected_analogues", "selection_input_hash", "outcome_unit", "record_hash"} <= set(analogue["required"]), "analogue reproducibility")
    require({"analogue_id", "historical_as_of_timestamp", "entity_id", "event_id", "similarity_score", "distance", "input_snapshot_hash"} <= set(analogue["properties"]["selected_analogues"]["items"]["required"]), "selected analogue identity")
    require("unit" in analogue["$defs"]["distribution"]["required"], "explicit analogue outcome units")
    require(analogue["properties"]["recovery_time"]["allOf"][1]["properties"]["unit"]["const"] == "TRADING_SESSIONS", "recovery time unit")

    thesis = parsed["trade_thesis.schema.json"]
    require({"thesis_engine_version", "code_commit", "decision_cutoff", "input_records", "fill_references", "aggregate_fill", "previous_version_hash", "record_hash"} <= set(thesis["required"]), "thesis reproducibility")
    require({"record_id", "record_hash", "record_type"} <= set(thesis["$defs"]["input_record_binding"]["required"]), "thesis direct input binding")
    require("input_record_ids" not in thesis["properties"] and "input_record_hashes" not in thesis["properties"], "parallel thesis inputs prohibited")
    require({"transaction_id", "fill_date", "quantity", "price", "source_system"} <= set(thesis["$defs"]["fill_reference"]["required"]), "multiple fill references")

    shadow = parsed["shadow_decision.schema.json"]
    require({"decision_engine_version", "code_commit", "decision_cutoff_timestamp", "input_records", "source_registry_version", "entity_registry_version", "record_hash"} <= set(shadow["required"]), "shadow reproducibility")
    require({"record_id", "record_hash", "record_type"} <= set(shadow["$defs"]["input_record_binding"]["required"]), "shadow direct input binding")
    require("input_record_ids" not in shadow["properties"] and "input_record_hashes" not in shadow["properties"], "parallel shadow inputs prohibited")

    portfolio = parsed["portfolio_context.schema.json"]
    require(parsed["portfolio_context.schema.json"]["properties"]["cash_is_valid_allocation"]["const"] is True, "cash allocation")
    require({"recommendation_id", "thesis_id", "transaction_or_fill_ids", "current_price", "average_cost", "sector_entity_id", "subsector_entity_id"} <= set(portfolio["$defs"]["position"]["required"]), "position provenance")
    require({"method", "return_frequency", "lookback_window", "minimum_observations", "data_cutoff_timestamp"} <= set(portfolio["$defs"]["correlation"]["required"]), "correlation provenance")
    require("unit" in portfolio["$defs"]["exposure"]["required"] and "denominator_definition" in portfolio["$defs"]["exposure"]["required"], "exposure units")

    market = parsed["market_context.schema.json"]
    require({"value", "unit", "observed_at_utc", "method"} <= set(market["$defs"]["measurement"]["required"]), "market measurement metadata")
    require("publication_timestamp_utc <= observed_timestamp_utc <= retrieved_timestamp_utc" in parsed["evidence.schema.json"]["x-stage6-invariants"][0], "timestamp invariant")

    exposure = parsed["exposure.schema.json"]
    require(exposure["properties"]["schema_version"]["const"] == "STAGE6_EXPOSURE_V2", "exposure V2")
    require({"exposure_version", "company_entity_id", "sector_entity_id", "subsector_entity_id", "entity_registry_snapshot_id", "entity_registry_version", "entity_registry_hash", "previous_version_hash", "record_hash"} <= set(exposure["required"]), "exposure entity/version identity")
    require({"value", "unit", "basis", "declared_unit"} <= set(exposure["$defs"]["measurement"]["required"]), "exposure measurement contract")
    require({"QUANTITATIVE", "QUALITATIVE"} == enum_at(exposure, "$defs", "assertion", "properties", "value_type", "enum"), "exposure value forms")
    require(exposure["$defs"]["assertion"]["properties"].get("value") is None, "unrestricted exposure value prohibited")

    expected_gates = {"ENTITY_IDENTITY_CONTRACT", "VERSIONED_SOURCE_REGISTRY", "EVIDENCE_VERSION_IDENTITY", "ANALOGUE_REPRODUCIBILITY_CONTRACT", "EXPLICIT_MEASUREMENT_UNITS", "MULTI_FILL_THESIS_CONTRACT", "SHADOW_DECISION_REPRODUCIBILITY", "PORTFOLIO_CONTEXT_PROVENANCE", "REGISTRY_SNAPSHOT_IDENTITY", "EVIDENCE_REGISTRY_BINDING", "FAILED_ACQUISITION_REPRESENTABLE", "INPUT_RECORD_ID_HASH_BINDING", "EXPOSURE_MEASUREMENT_CONTRACT", "EXPOSURE_ENTITY_IDENTITY", "FORWARD_COMPATIBLE_IMPLEMENTATION_BOUNDARY", "ARCHITECTURE_VALIDATOR_SCOPE"}
    require(all(result["validation_gates"].get(gate) == "PASS" for gate in expected_gates), "6.0C result gates")
    require(result["schema_count"] == len(SCHEMAS), "result schema count")

    # Stage 6.0 validates architecture-owned executable code only. Future
    # implementation stages enforce their own stage-specific runtime/network
    # boundaries and must not be globally policed by this frozen validator.
    architecture_scripts = {Path(__file__).resolve()}
    for python_file in architecture_scripts:
        tree = ast.parse(python_file.read_text(encoding="utf-8"), filename=str(python_file))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        require(not imports & NETWORK_MODULES, f"network import prohibited: {python_file}")

    print(json.dumps({
        "stage": "6.0C", "result": "PASS", "schemas_parsed": len(SCHEMAS),
        "authority": "SHADOW_ONLY", "production_control_commit": EXPECTED_COMMIT,
        "network_imports": 0, "trading_implementation": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
