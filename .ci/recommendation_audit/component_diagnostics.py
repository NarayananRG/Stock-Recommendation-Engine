"""Read-only decision component diagnostics from persisted active-run evidence.

Never mutates scoring/thresholds; reports states and availability independently.
"""
import argparse, collections, json
from pathlib import Path

def classify(value, acceptable):
    if value is None or str(value).upper() in ("", "UNAVAILABLE", "UNKNOWN", "NONE", "STALE"):
        return "MISSING_OR_STALE"
    return "PASS" if value in acceptable else "UNFAVORABLE"

def component_row(row):
    decision=row.get("live_decision")
    if not isinstance(decision,dict):raise ValueError("Missing live decision")
    evidence=decision.get("evidence") or {}
    if not isinstance(evidence,dict):raise ValueError("Invalid decision evidence")
    technical=evidence.get("technical") or {}
    if not isinstance(technical,dict):raise ValueError("Invalid technical evidence")
    states={
      "fundamental_quality":classify(decision.get("fundamental_data_quality"),("AVAILABLE",)),
      "business_health":classify(decision.get("business_health"),("HEALTHY","STRONG")),
      "earnings_direction":classify(decision.get("earnings_direction"),("STABLE","IMPROVING")),
      "fundamental_event_state":classify(decision.get("fundamental_event_state"),("STABLE","IMPROVING")),
      "cash_flow":classify(decision.get("cash_flow_state"),("SUPPORTIVE","ADEQUATE")),
      "balance_sheet":classify(decision.get("balance_sheet_state"),("HEALTHY","ACCEPTABLE")),
      "relative_valuation":classify(decision.get("valuation_state"),("ATTRACTIVE","REASONABLE")),
      "technical_data_status":classify(technical.get("status"),("READY",)),
      "weekly_confirmation":("PASS" if (technical.get("multi_timeframe") or {}).get("weekly_trend_confirmed") is True else
        "UNFAVORABLE" if (technical.get("multi_timeframe") or {}).get("weekly_trend_confirmed") is False else "MISSING_OR_STALE")
    }
    for group,key,rule in [
        ("trend","close",lambda v: v>0),("trend","ema50",lambda v:v>0),
        ("trend","ema50_slope_5d_pct",lambda v:v>0),
        ("momentum","roc20_pct",lambda v:v>0),
        ("momentum","macd_hist",lambda v:v>0),
        ("relative_strength","rs20_vs_nifty",lambda v:v>0),
        ("volume_flow","cmf20",lambda v:v>0)]:
        value=(technical.get(group) or {}).get(key)
        try:
            if isinstance(value,bool) or value is None:raise ValueError
            numeric=float(value)
            import math
            if not math.isfinite(numeric):raise ValueError
            states[group+"."+key]="PASS" if rule(numeric) else "UNFAVORABLE"
        except (TypeError,ValueError):states[group+"."+key]="MISSING_OR_STALE"
    try:
        close=float((technical.get("trend") or {}).get("close"))
        ema=float((technical.get("trend") or {}).get("ema50"))
        states["price_above_ema50"]="PASS" if close>ema else "UNFAVORABLE"
    except (TypeError,ValueError):states["price_above_ema50"]="MISSING_OR_STALE"
    # No symbol, holdings, forecasts or full evidence leaves this function.
    return states

def audit(payload):
    if not isinstance(payload,dict) or not isinstance(payload.get("run"),dict) or not isinstance(payload.get("candidates"),list):raise ValueError("Expected real run/candidates")
    run=payload["run"]
    if not run.get("run_id") or not run.get("market_session"):raise ValueError("Missing active-run identity")
    totals=collections.Counter();by_action=collections.Counter();symbols=set()
    for row in payload["candidates"]:
        if not isinstance(row,dict):raise ValueError("Invalid candidate")
        symbol=str(row.get("symbol") or "").upper().removesuffix(".NS")
        if not symbol or symbol in symbols:raise ValueError("Duplicate/missing symbol")
        symbols.add(symbol)
        action=str(row["live_decision"].get("final_action") or "UNAVAILABLE")
        states=component_row(row)
        for key,status in states.items():
            totals[(key,status)]+=1
            by_action[(action,key,status)]+=1
    return {
      "schema":"SRE_COMPONENT_DIAGNOSTICS_V1",
      "run_id":run["run_id"],"market_session":run["market_session"],"stocks":len(symbols),
      "components":[{"component":k,"status":v,"count":n} for (k,v),n in sorted(totals.items())],
      "by_action":[{"action":a,"component":k,"status":v,"count":n} for (a,k,v),n in sorted(by_action.items())],
      "limitations":["Diagnostic reconstruction from saved decision states and evidence; cannot infer causality or gate distance","Absent or malformed fields are MISSING_OR_STALE, not unfavorable","Financial-domain industrial cash/debt criteria may be non-applicable","No official-source freshness or return performance proof"],
      "production_changed":False,"promotion_authorized":False
    }

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--input",required=True);p.add_argument("--output",required=True);a=p.parse_args()
    source=Path(a.input)
    if not source.is_file():p.error("Real local active-run export required")
    report=audit(json.loads(source.read_text(encoding="utf-8-sig")))
    dst=Path(a.output);dst.parent.mkdir(parents=True,exist_ok=True)
    dst.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print("COMPONENT DIAGNOSTICS",report["stocks"],"symbols")
