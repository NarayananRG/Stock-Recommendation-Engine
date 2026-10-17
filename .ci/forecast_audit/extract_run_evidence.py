"""Read-only, fail-closed extraction of forecast lineage for a local SRE active-run JSON export.

Usage: python .ci/forecast_audit/extract_run_evidence.py --input ACTIVE_RUN.json --output evidence.json
Never exports account information, holdings, full fundamental records, or other symbols.
"""
import argparse, json, math
from pathlib import Path

SYMBOLS=("GODREJCP","HINDZINC")
FIELDS=("symbol","rank","expected_return","profit_probability","latest_close","confidence_label",
        "opportunity_status","final_action","run_id","market_session","horizon_sessions")
LIVE_FIELDS=("final_action","executable","confidence","market_session","strategy_style","primary_style",
             "point_in_time_safe","provenance","reason_codes","target_used_in_score")
RUN_FIELDS=("run_id","market_session","horizon_sessions","production_authority","model_version",
            "run_timestamp")

def _safe_num(v):
    if isinstance(v,bool) or v is None:return None
    try:
        a=float(v)
        return a if math.isfinite(a) else None
    except (TypeError,ValueError):return None

def extract(payload):
    if not isinstance(payload,dict):raise ValueError("Input must be an active-run JSON object")
    run=payload.get("run")
    rows=payload.get("candidates")
    if not isinstance(run,dict) or not isinstance(rows,list):raise ValueError("Input requires run and candidates fields")
    out={"schema":"SRE_ACTUAL_RECOMMENDATION_LINEAGE_V1","snapshot":{k:run.get(k) for k in RUN_FIELDS},
         "symbol_records":{},"limitations":[]}
    if not run.get("market_session") or not run.get("run_id"):raise ValueError("Missing authoritative run ID or session")
    for symbol in SYMBOLS:
        matches=[r for r in rows if isinstance(r,dict) and str(r.get("symbol","")).upper().removesuffix(".NS")==symbol]
        if len(matches)>1:raise ValueError("Duplicate candidate rows for "+symbol)
        if not matches:
            out["symbol_records"][symbol]={"found":False}
            out["limitations"].append(symbol+"_ABSENT_FROM_SNAPSHOT")
            continue
        row=matches[0]
        live=row.get("live_decision") or {}
        if not isinstance(live,dict):raise ValueError("Invalid live decision")
        data={k:row.get(k) for k in FIELDS if k not in ("expected_return","profit_probability","latest_close")}
        for key in ("expected_return","profit_probability","latest_close"):data[key]=_safe_num(row.get(key))
        data["live_decision"]={k:live.get(k) for k in LIVE_FIELDS}
        data["found"]=True
        data["same_session"]=str(live.get("market_session") or "")==str(run["market_session"])
        data["forecast_horizon_verified"]=False
        data["forecast_calibration_verified"]=False
        out["symbol_records"][symbol]=data
        if not data["same_session"]:out["limitations"].append(symbol+"_LIVE_DECISION_SESSION_MISMATCH")
        out["limitations"].append(symbol+"_LEGACY_FORECAST_PROVENANCE_UNVERIFIED")
    out["ready_to_promote_forecast_as_buy_gate"]=False
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    src=Path(args.input)
    if not src.is_file():raise SystemExit("No local active-run export found: "+str(src))
    result=extract(json.loads(src.read_text(encoding="utf-8-sig")))
    dst=Path(args.output)
    dst.parent.mkdir(parents=True,exist_ok=True)
    dst.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print("EVIDENCE EXTRACTED:",", ".join(k for k,v in result["symbol_records"].items() if v["found"]))
    print("LIMITATIONS:",", ".join(result["limitations"]))
    print("NO PRODUCTION DATA MODIFIED")

if __name__=="__main__":main()
