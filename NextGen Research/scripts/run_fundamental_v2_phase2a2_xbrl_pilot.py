from __future__ import annotations

import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

import requests

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "NextGen Research"
sys.path.insert(0, str(ROOT))

from fundamental_research_v2_phase2a.xbrl_extraction import (  # noqa: E402
    latest_events_by_group,
    parse_xbrl_document,
)

EVENTS = ROOT / "results" / "fundamental_v2_phase2a1_scaled" / "all_target_events.json"
OUT = ROOT / "results" / "fundamental_v2_phase2a2_pilot"
DOCS = OUT / "documents"
OUT.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(parents=True, exist_ok=True)

PILOT_SYMBOLS={"HCLTECH","HDFCBANK","360ONE","IRCTC","M&M","RELIANCE"}
PILOT_QUARTERS={"2026-03-31","2026-06-30"}

UA=(
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0 Safari/537.36"
)
session=requests.Session()
session.headers.update({
    "User-Agent":UA,
    "Accept":"application/xml,text/xml,text/plain,*/*",
    "Accept-Language":"en-US,en;q=0.9",
})


def fetch_bytes(url: str) -> bytes:
    host=(urlparse(url).hostname or "").lower()
    if host!="nsearchives.nseindia.com":
        raise RuntimeError(f"NON_OFFICIAL_XBRL_HOST:{host}")
    for attempt in range(4):
        response=session.get(url,timeout=60)
        if response.status_code in {429,500,502,503,504} and attempt<3:
            time.sleep(2+attempt)
            continue
        response.raise_for_status()
        body=response.content
        if not body or b"<" not in body[:2000]:
            raise RuntimeError("XBRL_BODY_NOT_XML_LIKE")
        time.sleep(0.4)
        return body
    raise RuntimeError("XBRL_FETCH_RETRY_EXHAUSTED")


def safe(value: str) -> str:
    return (
        value.replace("&","AND")
        .replace("/","_")
        .replace(":","_")
        .replace(" ","_")
    )


def main() -> int:
    if not EVENTS.exists():
        raise RuntimeError("PHASE2A1_SCALED_EVENTS_MISSING")

    events=json.loads(EVENTS.read_text(encoding="utf-8"))
    selected=latest_events_by_group(
        events,
        symbols=PILOT_SYMBOLS,
        quarters=PILOT_QUARTERS,
    )

    results=[]
    failures=[]
    concept_docs=defaultdict(set)
    concept_facts=Counter()
    by_domain=defaultdict(lambda:{"documents":0,"numeric_facts":0,"concepts":set()})

    for idx,event in enumerate(selected,start=1):
        url=event.get("xbrl_url")
        key=f"{event['symbol']}__{event['quarter_end']}__{event['reporting_basis']}"
        try:
            body=fetch_bytes(url)
            parsed=parse_xbrl_document(body,source_url=url,source_event=event)
            results.append(parsed)
            out=DOCS/f"{safe(key)}.json"
            out.write_text(json.dumps(parsed,indent=2,sort_keys=True),encoding="utf-8")

            seen=set()
            for fact in parsed["numeric_facts"]:
                concept=f"{fact.get('concept_namespace')}|{fact['concept_local_name']}"
                concept_facts[concept]+=1
                seen.add(concept)
            for concept in seen:
                concept_docs[concept].add(key)

            family="UNKNOWN"
            xurl=(url or "").upper()
            if "NBFC" in xurl:
                family="NBFC"
            elif "BANK" in xurl:
                family="BANK"
            elif "INDAS" in xurl:
                family="IND_AS_CORPORATE"
            by_domain[family]["documents"]+=1
            by_domain[family]["numeric_facts"]+=parsed["numeric_fact_count"]
            by_domain[family]["concepts"].update(seen)

            print(
                f"[{idx:02d}/{len(selected):02d}] {key}: "
                f"{parsed['numeric_fact_count']} numeric facts, "
                f"{parsed['context_count']} contexts"
            )
        except Exception as exc:
            failures.append({
                "symbol":event.get("symbol"),
                "quarter_end":event.get("quarter_end"),
                "reporting_basis":event.get("reporting_basis"),
                "event_id":event.get("event_id"),
                "xbrl_url":url,
                "error":f"{type(exc).__name__}: {exc}",
            })
            print(f"[{idx:02d}/{len(selected):02d}] {key}: FAIL {type(exc).__name__}: {exc}")

    concept_profile=[]
    for concept,docs in concept_docs.items():
        namespace,local=concept.split("|",1)
        concept_profile.append({
            "concept_namespace":None if namespace=="None" else namespace,
            "concept_local_name":local,
            "document_count":len(docs),
            "fact_count":concept_facts[concept],
            "document_coverage":len(docs)/len(results) if results else 0.0,
        })
    concept_profile.sort(key=lambda x:(-x["document_count"],-x["fact_count"],x["concept_local_name"]))

    domains={}
    for domain,data in by_domain.items():
        domains[domain]={
            "documents":data["documents"],
            "numeric_facts":data["numeric_facts"],
            "unique_concept_count":len(data["concepts"]),
        }

    summary={
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A2_XBRL_PILOT_V1",
        "authority":"SHADOW_ONLY",
        "pilot_symbols":sorted(PILOT_SYMBOLS),
        "pilot_quarters":sorted(PILOT_QUARTERS),
        "selected_document_count":len(selected),
        "successful_document_count":len(results),
        "failed_document_count":len(failures),
        "failures":failures,
        "total_numeric_fact_count":sum(x["numeric_fact_count"] for x in results),
        "unique_concept_count":len(concept_profile),
        "domain_profile":domains,
        "top_concepts":concept_profile[:100],
        "status":"PILOT_XBRL_PARSE_AND_BREADTH_PROFILE_PASS" if results and not failures else "PILOT_INCOMPLETE",
        "production_model_changed":False,
        "model_training_started":False,
    }
    (OUT/"concept_profile.json").write_text(
        json.dumps(concept_profile,indent=2,sort_keys=True),encoding="utf-8"
    )
    (OUT/"pilot_summary.json").write_text(
        json.dumps(summary,indent=2,sort_keys=True),encoding="utf-8"
    )
    print(json.dumps(summary,indent=2,sort_keys=True))
    return 0 if summary["status"]=="PILOT_XBRL_PARSE_AND_BREADTH_PROFILE_PASS" else 4


if __name__=="__main__":
    raise SystemExit(main())
