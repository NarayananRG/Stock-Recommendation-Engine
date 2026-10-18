"""Conservative, read-only and sector-aware evidence inventory."""
import argparse,json,math
from collections import Counter
from pathlib import Path

def valid(x):
    return not isinstance(x,bool) and isinstance(x,(int,float)) and math.isfinite(x)

def assess(f,t):
    f=f or {};t=t or {}
    fin=f.get("sector_profile")=="FINANCIAL_DOMAIN_CONSERVATIVE"
    growth=f.get("growth") or {}
    missing=[k for k in ("revenue_yoy_symmetric_pct","pat_yoy_symmetric_pct","eps_yoy_symmetric_pct") if not valid(growth.get(k))]
    recovery=list(missing)
    if fin:
        recovery.append("financial_domain_specialized_policy")
    else:
        if not valid((f.get("balance_sheet") or {}).get("debt_equity_ratio")):recovery.append("debt_equity")
        if not valid((f.get("cash_flow") or {}).get("latest_operating_cash_flow")):recovery.append("operating_cash_flow")
    if (f.get("valuation") or {}).get("pit_comparison_available") is not True:recovery.append("pit_relative_valuation")
    safe=f.get("available") is True and f.get("point_in_time_safe") is True and f.get("filing_freshness") in ("CURRENT_FOR_DECISION_TIME","CURRENT")
    adverse=(f.get("risk_event") or {}).get("strong_deterioration_transition") is True
    # A negative industrial debt/equity ratio can indicate negative equity; it is not missing data, but must not certify readiness.
    abnormal_equity=(not fin and valid((f.get("balance_sheet") or {}).get("debt_equity_ratio")) and (f.get("balance_sheet") or {})["debt_equity_ratio"]<0)
    return {"financial_domain":fin,"inapplicable_industrial_metrics":["debt_equity","operating_cash_flow"] if fin else [],
            "missing_growth_metrics":missing,"missing_recovery_evidence":recovery,"adverse_transition":adverse,"negative_equity_or_ratio_warning":abnormal_equity,
            "momentum_evidence_ready":safe and not missing and t.get("status")=="READY" and (t.get("multi_timeframe") or {}).get("weekly_trend_confirmed") is True and not adverse and not abnormal_equity,
            "recovery_evidence_ready":safe and not recovery and not adverse and not abnormal_equity}
def inventory(payload):
    rows=payload.get("candidates") if isinstance(payload,dict) else None
    if not isinstance(rows,list) or len(rows)!=200:raise ValueError("ACTUAL_200_STOCK_EXPORT_REQUIRED")
    counts=Counter();reasons=Counter();detail=[];seen=set()
    for row in rows:
        sym=str(row.get("symbol") or "").upper().removesuffix(".NS")
        if not sym or sym in seen:raise ValueError("DUPLICATE_OR_MISSING_SYMBOL")
        seen.add(sym)
        e=(row.get("live_decision") or {}).get("evidence") or {}
        d=assess(e.get("fundamental"),e.get("technical"))
        for key in ("momentum_evidence_ready","recovery_evidence_ready"):counts[key]+=int(d[key])
        for reason in d["missing_recovery_evidence"]:reasons[reason]+=1
        detail.append({"symbol":sym,**d})
    return {"schema":"SRE_EVIDENCE_INVENTORY_SHADOW_V1","authority":"SHADOW_ONLY","ready_counts":dict(counts),"missing_reasons":dict(reasons),"details":detail,"production_actions_changed":0,"promotion_allowed":False}
def main():
    p=argparse.ArgumentParser();p.add_argument("--snapshot",required=True,type=Path);p.add_argument("--output",required=True,type=Path);a=p.parse_args()
    if not a.snapshot.is_file():p.error("Real run export required")
    r=inventory(json.loads(a.snapshot.read_text(encoding="utf-8-sig")))
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,indent=2)+"\n")
if __name__=="__main__":main()
