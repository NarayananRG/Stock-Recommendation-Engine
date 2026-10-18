"""Read-only full-universe analysis of an exported active recommendation run.

No market downloads or scoring changes. Missing evidence is not a negative signal.
"""
import argparse
import collections
import json
from pathlib import Path

def audit(payload):
    if not isinstance(payload,dict) or not isinstance(payload.get("run"),dict) or not isinstance(payload.get("candidates"),list):
        raise ValueError("Expected active-run JSON with run object and candidates array")
    run=payload["run"]
    if not run.get("run_id") or not run.get("market_session"):
        raise ValueError("Missing authoritative run identity or market session")
    counts=collections.Counter()
    reasons=collections.Counter()
    quality=collections.Counter()
    sessions=collections.Counter()
    duplicate=set()
    symbols=set()
    for row in payload["candidates"]:
        if not isinstance(row,dict):
            raise ValueError("Invalid candidate")
        symbol=str(row.get("symbol") or "").upper().removesuffix(".NS")
        if not symbol or symbol in symbols:
            raise ValueError("Missing/duplicate symbol: "+symbol)
        symbols.add(symbol)
        decision=row.get("live_decision") or {}
        if not isinstance(decision,dict):
            raise ValueError("Invalid decision: "+symbol)
        action=str(decision.get("final_action") or row.get("final_action") or "UNAVAILABLE")
        counts[action]+=1
        counts["EXECUTABLE" if decision.get("executable") is True else "NOT_EXECUTABLE"]+=1
        q=str(decision.get("fundamental_data_quality") or "UNAVAILABLE")
        quality[q]+=1
        session=str(decision.get("market_session") or "UNAVAILABLE")
        sessions[session]+=1
        if session != str(run["market_session"]):
            duplicate.add(symbol)
        codes=decision.get("reason_codes") or []
        if not isinstance(codes,list):
            raise ValueError("Invalid reason codes: "+symbol)
        for code in set(str(c) for c in codes):
            reasons[code]+=1
    return {
        "schema":"SRE_FULL_UNIVERSE_EVIDENCE_V1",
        "run":{"run_id":run["run_id"],"market_session":run["market_session"],"model_version":run.get("model_version"),"production_authority":run.get("production_authority")},
        "universe_count":len(symbols),
        "action_and_execution_counts":dict(sorted(counts.items())),
        "fundamental_evidence_quality":dict(sorted(quality.items())),
        "decision_session_counts":dict(sorted(sessions.items())),
        "reason_code_counts":dict(sorted(reasons.items())),
        "session_mismatch_count":len(duplicate),
        "session_consistency_pass":not duplicate,
        "limitations":["No official daily cache attached; actual official-source freshness NOT VERIFIED","Reason-code frequencies are not proof of over-restriction","No matured OOS or realized paper-trading performance verified"],
        "changes_production":False,
        "promotion_authorized":False
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    source=Path(args.input)
    if not source.is_file():
        p.error("Actual local active-run export is required; no synthetic fallback")
    report=audit(json.loads(source.read_text(encoding="utf-8-sig")))
    output=Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print("FULL UNIVERSE EVIDENCE:",report["universe_count"],"symbols; session_consistency:",report["session_consistency_pass"])

if __name__=="__main__":
    main()
