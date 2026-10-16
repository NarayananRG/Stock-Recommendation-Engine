from pathlib import Path
import json
import os
import shutil

repo = Path(__file__).resolve().parents[2]
root = Path(os.environ["SRE_ENGINE_ROOT"])


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(label + " patch point missing")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


shutil.copy2(repo / ".ci" / "native152" / "evidence_coverage_v1.py", root / "stock_app" / "evidence_coverage_v1.py")
api = root / "modern_ui" / "api.py"
replace_once(api, 'APP_VERSION = "0.14.10-recommendation-presentation-status-repair"',
             'APP_VERSION = "0.14.11-missing-evidence-coverage-repair"', "release identity")
replace_once(api, "from stock_app.storage import AppDatabase\n",
             "from stock_app.storage import AppDatabase\nfrom stock_app.evidence_coverage_v1 import classify_live_decision\n",
             "classification import")
replace_once(api,
'''            live = route(symbol, session, technical, fundamental, price_context=context,
                         official_current=current and bool(bars) and str(bars[-1].get("date"))[:10] == session, legacy=dict(row))
            rows.append({**row, "legacy_opportunity_status": row.get("opportunity_status"), "live_decision": live,
''',
'''            live = route(symbol, session, technical, fundamental, price_context=context,
                         official_current=current and bool(bars) and str(bars[-1].get("date"))[:10] == session, legacy=dict(row))
            # Diagnostic annotation only. The router has already produced its
            # action and remains byte-for-byte unchanged.
            live["evidence_classification"] = classify_live_decision(live)
            rows.append({**row, "legacy_opportunity_status": row.get("opportunity_status"), "live_decision": live,
''', "live evidence annotation")

text = api.read_text(encoding="utf-8")
start = text.index("    def live_coverage(self) -> dict[str, Any]:\n")
end = text.index("\n    def latest_run_input", start)
method = '''    def live_coverage(self) -> dict[str, Any]:
        from collections import Counter
        rows = self.latest_prediction_rows(limit=200)
        features: dict[str, Counter] = {}
        conditions: dict[str, Counter] = {}
        blockers = Counter()
        ready = partial = unavailable = financial = 0
        symbols = []
        for row in rows:
            live = row.get("live_decision") or {}
            fundamental = ((live.get("evidence") or {}).get("fundamental") or {})
            classified = live.get("evidence_classification") or classify_live_decision(live)
            is_financial = classified.get("domain") != "corporate"
            financial += int(is_financial)
            if not fundamental.get("available"):
                unavailable += 1
            elif (not is_financial and live.get("cash_flow_state") in ("ADEQUATE", "SUPPORTIVE") and
                  live.get("balance_sheet_state") in ("HEALTHY", "ACCEPTABLE")):
                ready += 1
            else:
                partial += 1
            for code in live.get("reason_codes") or []:
                blockers[str(code)] += 1
            per_symbol = {}
            for name, item in (fundamental.get("feature_coverage") or {}).items():
                status = str((item or {}).get("status") or "MISSING").upper()
                status = status if status in ("AVAILABLE", "MISSING", "STALE") else "MISSING"
                features.setdefault(name, Counter())[status] += 1
                per_symbol[name] = status
            for name, item in (classified.get("families") or {}).items():
                conditions.setdefault(name, Counter())[str(item.get("condition"))] += 1
            symbols.append({"symbol": row.get("symbol"), "final_action": live.get("final_action"),
                            "missing_evidence": classified.get("missing") or [],
                            "unfavorable_evidence": classified.get("unfavorable") or [],
                            "evidence_classification": classified, "features": per_symbol})
        for counts in features.values():
            counts["MISSING"] += len(rows) - sum(counts.values())
        lane = (self.active_prediction_run() or {}).get("run", {}).get("lane_counts") or {}
        return {"authority": "LIVE_DECISION_V1", "model_version": APP_VERSION, "universe_size": len(rows),
                "fundamental_ready": ready, "fundamental_partial": partial,
                "fundamental_unavailable": unavailable, "financial_domain_count": financial,
                "nonfinancial_count": len(rows) - financial, "lane_counts": lane,
                "blocker_counts": dict(blockers.most_common()),
                "evidence_condition_counts": {name: dict(counts) for name, counts in sorted(conditions.items())},
                "feature_coverage_counts": {name: dict(counts) for name, counts in sorted(features.items())},
                "symbols": symbols}
'''
api.write_text(text[:start] + method + text[end:], encoding="utf-8")

replace_once(api,
'''        summary["blocker_count_semantics"] = "UNIQUE_SYMBOLS"
        summary["live_universe_size"] = len(live_rows)
''',
'''        summary["blocker_count_semantics"] = "UNIQUE_SYMBOLS"
        evidence_counts = Counter()
        for item in live_rows:
            live = item.get("live_decision") or {}
            classified = live.get("evidence_classification") or classify_live_decision(live)
            if classified.get("domain") != "corporate":
                evidence_counts["BANK/NBFC policy not validated"] += 1
                continue
            families = classified.get("families") or {}
            leverage = (families.get("Debt / leverage / DebtEquityRatio") or {}).get("condition")
            cashflow = (families.get("Operating cash flow") or {}).get("condition")
            history = (families.get("Historical PIT valuation reference") or {}).get("condition")
            if leverage == "PRESENT_BUT_UNFAVORABLE": evidence_counts["Balance-sheet present but caution/weak"] += 1
            elif leverage != "PRESENT_AND_SUPPORTIVE": evidence_counts["Balance-sheet unavailable"] += 1
            if cashflow == "PRESENT_BUT_UNFAVORABLE": evidence_counts["Cash flow present but not supportive"] += 1
            elif cashflow != "PRESENT_AND_SUPPORTIVE": evidence_counts["Cash flow unavailable"] += 1
            if history != "PRESENT_AND_SUPPORTIVE": evidence_counts["PIT valuation history unavailable"] += 1
        summary["evidence_condition_counts"] = dict(evidence_counts)
        summary["live_universe_size"] = len(live_rows)
''', "capital diagnostic split")

front = root / "modern_ui" / "frontend" / "app.js"
replace_once(front,
"BALANCE_SHEET_NOT_ACCEPTABLE_OR_UNAVAILABLE:'Balance-sheet evidence is missing or insufficient',CASH_FLOW_NOT_SUPPORTIVE_OR_UNAVAILABLE:'Cash-flow evidence is missing or not supportive'",
"BALANCE_SHEET_NOT_ACCEPTABLE_OR_UNAVAILABLE:'Balance-sheet gate not passed — see unavailable vs caution counts',CASH_FLOW_NOT_SUPPORTIVE_OR_UNAVAILABLE:'Cash-flow gate not passed — see unavailable vs unfavorable counts'",
"reason wording")
replace_once(front,
"const s=d.capital_summary||{},buys=d.new_buys||[],lc=s.live_lane_counts||{},blockers=s.top_blockers||{},universe=+s.live_universe_size||200;",
"const s=d.capital_summary||{},buys=d.new_buys||[],lc=s.live_lane_counts||{},blockers=s.top_blockers||{},evidence=s.evidence_condition_counts||{},universe=+s.live_universe_size||200;",
"capital evidence counts")
replace_once(front,
"</div>${top.length?`<div class=\"blocker-summary\">",
"</div>${Object.keys(evidence).length?`<div class=\"blocker-summary evidence-condition-summary\"><b>Evidence availability vs condition</b><small>Unavailable evidence is separate from evidence that is present but unfavorable.</small>${Object.entries(evidence).map(([label,count])=>`<div class=\"blocker-row\"><span>${escapeHtml(label)}</span><strong>${count}</strong><span>${universe?((100*count/universe).toFixed(1)+'%'):'-'}</span></div>`).join('')}</div>`:''}${top.length?`<div class=\"blocker-summary\">",
"capital evidence UI")

policy = root / "phase5" / "missing_evidence_coverage_policy_01411.json"
policy.write_text(json.dumps({
    "schema": "SRE_MISSING_EVIDENCE_COVERAGE_POLICY_01411",
    "release": "0.14.11-missing-evidence-coverage-repair",
    "conditions": ["MISSING_SOURCE_DATA", "SOURCE_AVAILABLE_BUT_UNMAPPED", "PRESENT_BUT_UNFAVORABLE",
                   "INSUFFICIENT_PIT_HISTORY", "NOT_APPLICABLE_FOR_DOMAIN", "POLICY_NOT_VALIDATED",
                   "STALE_OR_OUT_OF_ORDER", "PARSER_OR_SCHEMA_FAILURE", "PRESENT_AND_SUPPORTIVE"],
    "financial_domain_policy": "FAIL_CLOSED_POLICY_NOT_VALIDATED",
    "classification_changes_decision": False,
    "router_changed": False, "model_or_threshold_changed": False, "provider_policy_changed": False,
    "automatic_yfinance_fallback": False,
}, indent=2), encoding="utf-8")

assert 'APP_VERSION = "0.14.11-missing-evidence-coverage-repair"' in api.read_text(encoding="utf-8")
assert "evidence_classification" in api.read_text(encoding="utf-8")
assert "Evidence availability vs condition" in front.read_text(encoding="utf-8")
print("0.14.11 missing evidence coverage repair applied")

