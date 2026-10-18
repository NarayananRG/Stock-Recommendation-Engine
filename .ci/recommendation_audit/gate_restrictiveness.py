"""Privacy-safe read-only gate overlap analysis. No rule changes."""
import argparse, collections, json
from pathlib import Path

def audit(payload):
    if not isinstance(payload,dict) or not isinstance(payload.get("run"),dict) or not isinstance(payload.get("candidates"),list):
        raise ValueError("Missing run or candidates")
    run=payload["run"]
    if not run.get("run_id") or not run.get("market_session"):raise ValueError("Missing run identity")
    actions=collections.Counter();reasons=collections.Counter();pairs=collections.Counter()
    by_action=collections.Counter();quality=collections.Counter();execution=collections.Counter()
    seen=set();mismatches=0
    for row in payload["candidates"]:
        if not isinstance(row,dict):raise ValueError("Invalid candidate")
        symbol=str(row.get("symbol") or "").upper().removesuffix(".NS")
        if not symbol or symbol in seen:raise ValueError("Duplicate or missing symbol")
        seen.add(symbol)
        d=row.get("live_decision")
        if not isinstance(d,dict):raise ValueError("Missing live decision")
        action=str(d.get("final_action") or "UNAVAILABLE");actions[action]+=1
        quality[str(d.get("fundamental_data_quality") or "UNAVAILABLE")]+=1
        execution["YES" if d.get("executable") is True else "NO"]+=1
        mismatches+=str(d.get("market_session") or "")!=str(run["market_session"])
        raw=d.get("reason_codes") or []
        if not isinstance(raw,list):raise ValueError("Invalid reason codes")
        codes=sorted(set(str(x) for x in raw if x))
        for i,a in enumerate(codes):
            reasons[a]+=1;by_action[(action,a)]+=1
            for b in codes[i+1:]:pairs[(a,b)]+=1
    return {"schema":"SRE_GATE_RESTRICTIVENESS_V1",
      "run":{"run_id":run["run_id"],"market_session":run["market_session"]},
      "count":len(seen),"session_mismatches":mismatches,
      "actions":dict(sorted(actions.items())),"executable":dict(sorted(execution.items())),
      "fundamental_quality":dict(sorted(quality.items())),"reason_counts":dict(sorted(reasons.items())),
      "reason_by_action":[{"action":a,"reason":r,"count":n} for (a,r),n in sorted(by_action.items())],
      "overlapping_reason_pairs":[{"a":a,"b":b,"count":n} for (a,b),n in sorted(pairs.items(),key=lambda kv:-kv[1])],
      "mixed_reason_codes":[r for r in sorted(reasons) if "_OR_UNAVAILABLE" in r],
      "limitations":["Mixed OR reasons cannot distinguish missing from unfavorable","No gate-distance or causal counterfactual","No official-source cache provenance","No matured OOS or paper outcomes"],
      "production_rules_changed":False,"promotion_authorized":False}

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--input",required=True);p.add_argument("--output",required=True)
    args=p.parse_args()
    src=Path(args.input)
    if not src.is_file():p.error("Real run snapshot required")
    result=audit(json.loads(src.read_text(encoding="utf-8-sig")))
    dst=Path(args.output);dst.parent.mkdir(parents=True,exist_ok=True)
    dst.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print("AUDIT DONE",result["count"],"stocks; mismatches",result["session_mismatches"])
