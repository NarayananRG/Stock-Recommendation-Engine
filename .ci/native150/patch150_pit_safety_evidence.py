from pathlib import Path
import os

root=Path(os.environ["SRE_ENGINE_ROOT"])

def replace_once(path:Path,old:str,new:str,label:str):
    text=path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(label+" patch point missing")
    path.write_text(text.replace(old,new,1),encoding="utf-8")

api=root/"modern_ui"/"api.py"
replace_once(
    api,
    'APP_VERSION = "0.14.8-analysis-refresh-execution-repair"',
    'APP_VERSION = "0.14.9-pit-safety-evidence-repair"',
    "release identity",
)

# The LIVE_DECISION_V1 router itself is intentionally untouched. Only the
# official PIT evidence feeding Fundamental V3 is extended.

fund=root/"stock_app"/"fundamental_v3.py"
s=fund.read_text(encoding="utf-8")

anchor="\ndef analyze(\n"
if anchor not in s:
    raise RuntimeError("fundamental analyze anchor missing")

helper=r'''
def _pit_safety_supplement_path(root: Path) -> Path | None:
    candidates=[]
    for base in _candidate_roots(root):
        candidates.append(
            base / "NextGen Research" / "results" / "pit_safety_supplement_v1" / "pit_safety_supplement.jsonl"
        )
    existing=[p for p in candidates if p.exists() and p.is_file()]
    return max(existing,key=lambda p:(p.stat().st_mtime_ns,str(p))) if existing else None


def _merge_pit_safety_supplement(
    root: Path,
    symbol: str,
    cutoff: datetime,
    basis: str | None,
    history: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path=_pit_safety_supplement_path(root)
    meta={
        "authority":"OFFICIAL_PIT_EVIDENCE_SUPPLEMENT",
        "status":"SUPPLEMENT_NOT_PRESENT" if path is None else "NO_ELIGIBLE_ROW",
        "path":str(path) if path else None,
        "feature":"DEBT_EQUITY_RATIO",
        "applied":False,
    }
    if path is None:
        return [dict(x) for x in history],meta

    wanted=_symbol(symbol)
    eligible=[]
    for row in _read_rows(path):
        if _symbol(row.get("symbol"))!=wanted:
            continue
        if row.get("feature")!="DEBT_EQUITY_RATIO":
            continue
        if row.get("domain")!="IND_AS_CORPORATE":
            continue
        if row.get("source_host")!="nsearchives.nseindia.com":
            continue
        if row.get("display_validated") is not True or row.get("point_in_time_safe") is not True:
            continue
        if basis and str(row.get("reporting_basis") or "").upper()!=str(basis).upper():
            continue
        available=_dt(row.get("availability_ts"))
        if available is None or available>cutoff:
            continue
        value=_num(row.get("value"))
        if value is None or value<0 or value>100:
            continue
        eligible.append(row)

    if not eligible:
        return [dict(x) for x in history],meta

    selected=max(
        eligible,
        key=lambda x:(str(x.get("quarter_end") or ""),str(x.get("availability_ts") or "")),
    )
    output=[dict(x) for x in history]
    target_index=None
    for index,row in enumerate(output):
        if (
            str(row.get("quarter_end") or row.get("current_quarter_end") or "")==str(selected.get("quarter_end") or "")
            and (not basis or str(row.get("reporting_basis") or "").upper()==str(basis).upper())
        ):
            target_index=index
    if target_index is None:
        meta.update({
            "status":"NO_MATCHING_CANONICAL_QUARTER",
            "selected_quarter_end":selected.get("quarter_end"),
            "selected_availability_ts":selected.get("availability_ts"),
        })
        return output,meta

    target=dict(output[target_index])
    existing=_usable_feature(target,"DEBT_EQUITY_RATIO")
    if existing is not None:
        meta.update({
            "status":"CANONICAL_ALREADY_AVAILABLE",
            "applied":False,
            "value":existing,
        })
        return output,meta

    value=float(selected["value"])
    target["DEBT_EQUITY_RATIO"]=value
    target["DEBT_EQUITY_RATIO__value"]=value
    target["DEBT_EQUITY_RATIO__status"]="SELECTED"
    target["DEBT_EQUITY_RATIO__concept"]="DebtEquityRatio"
    target["DEBT_EQUITY_RATIO__source"]="OFFICIAL_PIT_EVIDENCE_SUPPLEMENT"
    output[target_index]=target
    meta.update({
        "status":"APPLIED",
        "applied":True,
        "value":value,
        "quarter_end":selected.get("quarter_end"),
        "availability_ts":selected.get("availability_ts"),
        "concept":selected.get("concept"),
        "normalization":selected.get("normalization"),
        "xbrl_raw_value":selected.get("xbrl_raw_value"),
        "display_validated":True,
        "source_host":selected.get("source_host"),
    })
    return output,meta

'''
s=s.replace(anchor,"\n"+helper+anchor,1)

old='''    latest = history[-1]
    event_rows = _read_rows(sources["derived_events"])
'''
new='''    history, safety_supplement = _merge_pit_safety_supplement(root, symbol, cutoff, basis, history)
    latest = history[-1]
    event_rows = _read_rows(sources["derived_events"])
'''
if old not in s:
    raise RuntimeError("fundamental supplement merge point missing")
s=s.replace(old,new,1)

old='''        "balance_sheet": scored["balance_sheet"],
        "valuation": scored["valuation"],
'''
new='''        "balance_sheet": scored["balance_sheet"],
        "pit_safety_supplement": safety_supplement,
        "valuation": scored["valuation"],
'''
if old not in s:
    raise RuntimeError("fundamental output supplement point missing")
s=s.replace(old,new,1)

# Financial-sector evidence is now explicitly fail-closed until a value-based,
# PIT-safe bank/NBFC safety policy is validated. Presence alone can never unlock
# a financial-domain BUY.
old='''        "safety_ready": bool(financial_domain and not financial_missing),
        "status": "READY" if financial_domain and not financial_missing else "INSUFFICIENT_COVERAGE" if financial_domain else "NOT_APPLICABLE",
        "industrial_cashflow_or_leverage_used": False,
'''
new='''        "safety_ready": False,
        "status": "POLICY_NOT_VALIDATED" if financial_domain else "NOT_APPLICABLE",
        "observed_group_coverage_complete": bool(financial_domain and not financial_missing),
        "industrial_cashflow_or_leverage_used": False,
'''
if old not in s:
    raise RuntimeError("financial-domain fail-closed patch point missing")
s=s.replace(old,new,1)

fund.write_text(s,encoding="utf-8")

# Same-session caches from an older evidence pipeline must be rematerialized.
a=api.read_text(encoding="utf-8")
old='''            cached_session = str((cached.get("run") or {}).get("market_session") or "")
            if cached_session == session:
                return cached
            # A run-id cache from an older market session must never survive a
            # newly accepted official session.
            path.unlink(missing_ok=True)
'''
new='''            cached_run = cached.get("run") or {}
            cached_session = str(cached_run.get("market_session") or "")
            cached_version = str(cached_run.get("model_version") or "")
            if cached_session == session and cached_version == APP_VERSION:
                return cached
            # A cache from an older market session OR older evidence-pipeline
            # release must never survive into the current decision run.
            path.unlink(missing_ok=True)
'''
if old not in a:
    raise RuntimeError("version-aware live cache point missing")
a=a.replace(old,new,1)
api.write_text(a,encoding="utf-8")

policy=root/"phase5"/"pit_safety_evidence_policy_0149.json"
policy.write_text('''{
  "schema": "SRE_PIT_SAFETY_EVIDENCE_POLICY_0149",
  "release": "0.14.9-pit-safety-evidence-repair",
  "corporate_feature": "DEBT_EQUITY_RATIO",
  "corporate_source": "OFFICIAL_NSE_INTEGRATED_FILING_XBRL_AND_IXBRL",
  "display_validation_required": true,
  "point_in_time_required": true,
  "zero_fill_allowed": false,
  "financial_domain_policy": "FAIL_CLOSED_POLICY_NOT_VALIDATED",
  "financial_domain_metrics_promoted": false,
  "live_decision_router_changed": false,
  "thresholds_changed": false,
  "provider_policy_changed": false,
  "automatic_yfinance_fallback": false
}
''',encoding="utf-8")

assert 'APP_VERSION = "0.14.9-pit-safety-evidence-repair"' in api.read_text(encoding="utf-8")
assert "def _merge_pit_safety_supplement" in fund.read_text(encoding="utf-8")
assert '"status": "POLICY_NOT_VALIDATED" if financial_domain else "NOT_APPLICABLE"' in fund.read_text(encoding="utf-8")
assert "cached_version == APP_VERSION" in api.read_text(encoding="utf-8")
print("0.14.9 PIT safety evidence repair applied")
