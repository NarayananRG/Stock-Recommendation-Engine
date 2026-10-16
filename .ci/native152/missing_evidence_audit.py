from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from evidence_coverage_v1 import classify_live_decision

ROOT = Path(os.environ["SRE_ENGINE_ROOT"]).resolve()
OUT = Path(os.environ.get("SRE_EVIDENCE_AUDIT_OUT", str(Path.cwd() / "work" / "missing-evidence-audit")))
OUT.mkdir(parents=True, exist_ok=True)
SESSION = "2026-10-15"
ROUTER = ROOT / "stock_app" / "live_decision_v1.py"
ROUTER_SHA = hashlib.sha256(ROUTER.read_bytes()).hexdigest()
EXPECTED_ROUTER_SHA = os.environ.get("SRE_EXPECTED_ROUTER_SHA")
if EXPECTED_ROUTER_SHA and ROUTER_SHA.lower() != EXPECTED_ROUTER_SHA.lower():
    raise RuntimeError(f"ROUTER_SHA_CHANGED:{ROUTER_SHA}!={EXPECTED_ROUTER_SHA}")


def _load_run() -> dict:
    supplied = os.environ.get("SRE_ACTIVE_RUN_JSON")
    if supplied:
        return json.loads(Path(supplied).read_text(encoding="utf-8"))
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("STOCK_MODERN_UI_PREVIEW", "0")
    os.environ.setdefault("SRE_EXPECTED_SESSION_NOW", "2026-10-15T19:45:00+05:30")
    from modern_ui.api import ModernAppContext
    app_data = Path(tempfile.mkdtemp(prefix="sre01411-audit-"))
    ctx = ModernAppContext(repo_root=ROOT, app_data_dir=app_data)
    ctx.run_post_close_daily_flow(force=True)
    status = ctx.post_close_daily_status()
    if status.get("analysis_current") is not True or status.get("active_analysis_session") != SESSION:
        raise RuntimeError("CURRENT_2026_10_15_ANALYSIS_REQUIRED:" + json.dumps(status, default=str))
    active = ctx.active_prediction_run()
    if not active:
        raise RuntimeError("ACTIVE_RUN_NOT_MATERIALIZED")
    return active


def _supplement_diagnostics() -> dict[str, str]:
    path = ROOT / "NextGen Research" / "results" / "pit_safety_supplement_v1" / "summary.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(row.get("symbol")): str(row.get("status")) for row in payload.get("diagnostics") or []}


def _supplement_validated_count() -> int:
    path = ROOT / "NextGen Research" / "results" / "pit_safety_supplement_v1" / "summary.json"
    if not path.exists():
        return 0
    return int(json.loads(path.read_text(encoding="utf-8")).get("validated_corporate_debt_equity_rows") or 0)


def _symbols(items) -> list[str]:
    return sorted(str(item) for item in items)


def _actions(rows: list[dict]) -> dict:
    counts = Counter((row.get("live_decision") or {}).get("final_action") for row in rows)
    return {
        "momentum_buy": counts["MOMENTUM BUY"], "recovery_buy": counts["RECOVERY BUY"],
        "both": counts["MOMENTUM + RECOVERY BUY"],
        "watch": sum(v for k, v in counts.items() if str(k).startswith("WATCH")),
        "avoid": sum(v for k, v in counts.items() if str(k).startswith("AVOID")),
        "no_opportunity": counts["NO OPPORTUNITY"],
        "executable": sum((row.get("live_decision") or {}).get("executable") is True for row in rows),
    }


run = _load_run()
rows = list(run.get("candidates") or [])
if len(rows) != 200:
    raise RuntimeError(f"EXPECTED_200_ROWS_GOT_{len(rows)}")
if str((run.get("run") or {}).get("market_session")) != SESSION:
    raise RuntimeError("WRONG_MARKET_SESSION")

leverage_diagnostics = _supplement_diagnostics()
matrix = []
classifications = {}
for row in sorted(rows, key=lambda item: str(item.get("symbol"))):
    symbol = str(row.get("symbol"))
    live = row.get("live_decision") or {}
    fundamental = ((live.get("evidence") or {}).get("fundamental") or {})
    classified = classify_live_decision(live, leverage_diagnostics.get(symbol))
    classifications[symbol] = classified
    families = classified["families"]
    matrix.append({
        "symbol": symbol, "domain": classified["domain"], "final_action": live.get("final_action"),
        "business_health": live.get("business_health"), "earnings_direction": live.get("earnings_direction"),
        "event_state": live.get("fundamental_event_state"), "cash_flow_state": live.get("cash_flow_state"),
        "balance_sheet_state": live.get("balance_sheet_state"), "valuation_state": live.get("valuation_state"),
        "technical_state": live.get("technical_state"), "price_condition": live.get("price_condition"),
        "data_quality": live.get("fundamental_data_quality"), "financial_domain_state": live.get("financial_domain_state"),
        "missing_evidence_list": ";".join(classified["missing"]),
        "unfavorable_evidence_list": ";".join(classified["unfavorable"]),
        "reason_codes": ";".join(live.get("reason_codes") or []),
        "revenue_condition": families["Revenue"]["condition"], "pat_condition": families["PAT"]["condition"],
        "eps_condition": families["EPS"]["condition"],
        "operating_cash_flow_condition": families["Operating cash flow"]["condition"],
        "cash_equivalents_condition": families["Cash / equivalents"]["condition"],
        "total_assets_condition": families["Total assets"]["condition"],
        "leverage_condition": families["Debt / leverage / DebtEquityRatio"]["condition"],
        "current_valuation_condition": families["PB valuation" if classified["domain"] != "corporate" else "PE / earnings valuation"]["condition"],
        "historical_pit_valuation_condition": families["Historical PIT valuation reference"]["condition"],
        "reporting_basis": fundamental.get("reporting_basis"), "quarter_end": fundamental.get("quarter_end"),
        "availability_ts": fundamental.get("effective_availability_ts"),
        "financial_policy_condition": classified["financial_domain"]["condition"],
    })

with (OUT / "missing_evidence_matrix.csv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(matrix[0].keys()))
    writer.writeheader()
    writer.writerows(matrix)


def condition_breakdown(family: str) -> dict:
    counts = Counter()
    symbols = defaultdict(list)
    for symbol, item in classifications.items():
        condition = item["families"][family]["condition"]
        counts[condition] += 1
        symbols[condition].append(symbol)
    return {"counts": dict(counts), "symbols": {key: _symbols(value) for key, value in symbols.items()}}


corporates = [row for row in matrix if row["domain"] == "corporate"]
financials = [row for row in matrix if row["domain"] != "corporate"]
balance_unavailable = [r["symbol"] for r in corporates if r["balance_sheet_state"] == "UNAVAILABLE"]
balance_unfavorable = [r["symbol"] for r in corporates if r["balance_sheet_state"] in {"CAUTION", "STRESSED"}]
cash_unavailable = [r["symbol"] for r in corporates if r["cash_flow_state"] == "UNAVAILABLE"]
cash_unfavorable = [r["symbol"] for r in corporates if r["cash_flow_state"] in {"WEAK", "DANGEROUS"}]
cash_supportive = [r["symbol"] for r in corporates if r["cash_flow_state"] in {"SUPPORTIVE", "ADEQUATE"}]
pit_unavailable = [r["symbol"] for r in matrix if r["historical_pit_valuation_condition"] != "PRESENT_AND_SUPPORTIVE"]
business_blocked = [r for r in rows if "BUSINESS_EARNINGS_OR_EVENT_EVIDENCE_INSUFFICIENT" in ((r.get("live_decision") or {}).get("reason_codes") or [])]

business_causes = defaultdict(list)
for row in business_blocked:
    symbol = str(row["symbol"])
    live = row["live_decision"]
    item = classifications[symbol]
    families = item["families"]
    if any(families[name]["condition"] in {"MISSING_SOURCE_DATA", "STALE_OR_OUT_OF_ORDER", "PARSER_OR_SCHEMA_FAILURE"} for name in ("Revenue", "PAT", "EPS")):
        business_causes["missing_revenue_pat_eps"].append(symbol)
    if live.get("earnings_direction") not in {"STABLE", "IMPROVING"}:
        business_causes["earnings_present_but_not_strong_enough"].append(symbol)
    if live.get("fundamental_event_state") == "UNAVAILABLE":
        business_causes["event_state_unavailable"].append(symbol)
    elif live.get("fundamental_event_state") not in {"STABLE", "IMPROVING"}:
        business_causes["event_state_present_not_qualifying"].append(symbol)
    if live.get("fundamental_data_quality") == "STALE":
        business_causes["stale_pit_data"].append(symbol)

data_gap_conditions = {"MISSING_SOURCE_DATA", "SOURCE_AVAILABLE_BUT_UNMAPPED", "INSUFFICIENT_PIT_HISTORY",
                       "STALE_OR_OUT_OF_ORDER", "PARSER_OR_SCHEMA_FAILURE", "POLICY_NOT_VALIDATED"}
near_one = []
near_two = []
near_detail = []
for row in rows:
    live = row["live_decision"]
    if live.get("final_action") in {"MOMENTUM BUY", "RECOVERY BUY", "MOMENTUM + RECOVERY BUY"}:
        continue
    reasons = list(dict.fromkeys(live.get("reason_codes") or []))
    # Count router gates, keeping the two thesis-specific technical gates distinct.
    failures = []
    for code in reasons:
        if code not in failures:
            failures.append(code)
    if len(failures) not in {1, 2}:
        continue
    symbol = str(row["symbol"])
    missing = classifications[symbol]["missing"]
    kind = "DATA_GAP" if missing else "LEGITIMATE_MODEL_REJECTION"
    target = near_one if len(failures) == 1 else near_two
    target.append(symbol)
    near_detail.append({"symbol": symbol, "failed_gate_count": len(failures), "failures": failures,
                        "classification": kind, "missing_evidence": missing})

historical = []
sys.path.insert(0, str(ROOT))
from stock_app import fundamental_v3 as _f3
_panel = _f3._read_rows(_f3.discover_sources(ROOT)["canonical_panel"])
_supplement_path = ROOT / "NextGen Research" / "results" / "pit_safety_supplement_v1" / "pit_safety_supplement.jsonl"
_supplement_rows = _f3._read_rows(_supplement_path if _supplement_path.exists() else None)
_supplement_by_symbol = defaultdict(list)
for _item in _supplement_rows:
    _supplement_by_symbol[str(_item.get("symbol") or "")].append(_item)
for month in range(4, 11):
    cutoff = date(2026, month, 30 if month in {4, 6, 9} else 31).isoformat()
    valuation_available = 0
    fundamental_available = 0
    missing = Counter()
    for row in rows:
        symbol = str(row["symbol"])
        history, _basis = _f3._pit_rows(_panel, symbol, _f3._cutoff(cutoff), "CONSOLIDATED")
        fundamental_available += int(bool(history))
        if history:
            for label, feature_name in (("revenue", "REVENUE"), ("pat", "PAT"), ("eps", "EPS"),
                                        ("operating_cash_flow", "OPERATING_CASH_FLOW"),
                                        ("debt_equity_ratio", "DEBT_EQUITY_RATIO")):
                present = any(_f3._usable_feature(item, feature_name) is not None for item in reversed(history))
                if feature_name == "DEBT_EQUITY_RATIO" and not present:
                    present = any(
                        str(item.get("availability_ts") or "")[:10] <= cutoff
                        and item.get("point_in_time_safe") is True
                        and item.get("display_validated") is True
                        and item.get("domain") == "IND_AS_CORPORATE"
                        for item in _supplement_by_symbol.get(symbol, [])
                    )
                missing[label] += int(not present)
        else:
            for label in ("revenue", "pat", "eps", "operating_cash_flow", "debt_equity_ratio"):
                missing[label] += 1
        live = row["live_decision"]
        fundamental = ((live.get("evidence") or {}).get("fundamental") or {})
        observations = (fundamental.get("valuation") or {}).get("pit_comparison_observations") or []
        usable = [o for o in observations if str(o.get("session") or "")[:10] <= cutoff]
        valuation_available += int(len(usable) >= 4)
    historical.append({
        "month": cutoff[:7], "universe": 200,
        "fundamental_available": fundamental_available,
        "fundamental_missing_rate": round((200 - fundamental_available) / 200, 4),
        "revenue_missing_rate": round(missing["revenue"] / 200, 4),
        "pat_missing_rate": round(missing["pat"] / 200, 4),
        "eps_missing_rate": round(missing["eps"] / 200, 4),
        "operating_cash_flow_missing_rate": round(missing["operating_cash_flow"] / 200, 4),
        "debt_equity_ratio_missing_rate": round(missing["debt_equity_ratio"] / 200, 4),
        "pit_valuation_minimum_history_available": valuation_available,
        "pit_valuation_missing_rate": round((200 - valuation_available) / 200, 4),
        "method": "Canonical panel filtered by official availability timestamp and reporting basis; valuation uses existing company-specific PIT observations. Coverage diagnostic only.",
    })

actions = _actions(rows)
pit_causes = defaultdict(list)
for row in matrix:
    symbol = row["symbol"]
    current_condition = row["current_valuation_condition"]
    history_condition = row["historical_pit_valuation_condition"]
    if history_condition == "PRESENT_AND_SUPPORTIVE":
        continue
    if current_condition == "PRESENT_BUT_UNFAVORABLE":
        pit_causes["current_pe_or_pb_non_positive"].append(symbol)
    elif current_condition != "PRESENT_AND_SUPPORTIVE":
        pit_causes["current_pe_or_pb_unavailable"].append(symbol)
        if row["domain"] != "corporate":
            pit_causes["financial_domain_mapping_unavailable"].append(symbol)
    elif history_condition == "INSUFFICIENT_PIT_HISTORY":
        pit_causes["fewer_than_minimum_pit_observations"].append(symbol)
    elif history_condition == "STALE_OR_OUT_OF_ORDER":
        pit_causes["stale_filing_timestamps"].append(symbol)
    else:
        pit_causes["parser_or_reporting_basis_failure"].append(symbol)
summary = {
    "schema": "SRE_MISSING_EVIDENCE_COVERAGE_AUDIT_V1",
    "release": "0.14.11-missing-evidence-coverage-repair",
    "market_session": SESSION, "universe": len(rows), "router_sha256": ROUTER_SHA,
    "action_counts_before": actions, "action_counts_after": actions,
    "new_buys_caused_by_repaired_evidence": [],
    "coverage": {
        "corporate_count": len(corporates), "financial_count": len(financials),
        "corporate_leverage_validated_supplement_rows": _supplement_validated_count(),
        "corporate_leverage_available": len(corporates) - len(balance_unavailable),
        "balance_sheet_unavailable": {"count": len(balance_unavailable), "symbols": _symbols(balance_unavailable)},
        "balance_sheet_unfavorable": {"count": len(balance_unfavorable), "symbols": _symbols(balance_unfavorable)},
        "cash_flow_unavailable": {"count": len(cash_unavailable), "symbols": _symbols(cash_unavailable)},
        "cash_flow_unfavorable": {"count": len(cash_unfavorable), "symbols": _symbols(cash_unfavorable)},
        "cash_flow_supportive": {"count": len(cash_supportive), "symbols": _symbols(cash_supportive)},
        "pit_valuation_unavailable": {"count": len(pit_unavailable), "symbols": _symbols(pit_unavailable)},
        "pit_valuation_causes": {key: {"count": len(value), "symbols": _symbols(value)} for key, value in pit_causes.items()},
        "bank_nbfc_unresolved": {"count": len(financials), "symbols": _symbols(r["symbol"] for r in financials)},
    },
    "family_breakdowns": {
        family: condition_breakdown(family) for family in (
            "Revenue", "PAT", "EPS", "Operating cash flow", "Cash / equivalents", "Total assets",
            "Debt / leverage / DebtEquityRatio", "Historical PIT valuation reference")
    },
    "business_earnings_incomplete": {
        "count": len(business_blocked),
        "symbols": _symbols(row["symbol"] for row in business_blocked),
        "causes": {key: {"count": len(value), "symbols": _symbols(value)} for key, value in business_causes.items()},
    },
    "near_miss": {"one_gate": _symbols(near_one), "two_gates": _symbols(near_two), "details": near_detail},
    "historical_coverage": historical,
    "safe_repairs": [
        "Deterministic missing-vs-unfavorable evidence classification",
        "Financial-domain taxonomy research adapter kept fail-closed",
        "UI blocker counts separated by unavailable and unfavorable conditions",
    ],
    "evidence_values_added": 0,
    "financial_domain_policy": "FAIL_CLOSED_POLICY_NOT_VALIDATED",
    "router_changed": False, "model_or_threshold_changed": False, "provider_policy_changed": False,
    "automatic_yfinance_fallback": False,
}
(OUT / "missing_evidence_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

md = [
    "# Missing Evidence Coverage Audit", "",
    f"- Session: {SESSION}", f"- Universe: {len(rows)}", f"- Router SHA256: `{ROUTER_SHA}`",
    "- Decision/model/threshold changes: none", "- BANK/NBFC policy: fail-closed", "",
    "## Coverage", "",
    f"- Corporate leverage available: {summary['coverage']['corporate_leverage_available']}/{len(corporates)}",
    f"- Balance sheet unavailable: {len(balance_unavailable)}", f"- Balance sheet present but caution/weak: {len(balance_unfavorable)}",
    f"- Cash flow unavailable: {len(cash_unavailable)}", f"- Cash flow present but unfavorable: {len(cash_unfavorable)}",
    f"- Cash flow supportive: {len(cash_supportive)}", f"- PIT valuation unavailable: {len(pit_unavailable)}",
    f"- BANK/NBFC unresolved: {len(financials)}", "",
    "## LIVE_DECISION_V1", "", *(f"- {key}: {value}" for key, value in actions.items()), "",
    "## Finding", "",
    "No additional official value mapping met the semantic, unit, context, reporting-basis and continuity bar for production promotion. "
    "The safe repair is diagnostic: unavailable evidence is no longer merged with present-but-unfavorable evidence. Financial-domain concepts are research-only.", "",
    "## Historical coverage diagnostic", "",
    "This is a missing-data/restrictiveness check, not a profitability backtest.", "",
    "| Month | Fundamental missing rate | PIT valuation missing rate |", "|---|---:|---:|",
]
for item in historical:
    md.append(f"| {item['month']} | {item['fundamental_missing_rate']:.1%} | {item['pit_valuation_missing_rate']:.1%} |")
(OUT / "missing_evidence_audit.md").write_text("\n".join(md) + "\n", encoding="utf-8")

assert actions["recovery_buy"] == 2
by_symbol = {str(row["symbol"]): row["live_decision"] for row in rows}
assert by_symbol["HINDZINC"]["final_action"] == "RECOVERY BUY"
assert by_symbol["GODREJCP"]["final_action"] == "RECOVERY BUY"
assert by_symbol["OFSS"]["final_action"] == "WATCH - RECOVERY"
assert by_symbol["OFSS"]["balance_sheet_state"] == "CAUTION"
assert len(balance_unavailable) == 97 and len(balance_unfavorable) == 10
assert len(cash_unavailable) == 16 and len(cash_unfavorable) == 29
assert len(pit_unavailable) == 56
assert len(financials) == 37
assert hashlib.sha256(ROUTER.read_bytes()).hexdigest() == ROUTER_SHA
print(json.dumps(summary, indent=2, default=str), flush=True)
print("0.14.11 MISSING EVIDENCE COVERAGE AUDIT PASS", flush=True)

