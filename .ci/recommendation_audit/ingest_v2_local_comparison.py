"""Ingest Codex's real V2 before/after CSV without fabricating missing evidence."""
from __future__ import annotations
import argparse,csv,hashlib,json
from collections import Counter
from pathlib import Path
BUY={"MOMENTUM BUY","RECOVERY BUY","MOMENTUM + RECOVERY BUY"}
def ingest(path:Path,expected:int=200)->dict:
    raw=path.read_bytes()
    rows=list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    if not rows:raise ValueError("EMPTY_REAL_EVIDENCE")
    required={"symbol","before_action","after_action"}
    if not required.issubset(rows[0]):raise ValueError("MISSING_REQUIRED_COLUMNS:"+",".join(sorted(required-set(rows[0]))))
    seen=set();deltas=[];before=Counter();after=Counter()
    for r in rows:
        sym=(r.get("symbol") or "").strip().upper().removesuffix(".NS")
        if not sym or sym in seen:raise ValueError("MISSING_OR_DUPLICATE_SYMBOL:"+sym)
        seen.add(sym)
        b=(r.get("before_action") or "").strip();a=(r.get("after_action") or "").strip()
        if not b or not a:raise ValueError("MISSING_ACTION:"+sym)
        before[b]+=1;after[a]+=1
        if b!=a:deltas.append({"symbol":sym,"before_action":b,"after_action":a})
    if len(seen)!=expected:raise ValueError(f"UNEXPECTED_UNIVERSE_COUNT:{len(seen)}")
    # An action containing BUY is not proof that an allocation is executable.
    return {"schema":"SRE_V2_REAL_REPORT_COMPARISON_V1","authority":"AUDIT_ONLY",
            "source_name":path.name,"source_sha256":hashlib.sha256(raw).hexdigest(),
            "source_type":"USER_PROVIDED_LOCAL_CSV","universe_count":len(rows),
            "before_actions":dict(sorted(before.items())),"after_actions":dict(sorted(after.items())),
            "changed_action_count":len(deltas),"changed_actions":deltas,
            "action_label_buy_counts":{"before":sum(n for a,n in before.items() if a in BUY),
                                       "after":sum(n for a,n in after.items() if a in BUY)},
            "verified_executable_buy_count":None,
            "fundamental_coverage_delta":None,
            "historical_forward_returns_validated":False,"production_changes":False,
            "limitations":["CSV lacks independent decision timestamp and full original evidence",
                           "BUY action label does not independently confirm execution",
                           "Fundamental profile coverage and PIT require original validated report"]}
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--expected-count",type=int,default=200)
    args=p.parse_args()
    result=ingest(args.source,args.expected_count)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:result[k] for k in ("universe_count","changed_action_count","action_label_buy_counts")},indent=2))
if __name__=="__main__":main()
