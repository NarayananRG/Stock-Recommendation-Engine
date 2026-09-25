"""Offline Stage 6.0 documentation/contract consistency validation only."""
from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
EXPECTED_COMMIT = "74b2710f0e19bd403978da81e87f25a3059ace06"
EXPECTED_CONTROL = "stage5d5-live-paper-runner-baseline"
SCHEMAS = (
    "source_registry.schema.json", "evidence.schema.json", "event.schema.json",
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


def main() -> None:
    parsed = {}
    for name in (*SCHEMAS, "stage6_contract.json"):
        parsed[name] = json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
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
    require(enum_at(parsed["source_registry.schema.json"], "$defs", "source", "properties", "authority_level", "enum") == authority, "source authority enum")
    require(enum_at(parsed["evidence.schema.json"], "properties", "authority_level", "enum") == authority, "evidence authority enum")
    events = enum_at(parsed["event.schema.json"], "properties", "event_type", "enum")
    require({"EARNINGS_BEAT", "FRAUD_ALLEGATION", "WAR_ESCALATION", "OIL_SHOCK", "RATE_HIKE", "SUPPLY_CHAIN_DISRUPTION", "OTHER"} <= events, "event taxonomy")
    causality = enum_at(parsed["event.schema.json"], "properties", "causality_assessment", "enum")
    require(causality == {"CONFIRMED_CAUSE", "PLAUSIBLE_CONTRIBUTOR", "CORRELATED_MARKET_MOVE", "NO_SUPPORTED_CAUSE_FOUND"}, "causality enum")
    decisions = enum_at(parsed["shadow_decision.schema.json"], "properties", "decision", "enum")
    require({"ENTRY_VALID", "CANCEL_ENTRY", "HOLD", "REDUCE", "EXIT"} <= decisions, "decision enum")
    require(parsed["shadow_decision.schema.json"]["properties"]["authority_mode"]["const"] == "SHADOW_ONLY", "shadow authority")
    require(parsed["historical_analogue.schema.json"]["properties"]["authority_mode"]["const"] == "SHADOW_ONLY", "analogue authority")
    require(parsed["portfolio_context.schema.json"]["properties"]["cash_is_valid_allocation"]["const"] is True, "cash allocation")
    require("publication_timestamp_utc <= observed_timestamp_utc <= retrieved_timestamp_utc" in parsed["evidence.schema.json"]["x-stage6-invariants"][0], "timestamp invariant")

    for python_file in ROOT.rglob("*.py"):
        tree = ast.parse(python_file.read_text(encoding="utf-8"), filename=str(python_file))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        require(not imports & NETWORK_MODULES, f"network import prohibited: {python_file}")

    print(json.dumps({
        "stage": "6.0", "result": "PASS", "schemas_parsed": len(SCHEMAS),
        "authority": "SHADOW_ONLY", "production_control_commit": EXPECTED_COMMIT,
        "network_imports": 0, "trading_implementation": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
