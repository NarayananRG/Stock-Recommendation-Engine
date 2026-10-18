from __future__ import annotations
import html
from datetime import date, datetime
import json
import math
import os
import re
import sys
import time
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.scaled_mapping_validation import latest_event_groups
from fundamental_research_v2_phase2a.xbrl_extraction import parse_xbrl_document, parse_ixbrl_document
from fundamental_research_v2_phase2a.canonical_mapping_audit import classify_domain
from fundamental_research_v2_phase2a.core import effective_availability_ts

DIAG=Path(os.environ["SRE_PHASE5_DIAGNOSTICS_ROOT"])
EVENTS=DIAG/"fundamental_v2_phase2a1_scaled"/"all_target_events.json"
OUT=Path(os.environ.get("SRE_SAFETY_SUPPLEMENT_OUT",str(Path.cwd()/"work"/"pit-safety-supplement")))
OUT.mkdir(parents=True,exist_ok=True)

UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/155 Safari/537.36"
_tls=threading.local()
OFFICIAL_HOST="nsearchives.nseindia.com"

def session():
    s=getattr(_tls,"s",None)
    if s is None:
        s=requests.Session()
        s.headers.update({
            "User-Agent":UA,
            "Accept":"application/xml,text/xml,text/html,application/xhtml+xml,*/*",
            "Accept-Language":"en-US,en;q=0.9",
            "Referer":"https://www.nseindia.com/",
        })
        _tls.s=s
    return s

def official(url):
    return (urlparse(str(url or "")).hostname or "").lower()==OFFICIAL_HOST

def fetch(url):
    if not official(url):
        raise RuntimeError("NON_OFFICIAL_SOURCE:"+str(url))
    last=None
    for attempt in range(7):
        try:
            r=session().get(url,timeout=50)
            if r.status_code in {403,429,500,502,503,504} and attempt<6:
                time.sleep(1.0*(attempt+1))
                continue
            r.raise_for_status()
            return r.content
        except Exception as exc:
            last=exc
            time.sleep(.8*(attempt+1))
    raise last or RuntimeError("FETCH_FAILED")

def selected_latest_symbol_events(events):
    groups=latest_event_groups(events)
    by=defaultdict(list)
    for e in groups:
        by[str(e.get("symbol"))].append(e)
    result=[]
    for symbol,items in sorted(by.items()):
        with_url=[e for e in items if e.get("xbrl_url") and official(e.get("xbrl_url")) and e.get("quarter_end") and e.get("reporting_basis") in {"CONSOLIDATED","STANDALONE"}]
        if not with_url:
            continue
        with_url.sort(key=lambda e:(str(e.get("quarter_end") or ""), e.get("reporting_basis")=="CONSOLIDATED"),reverse=True)
        # Choose the latest quarter first; consolidated is preferred only within that quarter.
        chosen=with_url[0]
        result.append(chosen)
    return result

def numeric(value):
    try:
        v=float(str(value).replace(",","").strip())
        return v if math.isfinite(v) else None
    except Exception:
        return None

def eligible_debt_facts(document,event):
    quarter=str(event.get("quarter_end") or "")
    contexts={x.get("context_id"):x for x in document.get("contexts",[])}
    rows=[]
    for fact in document.get("numeric_facts",[]):
        if fact.get("concept_local_name")!="DebtEquityRatio":
            continue
        ctx=contexts.get(fact.get("context_ref")) or {}
        if ctx.get("dimensions"):
            continue
        aligned=(ctx.get("instant")==quarter or ctx.get("end_date")==quarter)
        if not aligned:
            continue
        raw=numeric(fact.get("raw_value"))
        if raw is None:
            continue
        rows.append({
            "raw_value":raw,
            "scale":fact.get("scale"),
            "decimals":fact.get("decimals"),
            "context_ref":fact.get("context_ref"),
            "instant":ctx.get("instant"),
            "start_date":ctx.get("start_date"),
            "end_date":ctx.get("end_date"),
            "dimension_count":0,
        })
    return rows

def human_debt_ratio(ixbrl_bytes):
    text=ixbrl_bytes.decode("utf-8",errors="replace")
    patterns=[
        r"Debt\s*equity\s*ratio\s*</th>\s*<td[^>]*>\s*([^<]*)</td>",
        r"Debt[-\s]*Equity\s*Ratio\s*</th>\s*<td[^>]*>\s*([^<]*)</td>",
    ]
    values=[]
    for pattern in patterns:
        for match in re.finditer(pattern,text,flags=re.I|re.S):
            cell=html.unescape(re.sub(r"<[^>]+>","",match.group(1))).strip()
            value=numeric(cell)
            if value is not None:
                values.append(value)
    return values

def reconcile(raw, displayed):
    candidates=[
        ("RAW",raw),
        ("RAW_X100",raw*100.0),
        ("RAW_DIV100",raw/100.0),
    ]
    best=None
    for name,value in candidates:
        err=abs(value-displayed)
        scale=max(1.0,abs(displayed))
        rel=err/scale
        item=(rel,err,name,value)
        if best is None or item<best:
            best=item
    if best is None or best[0]>1e-6:
        return None
    return {"normalization":best[2],"normalized_value":best[3],"absolute_error":best[1]}

def valid_corporate_debt_equity(value):
    if isinstance(value,bool):
        return False
    try:
        value=float(value)
    except (TypeError,ValueError):
        return False
    return math.isfinite(value) and 0.0<=value<=100.0

def pit_availability_is_valid(availability, quarter_end):
    """Official filing cannot be PIT-safe without dated, offset-aware availability."""
    try:
        period = date.fromisoformat(str(quarter_end))
        if isinstance(availability, datetime):
            moment = availability
        else:
            moment = datetime.fromisoformat(str(availability).replace("Z", "+00:00"))
        return moment.tzinfo is not None and moment.utcoffset() is not None and moment.date() >= period
    except (ValueError, TypeError, OverflowError):
        return False


def process(event):
    xurl=event.get("xbrl_url")
    ixurl=event.get("ixbrl_url")
    if not xurl or not official(xurl):
        return {"symbol":event.get("symbol"),"status":"SKIP_NO_OFFICIAL_XBRL"}
    try:
        body=fetch(xurl)
        doc=parse_xbrl_document(body,source_url=xurl,source_event=event)
    except requests.HTTPError as exc:
        if getattr(exc.response,"status_code",None)==404 and ixurl and official(ixurl):
            body=fetch(ixurl)
            doc=parse_ixbrl_document(body,source_url=ixurl,source_event=event)
            doc["domain_source_url"]=xurl
        else:
            raise

    domain=classify_domain(doc.get("domain_source_url") or doc.get("source_url"))
    # Financial-domain safety remains governed separately; never use corporate
    # leverage rules for BANK/NBFC.
    if domain!="IND_AS_CORPORATE":
        return {"symbol":event.get("symbol"),"domain":domain,"status":"SKIP_FINANCIAL_DOMAIN"}

    facts=eligible_debt_facts(doc,event)
    if not facts:
        return {"symbol":event.get("symbol"),"domain":domain,"status":"NO_ALIGNED_DEBT_EQUITY_RATIO"}

    raw_values=sorted({round(float(x["raw_value"]),12) for x in facts})
    if len(raw_values)!=1:
        return {"symbol":event.get("symbol"),"domain":domain,"status":"AMBIGUOUS_XBRL_VALUES","raw_values":raw_values}

    if not ixurl or not official(ixurl):
        return {"symbol":event.get("symbol"),"domain":domain,"status":"NO_OFFICIAL_IXBRL_DISPLAY"}

    ixbody=fetch(ixurl)
    displayed=human_debt_ratio(ixbody)
    if not displayed:
        return {"symbol":event.get("symbol"),"domain":domain,"status":"NO_HUMAN_DISPLAY_VALUE","raw":raw_values[0]}

    # Prefer the first non-empty current-value cell. If multiple numeric cells
    # exist they usually repeat current/prior display values; accept only when
    # at least one deterministically reconciles with the XBRL fact.
    matches=[]
    for value in displayed:
        rec=reconcile(raw_values[0],value)
        if rec:
            matches.append((value,rec))
    if not matches:
        return {"symbol":event.get("symbol"),"domain":domain,"status":"DISPLAY_XBRL_MISMATCH",
                "raw":raw_values[0],"displayed":displayed[:6]}

    # Deterministic preference: exact RAW, then X100, then DIV100; numeric tie.
    order={"RAW":0,"RAW_X100":1,"RAW_DIV100":2}
    matches.sort(key=lambda x:(order[x[1]["normalization"]],x[1]["absolute_error"],x[0]))
    display_value,rec=matches[0]
    if not valid_corporate_debt_equity(display_value):
        return {
            "symbol":event.get("symbol"),"domain":domain,
            "status":"OUT_OF_POLICY_DISPLAY_VALUE",
            "raw":raw_values[0],"displayed":display_value,
            "normalization":rec["normalization"],
        }
    availability=effective_availability_ts(event)
    if not pit_availability_is_valid(availability, event.get("quarter_end")):
        return {"symbol":event.get("symbol"),"domain":domain,
                "status":"UNVERIFIABLE_PIT_PUBLICATION_TIMESTAMP"}
    return {
        "schema":"SRE_PIT_SAFETY_SUPPLEMENT_ROW_V1",
        "symbol":event.get("symbol"),
        "quarter_end":event.get("quarter_end"),
        "reporting_basis":event.get("reporting_basis"),
        "availability_ts":availability,
        "domain":domain,
        "feature":"DEBT_EQUITY_RATIO",
        "value":round(float(display_value),8),
        "concept":"DebtEquityRatio",
        "xbrl_raw_value":raw_values[0],
        "normalization":rec["normalization"],
        "display_validated":True,
        "xbrl_url":xurl,
        "ixbrl_url":ixurl,
        "source_host":OFFICIAL_HOST,
        "authority":"OFFICIAL_PIT_EVIDENCE_SUPPLEMENT",
        "point_in_time_safe":True,
        "status":"VALIDATED",
    }

events=json.loads(EVENTS.read_text(encoding="utf-8"))
selected=selected_latest_symbol_events(events)
rows=[]; diagnostics=[]
with ThreadPoolExecutor(max_workers=6) as pool:
    futures={pool.submit(process,e):e for e in selected}
    done=0
    for future in as_completed(futures):
        done+=1
        event=futures[future]
        try:
            item=future.result()
        except Exception as exc:
            item={"symbol":event.get("symbol"),"status":"FETCH_OR_PARSE_ERROR","error":type(exc).__name__+": "+str(exc)}
        if item.get("status")=="VALIDATED":
            rows.append(item)
        else:
            diagnostics.append(item)
        if done%25==0 or done==len(selected):
            print(f"[{done}/{len(selected)}] validated={len(rows)} diagnostics={len(diagnostics)}",flush=True)

rows.sort(key=lambda x:(str(x["symbol"]),str(x["quarter_end"]),str(x["reporting_basis"])))
diagnostics.sort(key=lambda x:(str(x.get("status")),str(x.get("symbol"))))

# Hard safety assertions.
assert rows, "NO_VALIDATED_DEBT_EQUITY_ROWS"
assert all(x["source_host"]==OFFICIAL_HOST for x in rows)
assert all(x["domain"]=="IND_AS_CORPORATE" for x in rows)
assert all(x["display_validated"] is True for x in rows)
assert all(x["concept"]=="DebtEquityRatio" for x in rows)
assert len({x["symbol"] for x in rows})==len(rows), "DUPLICATE_SYMBOL_SUPPLEMENT"

with (OUT/"pit_safety_supplement.jsonl").open("w",encoding="utf-8") as h:
    for row in rows:
        h.write(json.dumps(row,sort_keys=True)+"\n")

summary={
    "schema":"SRE_PIT_SAFETY_SUPPLEMENT_V1",
    "source":"OFFICIAL_NSE_INTEGRATED_FILING_XBRL_AND_IXBRL",
    "authority":"OFFICIAL_PIT_EVIDENCE_SUPPLEMENT",
    "documents_considered":len(selected),
    "validated_corporate_debt_equity_rows":len(rows),
    "normalization_counts":dict(Counter(x["normalization"] for x in rows)),
    "diagnostic_status_counts":dict(Counter(x.get("status") for x in diagnostics)),
    "validated_symbols":[x["symbol"] for x in rows],
    "near_miss_presence":{s:(s in {x["symbol"] for x in rows}) for s in ("BDL","BSE","GODREJCP","HINDZINC","OFSS")},
    "financial_domain_policy":"FAIL_CLOSED_UNCHANGED",
    "financial_domain_metrics_promoted":False,
    "production_router_changed":False,
    "thresholds_changed":False,
    "provider_policy_changed":False,
    "automatic_yfinance_fallback":False,
    "diagnostics":diagnostics,
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=str),encoding="utf-8")
print(json.dumps({k:v for k,v in summary.items() if k!="diagnostics"},indent=2),flush=True)
