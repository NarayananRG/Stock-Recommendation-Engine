from pathlib import Path
import json
import os
import sys

out=Path(os.environ["SRE_SCARCITY_AUDIT_OUT"])
report=json.loads((out/"scarcity_audit.json").read_text(encoding="utf-8"))
today=report["today"]
u=int(today["universe"])
buy=int(today["buy_count"])
mom=today["momentum_gate_failure_counts"]
rec=today["recovery_gate_failure_counts"]
profiles={p["symbol"]:p for p in today.get("near_recovery",[])}
all_profiles={}
with (out/"near_misses.csv").open(encoding="utf-8") as h:
    import csv
    for row in csv.DictReader(h):
        all_profiles[row["symbol"]]=row

assert u==200,report
assert rec.get("domain_safety_ready",0)<200,rec
assert mom.get("domain_safety_ready",0)<200,mom
assert buy>=1,report
for symbol in ("GODREJCP","HINDZINC","OFSS"):
    row=all_profiles.get(symbol)
    assert row is not None,symbol
    print(symbol,row.get("final_action"),row.get("recovery_failures"))
assert report.get("policy_changes") is False
assert report.get("threshold_changes") is False
assert report.get("provider_policy_changes") is False
print(json.dumps({
  "universe":u,
  "buy_count":buy,
  "actions":today["actions"],
  "domain_safety_momentum_failures":mom.get("domain_safety_ready"),
  "domain_safety_recovery_failures":rec.get("domain_safety_ready"),
  "root_cause_classification":report.get("root_cause_classification"),
},indent=2))
print("0.14.9 SCARCITY REPAIR ACCEPTANCE PASS")
