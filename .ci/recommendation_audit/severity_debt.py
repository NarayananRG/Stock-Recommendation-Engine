"""Aggregate, privacy-safe severity and debt-ratio provenance from a real active run."""
import argparse, collections, json
from pathlib import Path

def audit(payload):
    run=payload.get("run") or {}; rows=payload.get("candidates")
    if not run.get("run_id") or not run.get("market_session") or not isinstance(rows,list):
        raise ValueError("Real run metadata and candidates required")
    counts=collections.Counter();seen=set()
    for row in rows:
        symbol=str(row.get("symbol") or "").upper().removesuffix(".NS")
        if not symbol or symbol in seen:raise ValueError("Missing or duplicate symbol")
        seen.add(symbol)
        decision=row.get("live_decision")
        if not isinstance(decision,dict):raise ValueError("Missing live decision")
        evidence=decision.get("evidence") or {}
        fund=evidence.get("fundamental") or {} if isinstance(evidence,dict) else {}
        if not isinstance(fund,dict):fund={}
        event=fund.get("risk_event") or {}
        if not isinstance(event,dict):event={}
        bal=fund.get("balance_sheet") or {}
        if not isinstance(bal,dict):bal={}
        sector="FINANCIAL" if decision.get("financial_domain") is True else "OTHER_OR_UNKNOWN"
        profile=str(event.get("event_profile") or "ABSENT")
        counts[("profile",profile)]+=1
        if profile=="MIXED_DIRECTIONAL":
            counts[("mixed_strong_deterioration",str(event.get("strong_deterioration_transition","ABSENT")))]+=1
            counts[("mixed_strong_improvement",str(event.get("strong_improvement_transition","ABSENT")))]+=1
            for key in ("deterioration_evidence_count","improvement_evidence_count"):
                val=event.get(key)
                band="ABSENT"
                if isinstance(val,int) and not isinstance(val,bool) and val>=0:band="ZERO" if val==0 else "ONE" if val==1 else "TWO_PLUS"
                counts[("mixed_"+key,band)]+=1
        ratio=bal.get("debt_equity_ratio")
        counts[("debt_ratio_presence",sector+":"+("PRESENT" if ratio is not None else "ABSENT"))]+=1
        counts[("balance_state_given_debt",sector+":"+str(decision.get("balance_sheet_state") or "ABSENT")+":"+("PRESENT" if ratio is not None else "ABSENT"))]+=1
    return {"schema":"SRE_SEVERITY_DEBT_PROVENANCE_V1","run_id":run["run_id"],"market_session":run["market_session"],"stocks":len(seen),
            "counts":[{"dimension":a,"value":b,"count":n} for (a,b),n in sorted(counts.items())],
            "limitations":["A mixed event is not by itself severe deterioration","ABSENT severity fields must not be interpreted as False","OTHER_OR_UNKNOWN does not guarantee nonfinancial","Numerical validity of the underlying debt ratio and official source are not verified"],
            "production_changed":False,"promotion_authorized":False}
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--input",required=True);p.add_argument("--output",required=True);args=p.parse_args()
    src=Path(args.input)
    if not src.is_file():p.error("Actual local active-run JSON required")
    result=audit(json.loads(src.read_text(encoding="utf-8-sig")))
    dst=Path(args.output);dst.parent.mkdir(parents=True,exist_ok=True)
    dst.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print("AUDITED",result["stocks"],"stocks")
