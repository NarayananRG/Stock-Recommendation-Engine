from __future__ import annotations
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT=Path(os.environ["SRE_ENGINE_ROOT"]).resolve()
sys.path.insert(0,str(ROOT))
os.environ.setdefault("STOCK_MODERN_UI_PREVIEW","0")
os.environ.setdefault("SRE_EXPECTED_SESSION_NOW","2026-10-15T19:45:00+05:30")

from modern_ui.api import ModernAppContext

out=Path(os.environ.get("SRE_0149_AUDIT_OUT",str(Path.cwd()/"work"/"0149-current-audit")))
out.mkdir(parents=True,exist_ok=True)
ctx=ModernAppContext(repo_root=ROOT,app_data_dir=Path(tempfile.mkdtemp(prefix="sre0149-current-")))

flow=ctx.run_post_close_daily_flow(force=True)
status=ctx.post_close_daily_status()
rows=ctx.latest_prediction_rows(limit=200)

if status.get("analysis_current") is not True:
    raise RuntimeError("CURRENT_ANALYSIS_REQUIRED:"+json.dumps(status,default=str))
if len(rows)!=200:
    raise RuntimeError("EXPECTED_200_ROWS_GOT_"+str(len(rows)))

buy_actions={"MOMENTUM BUY","RECOVERY BUY","MOMENTUM + RECOVERY BUY"}
actions=Counter()
domain_blocked=0
symbols={}
for row in rows:
    live=row.get("live_decision") or {}
    action=str(live.get("final_action") or "")
    actions[action]+=1
    financial=live.get("financial_domain") is True
    if financial:
        domain_ready=live.get("financial_domain_ready") is True
    else:
        domain_ready=(
            live.get("cash_flow_state") in ("SUPPORTIVE","ADEQUATE")
            and live.get("balance_sheet_state") in ("HEALTHY","ACCEPTABLE")
        )
    domain_blocked+=int(not domain_ready)
    symbols[str(row.get("symbol") or "")]={
        "action":action,
        "executable":live.get("executable") is True,
        "balance_sheet_state":live.get("balance_sheet_state"),
        "cash_flow_state":live.get("cash_flow_state"),
        "financial_domain":financial,
        "financial_domain_state":live.get("financial_domain_state"),
        "reason_codes":live.get("reason_codes") or [],
        "supplement":((live.get("evidence") or {}).get("fundamental") or {}).get("pit_safety_supplement"),
    }

buy_count=sum(actions[x] for x in buy_actions)
near={s:symbols.get(s) for s in ("BDL","BSE","GODREJCP","HINDZINC","OFSS")}
report={
    "schema":"SRE_0149_CURRENT_EVIDENCE_REPAIR_AUDIT_V1",
    "market_session":status.get("active_analysis_session"),
    "universe":len(rows),
    "buy_count":buy_count,
    "actions":dict(actions),
    "domain_safety_blocked":domain_blocked,
    "near_miss_symbols":near,
    "recommendation_logic_changed":False,
    "thresholds_changed":False,
    "provider_policy_changed":False,
    "automatic_yfinance_fallback":False,
}
(out/"current_evidence_repair_audit.json").write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")

# Acceptance: the structural 200/200 safety deadlock must be broken by evidence,
# not policy relaxation. The three previously single-gate near-misses with a
# display-validated official ratio should now qualify under unchanged rules.
assert domain_blocked < 200,report
assert buy_count >= 1,report
for symbol in ("GODREJCP","HINDZINC","OFSS"):
    item=symbols.get(symbol)
    assert item is not None,(symbol,report)
    assert item["supplement"] and item["supplement"].get("applied") is True,(symbol,item)
    assert item["action"]=="RECOVERY BUY",(symbol,item)
    assert item["executable"] is True,(symbol,item)

# Missing official facts stay missing; no zero-fill.
for symbol in ("BDL","BSE"):
    item=symbols.get(symbol)
    assert item is not None,(symbol,report)
    supplement=item.get("supplement") or {}
    assert supplement.get("applied") is not True,(symbol,item)

print(json.dumps(report,indent=2,default=str))
print("0.14.9 CURRENT EVIDENCE REPAIR AUDIT PASS")
