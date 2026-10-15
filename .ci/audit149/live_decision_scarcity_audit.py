from __future__ import annotations

import csv
import json
import math
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from statistics import mean, median

ROOT = Path(os.environ["SRE_ENGINE_ROOT"]).resolve()
sys.path.insert(0, str(ROOT))
os.environ.setdefault("STOCK_MODERN_UI_PREVIEW", "0")
os.environ.setdefault("SRE_EXPECTED_SESSION_NOW", "2026-10-15T19:45:00+05:30")

from modern_ui.api import ModernAppContext

OUT = Path(os.environ.get("SRE_SCARCITY_AUDIT_OUT", str(Path.cwd() / "work" / "scarcity-audit")))
OUT.mkdir(parents=True, exist_ok=True)
APP_DATA = Path(tempfile.mkdtemp(prefix="sre-scarcity-audit-"))
ctx = ModernAppContext(repo_root=ROOT, app_data_dir=APP_DATA)

BUY_ACTIONS = {"MOMENTUM BUY", "RECOVERY BUY", "MOMENTUM + RECOVERY BUY"}

def num(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):
        return None

def gate_profile(row):
    live=row.get("live_decision") or {}
    ev=live.get("evidence") or {}
    tech=ev.get("technical") or {}
    pc=ev.get("price_context") or {}
    fundamental=ev.get("fundamental") or {}
    atr=num((tech.get("volatility") or {}).get("atr_pct"))
    trend=tech.get("trend") or {}
    close=num(trend.get("close"))
    support=num(pc.get("prior_support"))
    regime=(tech.get("market_context") or {}).get("nifty_regime")
    financial=live.get("financial_domain") is True
    business_ready=live.get("business_health") in ("HEALTHY","STRONG")
    earnings_ready=live.get("earnings_direction") in ("STABLE","IMPROVING")
    event_ready=live.get("fundamental_event_state") in ("STABLE","IMPROVING")
    fundamental_ready=business_ready and earnings_ready and event_ready
    cash_ready=live.get("cash_flow_state") in ("SUPPORTIVE","ADEQUATE")
    balance_ready=live.get("balance_sheet_state") in ("HEALTHY","ACCEPTABLE")
    domain_ready=(live.get("financial_domain_ready") is True) if financial else (cash_ready and balance_ready)
    safety=live.get("fundamental_data_quality")=="AVAILABLE" and live.get("structural_deterioration") is not True
    strong=live.get("technical_state")=="STRONG"
    depressed=live.get("price_condition")=="DEPRESSED"
    breakdown=live.get("technical_state")=="BREAKDOWN"
    downside=(not breakdown and atr is not None and atr<=6 and close is not None and support is not None and support>0 and close>=support*.97)
    official=(ev.get("official_current") is True)
    valuation=live.get("valuation_state") in ("ATTRACTIVE","REASONABLE")
    momentum={
        "official_current":official,
        "technical_strong":strong,
        "fundamental_quality_and_no_deterioration":safety,
        "business_earnings_event_ready":fundamental_ready,
        "atr_le_6":atr is not None and atr<=6,
        "domain_safety_ready":domain_ready,
        "market_regime_bull_or_mixed":regime in ("BULL","MIXED"),
    }
    recovery={
        "official_current":official,
        "price_depressed_15pct_plus":depressed,
        "fundamental_quality_and_no_deterioration":safety,
        "business_earnings_event_ready":fundamental_ready,
        "domain_safety_ready":domain_ready,
        "downside_controlled":downside,
        "pit_relative_valuation_attractive_or_reasonable":valuation,
    }
    return {
        "symbol":row.get("symbol"),
        "rank":row.get("rank"),
        "final_action":live.get("final_action"),
        "confidence":live.get("confidence"),
        "technical_state":live.get("technical_state"),
        "business_health":live.get("business_health"),
        "fundamental_quality":live.get("fundamental_data_quality"),
        "valuation_state":live.get("valuation_state"),
        "price_condition":live.get("price_condition"),
        "cash_flow_state":live.get("cash_flow_state"),
        "balance_sheet_state":live.get("balance_sheet_state"),
        "financial_domain":financial,
        "financial_domain_ready":live.get("financial_domain_ready"),
        "atr_pct":atr,
        "nifty_regime":regime,
        "reason_codes":list(live.get("reason_codes") or []),
        "missing_evidence":list(live.get("missing_evidence") or []),
        "momentum_failures":[k for k,v in momentum.items() if not v],
        "recovery_failures":[k for k,v in recovery.items() if not v],
        "momentum_passed":sum(momentum.values()),
        "momentum_total":len(momentum),
        "recovery_passed":sum(recovery.values()),
        "recovery_total":len(recovery),
    }

def summarize_rows(rows):
    profiles=[gate_profile(r) for r in rows]
    actions=Counter(p["final_action"] for p in profiles)
    reasons=Counter(code for p in profiles for code in p["reason_codes"])
    missing=Counter(item for p in profiles for item in p["missing_evidence"])
    mom_fail=Counter(x for p in profiles for x in p["momentum_failures"])
    rec_fail=Counter(x for p in profiles for x in p["recovery_failures"])
    mom_single=Counter(p["momentum_failures"][0] for p in profiles if len(p["momentum_failures"])==1)
    rec_single=Counter(p["recovery_failures"][0] for p in profiles if len(p["recovery_failures"])==1)
    near_m=sorted(profiles,key=lambda p:(len(p["momentum_failures"]),p["rank"] or 10**9,p["symbol"] or ""))[:15]
    near_r=sorted(profiles,key=lambda p:(len(p["recovery_failures"]),p["rank"] or 10**9,p["symbol"] or ""))[:15]
    return {
        "universe":len(profiles),
        "buy_count":sum(actions[a] for a in BUY_ACTIONS),
        "actions":dict(actions),
        "reason_code_counts":dict(reasons.most_common()),
        "missing_evidence_counts":dict(missing.most_common()),
        "momentum_gate_failure_counts":dict(mom_fail.most_common()),
        "recovery_gate_failure_counts":dict(rec_fail.most_common()),
        "momentum_single_gate_near_misses":dict(mom_single.most_common()),
        "recovery_single_gate_near_misses":dict(rec_single.most_common()),
        "near_momentum":near_m,
        "near_recovery":near_r,
        "profiles":profiles,
    }

flow=ctx.run_post_close_daily_flow(force=True)
status=ctx.post_close_daily_status()
rows=ctx.latest_prediction_rows(limit=200)
coverage=ctx.live_coverage()
today=summarize_rows(rows)

if status.get("analysis_current") is not True:
    raise RuntimeError("Audit requires current analysis session: "+json.dumps(status,default=str))
if len(rows) < 150:
    raise RuntimeError("Audit universe unexpectedly small: "+str(len(rows)))

# Gate dominance and scarcity classification.
u=max(1,today["universe"])
dominance=[]
for lane,key in (("MOMENTUM","momentum_gate_failure_counts"),("RECOVERY","recovery_gate_failure_counts")):
    for gate,count in today[key].items():
        dominance.append({"lane":lane,"gate":gate,"count":count,"pct":round(100*count/u,1)})
dominance.sort(key=lambda x:(-x["pct"],x["lane"],x["gate"]))

# Sampled historical restrictiveness replay using the exact current router and PIT
# cutoffs. This is a scarcity diagnostic, NOT a performance backtest: it uses the
# current universe and therefore has survivorship bias.
index_bars=[]
for sym in ("INDEX_NSEI","NSEI","^NSEI","NIFTY"):
    try:
        index_bars=ctx.prices.history(sym,limit=5000)
    except Exception:
        index_bars=[]
    if index_bars:
        break
sessions=sorted({str(b.get("date"))[:10] for b in index_bars if str(b.get("date") or "")[:10] <= str(status.get("target_session") or "")})
sample_sessions=list(reversed(sessions))[::21][:7]
sample_sessions=list(reversed(sample_sessions))
historical=[]
original_gate=ctx._daily_data_gate
try:
    for session in sample_sessions:
        ctx._daily_data_gate=lambda s=session: {"ready":True,"target_session":s}
        synthetic={
            "run":{
                "run_id":"scarcity-audit-"+session,
                "market_session":session,
                "horizon_sessions":20,
                "investment_capital":100000.0,
                "target_return":None,
            },
            "candidates":[],
        }
        materialized=ctx._materialize_live_run(synthetic)
        sr=summarize_rows(materialized.get("candidates") or [])
        historical.append({
            "session":session,
            "universe":sr["universe"],
            "buy_count":sr["buy_count"],
            "actions":sr["actions"],
            "top_momentum_gate_failures":list(sr["momentum_gate_failure_counts"].items())[:5],
            "top_recovery_gate_failures":list(sr["recovery_gate_failure_counts"].items())[:5],
        })
finally:
    ctx._daily_data_gate=original_gate

hist_buy_counts=[x["buy_count"] for x in historical]
historical_summary={
    "method":"CURRENT_LIVE_DECISION_V1_PIT_SAMPLED_REPLAY",
    "sample_sessions":len(historical),
    "sessions":historical,
    "sessions_with_any_buy":sum(x>0 for x in hist_buy_counts),
    "sessions_with_zero_buys":sum(x==0 for x in hist_buy_counts),
    "mean_buys_per_sampled_session":round(mean(hist_buy_counts),3) if hist_buy_counts else None,
    "median_buys_per_sampled_session":median(hist_buy_counts) if hist_buy_counts else None,
    "max_buys_in_sampled_session":max(hist_buy_counts) if hist_buy_counts else None,
    "limitations":[
        "Sampled sessions are approximately 21 trading sessions apart, not every trading day.",
        "The current 200-stock universe is replayed historically, so survivorship bias remains.",
        "This measures rule restrictiveness only; it is not a profitability or promotion backtest.",
        "Fundamental and valuation evidence are reconstructed at each historical cutoff by the production PIT functions.",
    ],
}

coverage_summary={
    k:coverage.get(k) for k in (
        "universe_size","fundamental_ready","fundamental_partial","fundamental_unavailable",
        "financial_domain_count","nonfinancial_count","lane_counts","blocker_counts","feature_coverage_counts"
    )
}

report={
    "schema":"SRE_LIVE_DECISION_SCARCITY_AUDIT_V1",
    "audit_type":"READ_ONLY_NO_POLICY_CHANGE",
    "authority":"LIVE_DECISION_V1",
    "release":status.get("last_successful_daily_run",{}).get("model_version") or "0.14.8-analysis-refresh-execution-repair",
    "market_session":status.get("active_analysis_session"),
    "official_session":status.get("latest_available_official_session"),
    "analysis_current":status.get("analysis_current"),
    "today":{
        **{k:v for k,v in today.items() if k!="profiles"},
        "coverage":coverage_summary,
        "dominant_gate_failures":dominance[:20],
    },
    "historical_restrictiveness_sample":historical_summary,
    "policy_changes":False,
    "threshold_changes":False,
    "provider_policy_changes":False,
}

# Objective audit verdict.
top=dominance[0] if dominance else None
if today["buy_count"]>0:
    verdict="BUYS_PRESENT"
elif top and top["pct"]>=80:
    verdict="ZERO_BUYS_WITH_DOMINANT_GATE"
elif sum(1 for p in today["profiles"] if len(p["momentum_failures"])<=1 or len(p["recovery_failures"])<=1) >= 10:
    verdict="ZERO_BUYS_MANY_NEAR_MISSES"
else:
    verdict="ZERO_BUYS_BROAD_MULTI_GATE_REJECTION"
report["verdict"]=verdict

(OUT/"scarcity_audit.json").write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")

with (OUT/"near_misses.csv").open("w",newline="",encoding="utf-8") as h:
    fields=["symbol","rank","final_action","confidence","technical_state","business_health","fundamental_quality","valuation_state","price_condition","financial_domain","atr_pct","nifty_regime","momentum_failures","recovery_failures","reason_codes","missing_evidence"]
    w=csv.DictWriter(h,fieldnames=fields);w.writeheader()
    for p in sorted(today["profiles"],key=lambda x:(min(len(x["momentum_failures"]),len(x["recovery_failures"])),x["rank"] or 10**9)):
        q={k:p.get(k) for k in fields}
        for k in ("momentum_failures","recovery_failures","reason_codes","missing_evidence"):
            q[k]=" | ".join(q[k] or [])
        w.writerow(q)

md=[]
md.append("# LIVE_DECISION_V1 Recommendation Scarcity Audit")
md.append("")
md.append(f"- Session: **{report['market_session']}**")
md.append(f"- Universe: **{today['universe']}**")
md.append(f"- Executable BUY decisions: **{today['buy_count']}**")
md.append(f"- Verdict: **{verdict}**")
md.append("- Recommendation/model/threshold/provider changes: **NONE**")
md.append("")
md.append("## Current action distribution")
for k,v in today["actions"].items(): md.append(f"- {k}: {v}")
md.append("")
md.append("## Top route reason codes")
for k,v in list(today["reason_code_counts"].items())[:15]: md.append(f"- {k}: {v} ({100*v/u:.1f}%)")
md.append("")
md.append("## Momentum gate failures")
for k,v in today["momentum_gate_failure_counts"].items(): md.append(f"- {k}: {v} ({100*v/u:.1f}%)")
md.append("")
md.append("## Recovery gate failures")
for k,v in today["recovery_gate_failure_counts"].items(): md.append(f"- {k}: {v} ({100*v/u:.1f}%)")
md.append("")
md.append("## Single-gate near misses")
md.append("### Momentum")
for k,v in today["momentum_single_gate_near_misses"].items(): md.append(f"- {k}: {v}")
md.append("### Recovery")
for k,v in today["recovery_single_gate_near_misses"].items(): md.append(f"- {k}: {v}")
md.append("")
md.append("## Closest Momentum candidates")
for p in today["near_momentum"][:10]:
    md.append(f"- {p['symbol']}: {len(p['momentum_failures'])} failed gate(s) — {', '.join(p['momentum_failures']) or 'QUALIFIED'}")
md.append("")
md.append("## Closest Recovery candidates")
for p in today["near_recovery"][:10]:
    md.append(f"- {p['symbol']}: {len(p['recovery_failures'])} failed gate(s) — {', '.join(p['recovery_failures']) or 'QUALIFIED'}")
md.append("")
md.append("## Evidence coverage")
md.append(f"- Fundamental ready: {coverage.get('fundamental_ready')}")
md.append(f"- Fundamental partial: {coverage.get('fundamental_partial')}")
md.append(f"- Fundamental unavailable: {coverage.get('fundamental_unavailable')}")
md.append(f"- Financial-domain symbols: {coverage.get('financial_domain_count')}")
for name,counts in (coverage.get("feature_coverage_counts") or {}).items():
    md.append(f"- {name}: {counts}")
md.append("")
md.append("## Sampled historical restrictiveness")
for x in historical:
    md.append(f"- {x['session']}: {x['buy_count']} BUY(s) / {x['universe']} symbols")
md.append(f"- Sessions with any BUY: {historical_summary['sessions_with_any_buy']} / {historical_summary['sample_sessions']}")
md.append(f"- Mean BUYs per sampled session: {historical_summary['mean_buys_per_sampled_session']}")
md.append("")
md.append("### Historical replay limitations")
for x in historical_summary["limitations"]: md.append(f"- {x}")
(OUT/"scarcity_audit.md").write_text("\n".join(md)+"\n",encoding="utf-8")

print(json.dumps({
    "verdict":verdict,
    "market_session":report["market_session"],
    "universe":today["universe"],
    "buy_count":today["buy_count"],
    "actions":today["actions"],
    "top_reason_codes":list(today["reason_code_counts"].items())[:12],
    "momentum_gate_failures":today["momentum_gate_failure_counts"],
    "recovery_gate_failures":today["recovery_gate_failure_counts"],
    "momentum_single_gate":today["momentum_single_gate_near_misses"],
    "recovery_single_gate":today["recovery_single_gate_near_misses"],
    "near_momentum":[{"symbol":p["symbol"],"failures":p["momentum_failures"]} for p in today["near_momentum"][:10]],
    "near_recovery":[{"symbol":p["symbol"],"failures":p["recovery_failures"]} for p in today["near_recovery"][:10]],
    "fundamental_ready":coverage.get("fundamental_ready"),
    "fundamental_partial":coverage.get("fundamental_partial"),
    "fundamental_unavailable":coverage.get("fundamental_unavailable"),
    "historical_sample":historical_summary,
},indent=2,default=str))
