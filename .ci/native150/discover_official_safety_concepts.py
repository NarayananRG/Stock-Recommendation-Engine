from __future__ import annotations
import json, os, re, sys, time, threading
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

DIAG=Path(os.environ["SRE_PHASE5_DIAGNOSTICS_ROOT"])
EVENTS=DIAG/"fundamental_v2_phase2a1_scaled"/"all_target_events.json"
OUT=Path(os.environ.get("SRE_SAFETY_DISCOVERY_OUT",str(Path.cwd()/"work"/"pit-safety-discovery")))
OUT.mkdir(parents=True,exist_ok=True)

UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/155 Safari/537.36"
_tls=threading.local()

PATTERNS={
 "DEBT_LEVERAGE": re.compile(r"(debt|borrow|loan|lease.*liabil|financialliabil|networth|equity)",re.I),
 "ASSET_QUALITY": re.compile(r"(gross.*non.?perform|net.*non.?perform|gnpa|nnpa|nonperform)",re.I),
 "CAPITAL_ADEQUACY": re.compile(r"(capital.*adequ|crar|tier.?1|tier.?2|capitalratio)",re.I),
 "FUNDING_LIQUIDITY": re.compile(r"(loan.*deposit|credit.*deposit|deposit.*ratio|advances|deposits)",re.I),
 "CREDIT_COST_PROVISION": re.compile(r"(credit.*cost|provision.*coverage|provision|impairment.*loan|expected.*credit)",re.I),
 "NIM_SPREAD": re.compile(r"(net.*interest.*margin|nim|interest.*spread)",re.I),
 "ROA": re.compile(r"(return.*assets|roa)",re.I),
 "ROE": re.compile(r"(return.*equity|roe)",re.I),
}

def session():
    s=getattr(_tls,"s",None)
    if s is None:
        s=requests.Session()
        s.headers.update({"User-Agent":UA,"Accept":"application/xml,text/xml,text/plain,*/*","Accept-Language":"en-US,en;q=0.9"})
        _tls.s=s
    return s

def fetch(url:str)->bytes:
    host=(urlparse(url).hostname or "").lower()
    if host!="nsearchives.nseindia.com":
        raise RuntimeError("NON_OFFICIAL_HOST:"+host)
    last=None
    for attempt in range(5):
        try:
            r=session().get(url,timeout=45)
            if r.status_code in {429,500,502,503,504}:
                time.sleep(.8*(attempt+1)); continue
            r.raise_for_status()
            return r.content
        except Exception as exc:
            last=exc
            time.sleep(.8*(attempt+1))
    raise last or RuntimeError("FETCH_FAILED")

def choose_latest_one_per_symbol(events):
    groups=latest_event_groups(events)
    by=defaultdict(list)
    for e in groups:
        by[str(e.get("symbol"))].append(e)
    chosen=[]
    for symbol,items in sorted(by.items()):
        items=sorted(items,key=lambda e:(str(e.get("quarter_end") or ""), e.get("reporting_basis")=="CONSOLIDATED"), reverse=True)
        preferred=next((e for e in items if e.get("reporting_basis")=="CONSOLIDATED" and e.get("xbrl_url")),None)
        chosen.append(preferred or next((e for e in items if e.get("xbrl_url")),items[0]))
    return chosen

def context_map(document):
    return {x.get("context_id"):x for x in document.get("contexts",[])}

def process(event):
    url=event.get("xbrl_url")
    if not url:
        return {"symbol":event.get("symbol"),"error":"NO_XBRL_URL"}
    try:
        body=fetch(url)
        doc=parse_xbrl_document(body,source_url=url,source_event=event)
    except requests.HTTPError as exc:
        if getattr(exc.response,"status_code",None)==404 and event.get("ixbrl_url"):
            body=fetch(event["ixbrl_url"])
            doc=parse_ixbrl_document(body,source_url=event["ixbrl_url"],source_event=event)
            doc["domain_source_url"]=url
        else:
            raise
    domain=classify_domain(doc.get("domain_source_url") or doc.get("source_url"))
    contexts=context_map(doc)
    hits={k:[] for k in PATTERNS}
    all_concepts=set()
    seen=set()
    for fact in doc.get("numeric_facts",[]):
        concept=str(fact.get("concept_local_name") or "")
        if not concept:
            continue
        all_concepts.add(concept)
        ctx=contexts.get(fact.get("context_ref")) or {}
        dims=ctx.get("dimensions") or []
        signature=(concept,fact.get("context_ref"),fact.get("raw_value"))
        if signature in seen:
            continue
        seen.add(signature)
        for group,rx in PATTERNS.items():
            if rx.search(concept):
                hits[group].append({
                  "concept":concept,
                  "value":fact.get("raw_value"),
                  "context_ref":fact.get("context_ref"),
                  "instant":ctx.get("instant"),
                  "start_date":ctx.get("start_date"),
                  "end_date":ctx.get("end_date"),
                  "dimension_count":len(dims),
                  "unit_ref":fact.get("unit_ref"),
                })
    return {
      "symbol":event.get("symbol"),"quarter_end":event.get("quarter_end"),
      "reporting_basis":event.get("reporting_basis"),"domain":domain,
      "source_url":url,"hits":hits,"all_concepts":sorted(all_concepts),"numeric_fact_count":len(doc.get("numeric_facts",[])),
    }

events=json.loads(EVENTS.read_text(encoding="utf-8"))
selected=choose_latest_one_per_symbol(events)
print("DISCOVERY_DOCS",len(selected),flush=True)
rows=[]; failures=[]
with ThreadPoolExecutor(max_workers=8) as pool:
    fut={pool.submit(process,e):e for e in selected}
    done=0
    for f in as_completed(fut):
        done+=1
        try:
            row=f.result()
            if row.get("error"):
                failures.append(row)
            else:
                rows.append(row)
        except Exception as exc:
            e=fut[f]
            failures.append({"symbol":e.get("symbol"),"error":type(exc).__name__+": "+str(exc)})
        if done%25==0 or done==len(selected):
            print(f"[{done}/{len(selected)}] ok={len(rows)} fail={len(failures)}",flush=True)

concepts=defaultdict(Counter)
domain_all_concepts=defaultdict(Counter)
domain_concepts=defaultdict(lambda:defaultdict(Counter))
symbol_group_presence=defaultdict(Counter)
examples=defaultdict(lambda:defaultdict(list))
for row in rows:
    domain=row["domain"]
    for concept in row.get("all_concepts") or []:
        domain_all_concepts[domain][concept]+=1
    for group,hits in row["hits"].items():
        unique={h["concept"] for h in hits}
        symbol_group_presence[domain][group]+=int(bool(unique))
        for concept in unique:
            concepts[group][concept]+=1
            domain_concepts[domain][group][concept]+=1
        for h in hits[:8]:
            if len(examples[group][h["concept"]])<6:
                examples[group][h["concept"]].append({
                  "symbol":row["symbol"],"domain":domain,"quarter_end":row["quarter_end"],
                  "basis":row["reporting_basis"],**h
                })

report={
 "schema":"SRE_PIT_SAFETY_CONCEPT_DISCOVERY_V1",
 "source":"OFFICIAL_NSE_INTEGRATED_FILING_XBRL",
 "documents_requested":len(selected),
 "documents_parsed":len(rows),
 "failures":failures,
 "domain_counts":dict(Counter(r["domain"] for r in rows)),
 "group_document_presence":{d:dict(v) for d,v in symbol_group_presence.items()},
 "concept_frequency":{g:dict(c.most_common()) for g,c in concepts.items()},
 "domain_concept_frequency":{d:{g:dict(c.most_common()) for g,c in groups.items()} for d,groups in domain_concepts.items()},
 "domain_all_concept_frequency":{d:dict(c.most_common()) for d,c in domain_all_concepts.items()},
 "symbol_safety_hits":[{"symbol":row["symbol"],"domain":row["domain"],"quarter_end":row["quarter_end"],"basis":row["reporting_basis"],"hits":row["hits"]} for row in rows],
 "examples":{g:dict(v) for g,v in examples.items()},
 "production_logic_changed":False,
 "thresholds_changed":False,
 "provider_policy_changed":False,
}
(OUT/"concept_discovery.json").write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")

md=["# PIT Safety Concept Discovery","",
f"- Documents: {len(rows)}/{len(selected)}",
f"- Domains: {report['domain_counts']}",
"- Source: OFFICIAL NSE Integrated Filing XBRL",
"- Production changes: NONE",""]
for domain,groups in report["group_document_presence"].items():
    md.append("## "+domain)
    for group,count in groups.items():
        md.append(f"- {group}: present in {count} documents")
md.append("")
for domain,counter in domain_all_concepts.items():
    md.append("## "+domain+" common numeric concepts")
    for concept,count in counter.most_common(120):
        md.append(f"- {concept}: {count}")
    md.append("")
for group,counter in concepts.items():
    md.append("## "+group+" top concepts")
    for concept,count in counter.most_common(15):
        md.append(f"- {concept}: {count}")
    md.append("")
(OUT/"concept_discovery.md").write_text("\n".join(md)+"\n",encoding="utf-8")
print(json.dumps({
 "documents_parsed":len(rows),
 "domain_counts":report["domain_counts"],
 "group_document_presence":report["group_document_presence"],
 "top_concepts":{g:list(c.most_common(12)) for g,c in concepts.items()},
 "bank_common_concepts":list(domain_all_concepts.get("BANK",Counter()).most_common(100)),
 "nbfc_common_concepts":list(domain_all_concepts.get("NBFC",Counter()).most_common(100)),
 "failures":len(failures)
},indent=2),flush=True)
