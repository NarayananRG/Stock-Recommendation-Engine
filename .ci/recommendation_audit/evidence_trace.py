"""Audit actionable evidence gaps using genuine local SRE active-run JSON. Read-only."""
import argparse,collections,json,math
from pathlib import Path

def inspect(payload):
    run=payload.get("run") or {};rows=payload.get("candidates")
    if not run.get("run_id") or not run.get("market_session") or not isinstance(rows,list):raise ValueError("Real run required")
    summary=collections.Counter();seen=set()
    for row in rows:
        symbol=str(row.get("symbol") or "").upper().removesuffix(".NS")
        if not symbol or symbol in seen:raise ValueError("Missing/duplicate symbol")
        seen.add(symbol)
        d=row.get("live_decision")
        if not isinstance(d,dict):raise ValueError("Missing live decision")
        e=d.get("evidence") or {};f=e.get("fundamental") or {} if isinstance(e,dict) else {}
        if not isinstance(f,dict):f={}
        sector="FINANCIAL" if d.get("financial_domain") is True else "OTHER_OR_UNKNOWN"
        b=f.get("balance_sheet") or {};b=b if isinstance(b,dict) else {}
        ratio=b.get("debt_equity_ratio")
        missing=ratio is None
        summary[("debt_ratio",sector+":"+("ABSENT" if missing else "PRESENT"))]+=1
        if missing:
            summary[("debt_ratio_source_field","BALANCE_SHEET_OBJECT_PRESENT" if isinstance(f.get("balance_sheet"),dict) else "BALANCE_SHEET_OBJECT_ABSENT")]+=1
            summary[("fundamental_available_for_missing_debt",str(f.get("available","ABSENT")) )]+=1
            summary[("fundamental_pit_for_missing_debt",str(f.get("point_in_time_safe","ABSENT")) )]+=1
        event=f.get("risk_event") or {};event=event if isinstance(event,dict) else {}
        if event.get("event_profile")=="MIXED_DIRECTIONAL":
            summary[("mixed_strong_transition",str(event.get("strong_deterioration_transition","ABSENT")))]+=1
            for group in ("deterioration_evidence","improvement_evidence"):
                records=event.get(group)
                if not isinstance(records,list):
                    summary[(group+"_details","ABSENT")]+=1;continue
                summary[(group+"_details","PRESENT")]+=1
                for rec in records:
                    if not isinstance(rec,dict):continue
                    feature=str(rec.get("feature") or "UNSPECIFIED")
                    summary[(group+"_feature",feature)]+=1
                    value=rec.get("symmetric_change")
                    try:
                        magnitude=abs(float(value))
                        if not math.isfinite(magnitude):raise ValueError
                        band="LT_0_05" if magnitude<0.05 else "LT_0_20" if magnitude<0.20 else "GTE_0_20"
                    except (TypeError,ValueError):band="MISSING"
                    summary[(group+"_abs_symmetric_change_band",band)]+=1
    return {"schema":"SRE_EVIDENCE_TRACE_V1","run_id":run["run_id"],"market_session":run["market_session"],"stocks":len(seen),
      "counts":[{"dimension":key,"value":value,"count":count} for (key,value),count in sorted(summary.items())],
      "limitations":["Symmetric change is a fraction (2*(current-previous)/(abs(current)+abs(previous))), not percent; bands 0.05 and 0.20 are descriptive","Magnitude counts are per feature-event, not per stock","Evidence lists may be absent in serialized adapter","Final snapshot alone cannot reveal canonical filing mapping failure codes"],
      "production_changed":False,"promotion_authorized":False}

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--input",required=True);p.add_argument("--output",required=True);a=p.parse_args()
    src=Path(a.input)
    if not src.is_file():p.error("Actual local active-run JSON required")
    report=inspect(json.loads(src.read_text(encoding="utf-8-sig")))
    dst=Path(a.output);dst.parent.mkdir(parents=True,exist_ok=True)
    dst.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print("EVIDENCE TRACE",report["stocks"])
