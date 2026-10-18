from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date, datetime, time, timedelta
import importlib.util
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verified_official_current(decision: dict) -> bool:
    evidence = decision.get("evidence") or {}
    return isinstance(evidence, dict) and evidence.get("official_current") is True


def validate_recovery_snapshot(snapshot: dict) -> None:
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("run"), dict) or not isinstance(snapshot.get("candidates"), list) or not snapshot["candidates"]:
        raise ValueError("ACTUAL_NONEMPTY_RUN_SNAPSHOT_REQUIRED")
    if len(snapshot["candidates"]) != 200:
        raise ValueError("EXPECTED_200_SYMBOLS_FOR_RECOVERY_COMPARISON")
    if any(not isinstance(row, dict) for row in snapshot["candidates"]):
        raise ValueError("INVALID_CANDIDATE")
    symbols = [str(row.get("symbol") or "").upper().removesuffix(".NS") for row in snapshot["candidates"]]
    if any(not sym for sym in symbols) or len(set(symbols)) != 200:
        raise ValueError("UNIQUE_200_SYMBOLS_REQUIRED")


def metric_rows(items: list[dict]) -> dict:
    return {
        "stocks_analyzed": len(items),
        "fundamental_available": sum(bool(x["fundamental"].get("available")) for x in items),
        "missing_debt_equity_outside_financial_domain": sum(
            not x["decision"].get("financial_domain")
            and x["fundamental"].get("balance_sheet", {}).get("debt_equity_ratio") is None
            for x in items
        ),
        "strong_or_healthy_business_states": sum(
            x["decision"].get("business_health") in {"STRONG", "HEALTHY"} for x in items
        ),
        "mixed_fundamental_events": sum(
            (x["fundamental"].get("risk_event") or {}).get("event_profile") == "MIXED_DIRECTIONAL"
            for x in items
        ),
        "strong_deterioration_transitions": sum(
            (x["fundamental"].get("risk_event") or {}).get("strong_deterioration_transition") is True
            for x in items
        ),
        "executable_buy_recommendations": sum(
            x["decision"].get("executable") is True and "BUY" in str(x["decision"].get("final_action"))
            for x in items
        ),
        "invalid_or_stale_source_records": sum(
            x["fundamental"].get("available") is True
            and x["fundamental"].get("filing_freshness") != "CURRENT_FOR_DECISION_TIME"
            for x in items
        ),
        "recommendation_rule_violations": sum(bool(x.get("rule_violations")) for x in items),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--installed-engine", type=Path, required=True)
    parser.add_argument("--router", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(args.installed_engine))
    from stock_app import fundamental_v3  # type: ignore
    router = load_module("recovered_live_decision_v1", args.router)
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    validate_recovery_snapshot(snapshot)
    run = snapshot.get("run") or {}
    session = date.fromisoformat(run["market_session"])
    decision_ts = datetime.combine(
        session + timedelta(days=1), time(5, 29, 59, 999999), tzinfo=ZoneInfo("Asia/Kolkata")
    )

    before_items = []
    after_items = []
    details = []
    for candidate in snapshot.get("candidates") or []:
        before = candidate.get("live_decision") or {}
        before_fund = ((before.get("evidence") or {}).get("fundamental") or {})
        technical = ((before.get("evidence") or {}).get("technical") or {})
        price_context = ((before.get("evidence") or {}).get("price_context") or {})
        legacy = ((before.get("evidence") or {}).get("legacy_production_evidence") or None)
        basis = before_fund.get("reporting_basis") or "CONSOLIDATED"
        after_fund = fundamental_v3.analyze(
            args.data_root,
            candidate.get("symbol"),
            decision_timestamp=decision_ts.isoformat(),
            latest_price=candidate.get("latest_close"),
            basis_preference=basis,
        )
        route_args = dict(
            price_context=price_context,
            official_current=verified_official_current(before),
            legacy=legacy,
        )
        control = router.route(
            candidate.get("symbol"),
            run.get("market_session"),
            technical,
            before_fund,
            **route_args,
        )
        recomputed_after = router.route(
            candidate.get("symbol"),
            run.get("market_session"),
            technical,
            after_fund,
            **route_args,
        )
        before_debt = (before_fund.get("balance_sheet") or {}).get("debt_equity_ratio")
        after_debt = (after_fund.get("balance_sheet") or {}).get("debt_equity_ratio")
        fundamental_changed = (
            bool(before_fund.get("available")) != bool(after_fund.get("available"))
            or before_fund.get("domain") != after_fund.get("domain")
            or before_debt != after_debt
        )
        # The serialized snapshot is authoritative for unchanged symbols.  A
        # control reroute can differ when an installed router revision is newer
        # than the router that created the snapshot; that drift must not be
        # misattributed to recovered financial data.
        after = recomputed_after if fundamental_changed else before
        violations = []
        if after.get("executable") and not after_fund.get("available"):
            violations.append("EXECUTABLE_WITHOUT_FUNDAMENTALS")
        if after.get("executable") and after.get("financial_domain"):
            adapter = after_fund.get("financial_domain_adapter") or {}
            if adapter.get("safety_ready") is not True:
                violations.append("FINANCIAL_DOMAIN_WITHOUT_VALIDATED_SAFETY_POLICY")
        if after.get("executable") and after.get("structural_deterioration"):
            violations.append("EXECUTABLE_DURING_STRUCTURAL_DETERIORATION")

        before_items.append({"fundamental": before_fund, "decision": before, "rule_violations": []})
        after_items.append({"fundamental": after_fund, "decision": after, "rule_violations": violations})
        details.append({
            "symbol": candidate.get("symbol"),
            "before_action": before.get("final_action"),
            "after_action": after.get("final_action"),
            "before_executable": before.get("executable"),
            "after_executable": after.get("executable"),
            "before_fundamental_available": before_fund.get("available", False),
            "after_fundamental_available": after_fund.get("available", False),
            "before_domain": before_fund.get("domain"),
            "after_domain": after_fund.get("domain"),
            "before_business_health": before.get("business_health"),
            "after_business_health": after.get("business_health"),
            "before_event_state": before.get("fundamental_event_state"),
            "after_event_state": after.get("fundamental_event_state"),
            "before_debt_equity": (before_fund.get("balance_sheet") or {}).get("debt_equity_ratio"),
            "after_debt_equity": (after_fund.get("balance_sheet") or {}).get("debt_equity_ratio"),
            "fundamental_changed": fundamental_changed,
            "control_reroute_action": control.get("final_action"),
            "control_matches_snapshot": control.get("final_action") == before.get("final_action"),
            "filing_quarter": after_fund.get("quarter_end"),
            "filing_availability_ts": after_fund.get("effective_availability_ts"),
            "reporting_basis": after_fund.get("reporting_basis"),
            "fundamental_status": after_fund.get("status"),
            "rule_violations": violations,
        })

    before_metrics = metric_rows(before_items)
    after_metrics = metric_rows(after_items)
    changes = [row for row in details if row["before_action"] != row["after_action"]]
    recovered = [
        row for row in details
        if not row["before_fundamental_available"] and row["after_fundamental_available"]
    ]
    report = {
        "artifact_type": "LIVE_SNAPSHOT_OFFICIAL_RECOVERY_BEFORE_AFTER_V1",
        "authority": "SHADOW_ONLY",
        "run_id": run.get("run_id"),
        "market_session": run.get("market_session"),
        "decision_timestamp": decision_ts.isoformat(),
        "before": before_metrics,
        "after": after_metrics,
        "delta": {key: after_metrics[key] - before_metrics[key] for key in before_metrics},
        "fundamental_recovered_symbols": [row["symbol"] for row in recovered],
        "recommendation_change_count": len(changes),
        "recommendation_changes": changes,
        "control_reroute_parity_failure_count": sum(not row["control_matches_snapshot"] for row in details),
        "control_reroute_parity_failure_symbols": [
            row["symbol"] for row in details if not row["control_matches_snapshot"]
        ],
        "after_action_counts": dict(Counter(row["after_action"] for row in details)),
        "production_promoted": False,
        "automatic_yfinance_fallback": False,
    }
    (args.out / "before_after.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (args.out / "symbol_details.json").write_text(json.dumps(details, indent=2, sort_keys=True), encoding="utf-8")
    with (args.out / "symbol_details.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = [key for key in details[0] if key != "rule_violations"] + ["rule_violations"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in details:
            writer.writerow({**row, "rule_violations": ";".join(row["rule_violations"])})
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
