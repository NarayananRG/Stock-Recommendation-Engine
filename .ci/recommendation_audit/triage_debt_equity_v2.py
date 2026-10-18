"""Read-only triage of V2 debt/equity gaps from the real coverage matrix.

This script does not derive financial ratios or change recommendation authority.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

VERIFIED={"AVAILABLE_VERIFIED","DERIVABLE_FROM_VERIFIED_FACTS"}
INAPPLICABLE="FINANCIAL_DOMAIN_NOT_APPLICABLE"
COMPONENTS=("TOTAL_DEBT","SHAREHOLDERS_EQUITY")

def triage(matrix_path:Path,expected_symbols:int=200,expected_metrics:int=34)->dict:
    raw=matrix_path.read_bytes()
    rows=list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    required={"symbol","metric","after_status","domain","quarter_end","reporting_basis","publication_ts","event_id","source_url"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError("INCOMPLETE_V2_MATRIX_SCHEMA")
    if len(rows)!=expected_symbols*expected_metrics:raise ValueError("MATRIX_CELL_COUNT_MISMATCH")
    by_symbol=defaultdict(dict)
    for row in rows:
        sym=(row["symbol"] or "").strip().upper().removesuffix(".NS")
        metric=(row["metric"] or "").strip()
        if not sym or not metric or metric in by_symbol[sym]:raise ValueError("DUPLICATE_OR_MISSING_SYMBOL_METRIC")
        by_symbol[sym][metric]=row
    if len(by_symbol)!=expected_symbols or any(len(m)!=expected_metrics for m in by_symbol.values()):
        raise ValueError("INCOMPLETE_SYMBOL_COVERAGE")
    findings=[];counts=Counter();status_counts=Counter()
    for sym,metrics in sorted(by_symbol.items()):
        de=metrics.get("DEBT_EQUITY_RATIO")
        if de is None:raise ValueError("DEBT_EQUITY_ROW_REQUIRED")
        status=de["after_status"];status_counts[status]+=1
        if status in VERIFIED or status==INAPPLICABLE:continue
        components={key:metrics.get(key) for key in COMPONENTS}
        if status=="UNVERIFIABLE":
            classification="OFFICIAL_VALUE_FAILED_VERIFICATION"
        elif status in {"SOURCE_NOT_ACQUIRED","SOURCE_PARSE_FAILURE"}:
            classification="ACQUISITION_OR_PARSE_GAP"
        elif status in {"PERIOD_MISMATCH","REPORTING_BASIS_MISMATCH"}:
            classification="PERIOD_OR_BASIS_MISMATCH"
        elif all(components.values()) and all((r["after_status"]=="AVAILABLE_BUT_NOT_MAPPED") for r in components.values()):
            classification="COMPONENT_MAPPING_REVIEW"
        elif any(r and r["after_status"]=="AVAILABLE_BUT_NOT_MAPPED" for r in components.values()):
            classification="PARTIAL_COMPONENT_MAPPING_REVIEW"
        else:
            classification="OFFICIAL_COMPONENTS_NOT_VERIFIED"
        record={"symbol":sym,"domain":de["domain"],"de_status":status,
                "classification":classification,"quarter_end":de["quarter_end"],
                "reporting_basis":de["reporting_basis"],"publication_ts":de["publication_ts"],
                "source_url":de["source_url"],"event_id":de["event_id"],
                "component_statuses":{key:(r["after_status"] if r else "NO_MATRIX_ROW") for key,r in components.items()},
                "safe_to_derive_debt_equity":False,
                "required_next_step":"Verify official component values, matching period, basis, equity sign, and PIT publication timestamp"}
        findings.append(record);counts[classification]+=1
    return {"schema":"SRE_DEBT_EQUITY_GAP_TRIAGE_V1","authority":"AUDIT_ONLY",
            "source_sha256":hashlib.sha256(raw).hexdigest(),
            "symbol_count":len(by_symbol),"metric_count":expected_metrics,"gap_count":len(findings),
            "de_status_counts":dict(sorted(status_counts.items())),
            "triage_counts":dict(sorted(counts.items())),"findings":findings,
            "production_actions_changed":0,"ratios_derived":0,"promotion_allowed":False,
            "limitations":["A detected concept is not a verified usable value",
                           "No cross-period or cross-basis substitution permitted",
                           "No inferred debt/equity and no automatic BUY promotion"]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--matrix",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--expected-symbols",type=int,default=200)
    p.add_argument("--expected-metrics",type=int,default=34)
    a=p.parse_args()
    if not a.matrix.is_file():p.error("Actual V2 matrix required, no generated fallback")
    result=triage(a.matrix,a.expected_symbols,a.expected_metrics)
    a.out.mkdir(parents=True,exist_ok=True)
    (a.out/"debt_equity_triage.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    columns=("symbol","domain","de_status","classification","quarter_end","reporting_basis","publication_ts","source_url","event_id")
    with (a.out/"debt_equity_triage.csv").open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader()
        for record in result["findings"]:w.writerow({key:record[key] for key in columns})
    print(json.dumps({key:result[key] for key in ("gap_count","de_status_counts","triage_counts")},indent=2))
if __name__=="__main__":main()
