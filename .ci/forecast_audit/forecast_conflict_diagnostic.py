"""Diagnostic-only forecast conflict audit. Does not change recommendation authority."""
import argparse,json,math
from pathlib import Path

SYMBOLS=("GODREJCP","HINDZINC")
def finite(x):
    try:
        y=float(x)
        return y if math.isfinite(y) else None
    except (TypeError,ValueError):return None

def classify(row, run):
    live=row.get("live_decision") or {}
    evidence=live.get("evidence") or {}
    tech=evidence.get("technical") or {}
    analogues=tech.get("historical_analogues") or {}
    legacy=evidence.get("legacy_production_evidence") or {}
    horizon=run.get("horizon_sessions")
    legacy_return=finite(row.get("expected_return"))
    if legacy_return is None:legacy_return=finite(legacy.get("expected_return"))
    median=finite(analogues.get("median_forward_return"))
    sample=analogues.get("sample_size")
    pos=finite(analogues.get("positive_rate"))
    a_horizon=analogues.get("horizon_sessions")
    a_status=analogues.get("status")
    conflict=(legacy_return is not None and median is not None and
              (legacy_return>0>median or median>0>legacy_return))
    severity="UNKNOWN"
    if conflict:
        severity="MATERIAL" if abs(legacy_return-median)>=0.03 else "DIRECTIONAL"
    elif legacy_return is not None and median is not None:severity="NO_SIGN_CONFLICT"
    issues=[]
    if conflict:issues.append("FORECAST_DIRECTION_CONFLICT")
    if horizon != a_horizon:issues.append("ANALOGUE_HORIZON_MISMATCH")
    review=live.get("review_after_sessions")
    if isinstance(review,int) and horizon != review:issues.append("RECOMMENDATION_REVIEW_HORIZON_DIFFERS_FROM_FORECAST")
    if a_status!="READY" or not isinstance(sample,int) or sample<20:issues.append("ANALOGUE_SUPPORT_LIMITED")
    if pos is not None and pos<0.35:issues.append("LOW_POSITIVE_ANALOGUE_RATE")
    if str(live.get("market_session"))!=str(run.get("market_session")):issues.append("SESSION_MISMATCH")
    issues.append("LEGACY_FORECAST_CALIBRATION_NOT_ESTABLISHED")
    return {
        "symbol":row.get("symbol"),"decision":live.get("final_action"),
        "legacy_expected_return_fraction":legacy_return,"technical_analogue_median_fraction":median,
        "technical_analogue_positive_rate":pos,"technical_analogue_sample_size":sample,
        "technical_analogue_status":a_status,"market_session":run.get("market_session"),
        "forecast_horizon_sessions":horizon,"analogue_horizon_sessions":a_horizon,
        "recovery_review_after_sessions":review,"conflict_severity":severity,
        "flags":issues,"recommendation_authority_changed":False
    }

def audit(payload):
    run=payload.get("run")
    rows=payload.get("candidates")
    if not isinstance(run,dict) or not isinstance(rows,list):raise ValueError("Expected original active run with run and candidates")
    output=[]
    for symbol in SYMBOLS:
        matches=[x for x in rows if isinstance(x,dict) and str(x.get("symbol","")).upper().removesuffix(".NS")==symbol]
        if len(matches)>1:raise ValueError("Duplicate "+symbol)
        if matches:output.append(classify(matches[0],run))
    return {"schema":"SRE_FORECAST_CONFLICT_HORIZON_DIAGNOSTIC_V1",
        "authority":"READ_ONLY_NO_PROMOTION", "run_id":run.get("run_id"),
        "market_session":run.get("market_session"),"results":output,
        "ready_for_trading_rule_change":False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",required=True);p.add_argument("--output",required=True)
    a=p.parse_args()
    result=audit(json.loads(Path(a.input).read_text(encoding="utf-8-sig")))
    Path(a.output).write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))
if __name__=="__main__":main()
