"""PIT-safe, read-only comparison of two *actual* serialized recommendation runs.

Only matched symbol/session evidence is comparable. This does not backtest.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

BUY={"MOMENTUM BUY","RECOVERY BUY","MOMENTUM + RECOVERY BUY"}
def load(path):
    raw=Path(path).read_bytes()
    data=json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data,dict) or not isinstance(data.get("run"),dict) or not isinstance(data.get("candidates"),list):
        raise ValueError("INVALID_ACTUAL_RUN_EXPORT")
    run=data["run"]
    if not isinstance(run.get("market_session"),str) or not isinstance(run.get("run_id"),str) or not run["run_id"]:
        raise ValueError("MISSING_RUN_PROVENANCE")
    date.fromisoformat(run["market_session"])
    rows={}
    for row in data["candidates"]:
        if not isinstance(row,dict) or not isinstance(row.get("live_decision"),dict):
            raise ValueError("INVALID_CANDIDATE")
        sym=row.get("symbol")
        if not isinstance(sym,str) or not sym.strip():raise ValueError("MISSING_SYMBOL")
        sym=sym.strip().upper().removesuffix(".NS")
        if sym in rows:raise ValueError("DUPLICATE_SYMBOL:"+sym)
        d=row["live_decision"]
        if d.get("market_session")!=run["market_session"]:
            raise ValueError("MIXED_DECISION_SESSIONS:"+sym)
        if not isinstance(d.get("executable"),bool):
            raise ValueError("INVALID_EXECUTION_FLAG:"+sym)
        if d.get("executable") and d.get("final_action") not in BUY:
            raise ValueError("EXECUTABLE_NON_BUY:"+sym)
        rows[sym]=d
    if not rows:raise ValueError("EMPTY_UNIVERSE")
    return run,rows,hashlib.sha256(raw).hexdigest()

def compare(before,after,expected_count=200):
    br,b,bhash=load(before);ar,a,ahash=load(after)
    if br["market_session"]!=ar["market_session"]:raise ValueError("DIFFERENT_MARKET_SESSIONS")
    if set(b)!=set(a):raise ValueError("UNIVERSE_MISMATCH")
    if expected_count is not None and len(b)!=expected_count:raise ValueError("UNEXPECTED_UNIVERSE_COUNT")
    changes=[]
    pre=Counter();post=Counter()
    for sym in sorted(b):
        old,new=b[sym],a[sym]
        old_action,new_action=old.get("final_action"),new.get("final_action")
        pre[(old_action,old["executable"])]+=1
        post[(new_action,new["executable"])]+=1
        if old_action!=new_action or old["executable"]!=new["executable"]:
            changes.append({"symbol":sym,"before_action":old_action,"after_action":new_action,
                            "before_executable":old["executable"],"after_executable":new["executable"]})
    buys=lambda rows:sum(d["executable"] and d.get("final_action") in BUY for d in rows.values())
    return {"schema":"SRE_VERIFIED_LIVE_SNAPSHOT_COMPARISON_V1","authority":"AUDIT_ONLY",
            "market_session":br["market_session"],"universe_count":len(b),
            "before_run_id":br["run_id"],"after_run_id":ar["run_id"],
            "before_sha256":bhash,"after_sha256":ahash,
            "before_executable_buys":buys(b),"after_executable_buys":buys(a),
            "changed_decisions":changes,"changed_decision_count":len(changes),
            "historical_forward_outcomes_validated":False,
            "investment_performance_claim_allowed":False,
            "production_changes":False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--before",required=True,type=Path)
    p.add_argument("--after",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--expected-count",type=int,default=200)
    args=p.parse_args()
    result=compare(args.before,args.after,args.expected_count)
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/"comparison.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    with (args.out/"changed_decisions.csv").open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=["symbol","before_action","after_action","before_executable","after_executable"])
        writer.writeheader();writer.writerows(result["changed_decisions"])
    print("VERIFIED LIVE SNAPSHOT COMPARISON:",result["universe_count"],"symbols;",result["changed_decision_count"],"changes")
if __name__=="__main__":main()
