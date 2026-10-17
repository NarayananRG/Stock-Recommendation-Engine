"""Aggregate saved decision states without exporting stock identifiers or holdings."""
import argparse
import collections
import json
from pathlib import Path

STATES = ("business_health","earnings_direction","fundamental_event_state","cash_flow_state","balance_sheet_state","valuation_state","fundamental_data_quality","financial_domain","technical_state")

def audit(payload):
    run = payload.get("run") or {}
    rows = payload.get("candidates")
    if not run.get("run_id") or not run.get("market_session") or not isinstance(rows,list):
        raise ValueError("Real analysis run and candidates required")
    counts = collections.Counter()
    sectors = collections.Counter()
    evidence = collections.Counter()
    seen = set()
    for row in rows:
        name = str(row.get("symbol") or "").upper().removesuffix(".NS")
        if not name or name in seen:
            raise ValueError("Missing or duplicate candidate")
        seen.add(name)
        d = row.get("live_decision")
        if not isinstance(d,dict):
            raise ValueError("Missing decision")
        sector = "FINANCIAL" if d.get("financial_domain") is True else "OTHER_OR_UNKNOWN"
        for key in STATES:
            value = str(d[key]) if key in d and d[key] is not None else "ABSENT"
            counts[(key,value)] += 1
            if key in ("business_health","fundamental_event_state","balance_sheet_state","cash_flow_state"):
                sectors[(sector,key,value)] += 1
        context = d.get("evidence") or {}
        fund = context.get("fundamental") or {} if isinstance(context,dict) else {}
        if not isinstance(fund,dict):
            fund = {}
        event = fund.get("risk_event") or {}
        if not isinstance(event,dict):
            event = {}
        balance = fund.get("balance_sheet") or {}
        if not isinstance(balance,dict):
            balance = {}
        evidence[("event_profile",str(event.get("event_profile") or "ABSENT"))] += 1
        evidence[("event_available",str(event.get("available","ABSENT")))] += 1
        evidence[("debt_equity_present",str(balance.get("debt_equity_ratio") is not None))] += 1
        evidence[("pit_safe",str(fund.get("point_in_time_safe","ABSENT")))] += 1
    return {
        "schema":"SRE_RAW_STATE_AGGREGATE_V1",
        "run_id":run["run_id"],"market_session":run["market_session"],"stocks":len(seen),
        "states":[{"component":a,"value":b,"count":n} for (a,b),n in sorted(counts.items())],
        "sector_states":[{"sector":a,"component":b,"value":c,"count":n} for (a,b,c),n in sorted(sectors.items())],
        "evidence_presence":[{"component":a,"value":b,"count":n} for (a,b),n in sorted(evidence.items())],
        "limitations":["Observational report, not an evaluation of numeric thresholds","OTHER_OR_UNKNOWN is not confirmed nonfinancial","Official feed freshness and outcomes not verified"],
        "production_changed":False,"promotion_authorized":False
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",required=True)
    parser.add_argument("--output",required=True)
    args = parser.parse_args()
    path = Path(args.input)
    if not path.is_file():
        parser.error("Real local active-run snapshot required")
    report = audit(json.loads(path.read_text(encoding="utf-8-sig")))
    destination = Path(args.output)
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print("RAW STATE AUDIT",report["stocks"],"candidates")
