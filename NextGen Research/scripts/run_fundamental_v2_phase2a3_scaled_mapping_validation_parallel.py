from __future__ import annotations

import json
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.scaled_mapping_validation import (
    compact_document_resolution,
    latest_event_groups,
    summarize_resolutions,
)
from fundamental_research_v2_phase2a.xbrl_extraction import parse_ixbrl_document, parse_xbrl_document

EVENTS=ROOT/"results"/"fundamental_v2_phase2a1_scaled"/"all_target_events.json"
CONTRACT=ROOT/"fundamental_research_v2_phase2a"/"phase2a2_canonical_mapping_freeze_v1.json"
OUT=ROOT/"results"/"fundamental_v2_phase2a3_scaled_mapping_validation"
BY_DOC=OUT/"by_document"
OUT.mkdir(parents=True,exist_ok=True)
BY_DOC.mkdir(parents=True,exist_ok=True)

UA=(
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0 Safari/537.36"
)
MAX_WORKERS=6
_tls=threading.local()


def session() -> requests.Session:
    s=getattr(_tls,"session",None)
    if s is None:
        s=requests.Session()
        s.headers.update({
            "User-Agent":UA,
            "Accept":"application/xml,text/xml,text/plain,*/*",
            "Accept-Language":"en-US,en;q=0.9",
            "Connection":"keep-alive",
        })
        _tls.session=s
    return s


def safe(value: str) -> str:
    return (
        value.replace("&","AND").replace("/","_").replace(":","_")
        .replace(" ","_").replace("|","_")
    )


def fetch_bytes(url: str) -> bytes:
    host=(urlparse(url).hostname or "").lower()
    if host!="nsearchives.nseindia.com":
        raise RuntimeError(f"NON_OFFICIAL_XBRL_HOST:{host}")
    last=None
    for attempt in range(6):
        try:
            response=session().get(url,timeout=45)
            if response.status_code in {429,500,502,503,504}:
                if attempt < 5:
                    time.sleep(0.6*(attempt+1))
                    continue
            response.raise_for_status()
            body=response.content
            if not body or b"<" not in body[:2000]:
                raise RuntimeError("XBRL_BODY_NOT_XML_LIKE")
            return body
        except Exception as exc:
            last=exc
            if attempt < 5:
                time.sleep(0.6*(attempt+1))
                continue
    raise last or RuntimeError("XBRL_FETCH_RETRY_EXHAUSTED")


def process(event: dict, contract: dict):
    key="__".join([
        str(event.get("symbol")),
        str(event.get("quarter_end")),
        str(event.get("reporting_basis")),
        str(event.get("event_id"))[:12],
    ])
    path=BY_DOC/f"{safe(key)}.json"
    if path.exists():
        cached=json.loads(path.read_text(encoding="utf-8"))
        if cached.get("source_event_id")==event.get("event_id"):
            cached.setdefault("retrieval_representation","XBRL_PRIMARY_CACHED")
            cached.setdefault("source_document_kind","XBRL")
            return ("ok",cached)

    url=event.get("xbrl_url")
    if not url:
        return ("gap",{
            "symbol":event.get("symbol"),
            "quarter_end":event.get("quarter_end"),
            "reporting_basis":event.get("reporting_basis"),
            "event_id":event.get("event_id"),
            "code":"LATEST_EVENT_XBRL_URL_MISSING",
        })

    try:
        recovered=False
        primary_error=None
        try:
            body=fetch_bytes(url)
            document=parse_xbrl_document(body,source_url=url,source_event=event)
        except requests.HTTPError as primary_exc:
            status=getattr(primary_exc.response,"status_code",None)
            ixurl=event.get("ixbrl_url")
            if status!=404 or not ixurl:
                raise
            primary_error=f"{type(primary_exc).__name__}: {primary_exc}"
            ixbody=fetch_bytes(ixurl)
            document=parse_ixbrl_document(ixbody,source_url=ixurl,source_event=event)
            document["domain_source_url"]=url
            recovered=True

        compact=compact_document_resolution(document,contract)
        compact["retrieval_representation"]="IXBRL_SAME_EVENT_404_RECOVERY" if recovered else "XBRL_PRIMARY"
        compact["primary_xbrl_url"]=url
        compact["same_event_ixbrl_url"]=event.get("ixbrl_url")
        compact["primary_retrieval_error"]=primary_error
        path.write_text(json.dumps(compact,indent=2,sort_keys=True),encoding="utf-8")
        return ("ok",compact)
    except Exception as exc:
        return ("failure",{
            "symbol":event.get("symbol"),
            "quarter_end":event.get("quarter_end"),
            "reporting_basis":event.get("reporting_basis"),
            "event_id":event.get("event_id"),
            "xbrl_url":url,
            "ixbrl_url":event.get("ixbrl_url"),
            "error":f"{type(exc).__name__}: {exc}",
        })


def main() -> int:
    if not EVENTS.exists():
        raise RuntimeError("PHASE2A1_SCALED_EVENTS_MISSING")
    if not CONTRACT.exists():
        raise RuntimeError("PHASE2A2_FROZEN_MAPPING_CONTRACT_MISSING")

    events=json.loads(EVENTS.read_text(encoding="utf-8"))
    contract=json.loads(CONTRACT.read_text(encoding="utf-8"))
    selected=latest_event_groups(events)
    print(f"FAST PARALLEL MAP START: {len(selected)} documents, workers={MAX_WORKERS}",flush=True)

    resolutions=[]
    retrieval_failures=[]
    url_gaps=[]
    completed=0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures={pool.submit(process,event,contract):event for event in selected}
        for future in as_completed(futures):
            kind,payload=future.result()
            completed+=1
            if kind=="ok":
                resolutions.append(payload)
            elif kind=="gap":
                url_gaps.append(payload)
            else:
                retrieval_failures.append(payload)

            if completed % 50 == 0 or completed == len(selected):
                print(
                    f"[{completed}/{len(selected)}] parsed={len(resolutions)} "
                    f"failures={len(retrieval_failures)} gaps={len(url_gaps)}",
                    flush=True,
                )
                checkpoint={
                    "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A3_CHECKPOINT_V1",
                    "authority":"SHADOW_ONLY",
                    "expected_document_count":len(selected),
                    "processed_index":completed,
                    "parsed_document_count":len(resolutions),
                    "retrieval_failure_count":len(retrieval_failures),
                    "latest_event_xbrl_url_gap_count":len(url_gaps),
                    "parallel_workers":MAX_WORKERS,
                    "production_model_changed":False,
                    "model_training_started":False,
                }
                (OUT/"checkpoint.json").write_text(json.dumps(checkpoint,indent=2,sort_keys=True),encoding="utf-8")

    # Stable ordering keeps downstream hashes/reviews deterministic.
    resolutions.sort(key=lambda x:(str(x.get("symbol")),str(x.get("quarter_end")),str(x.get("reporting_basis")),str(x.get("source_event_id"))))
    retrieval_failures.sort(key=lambda x:(str(x.get("symbol")),str(x.get("quarter_end")),str(x.get("reporting_basis"))))
    url_gaps.sort(key=lambda x:(str(x.get("symbol")),str(x.get("quarter_end")),str(x.get("reporting_basis"))))

    summary=summarize_resolutions(
        resolutions,
        expected_document_count=len(selected),
        retrieval_failures=retrieval_failures,
        url_gaps=url_gaps,
    )
    (OUT/"summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True),encoding="utf-8")
    (OUT/"retrieval_failures.json").write_text(json.dumps(retrieval_failures,indent=2,sort_keys=True),encoding="utf-8")
    (OUT/"xbrl_url_gaps.json").write_text(json.dumps(url_gaps,indent=2,sort_keys=True),encoding="utf-8")
    (OUT/"feature_coverage.json").write_text(json.dumps(summary["feature_coverage"],indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(summary,indent=2,sort_keys=True),flush=True)

    if summary["status"]=="INCOMPLETE_RETRIEVAL":
        return 4
    if summary["status"]=="FAIL_SCALED_MAPPING_AMBIGUITY":
        return 5
    return 0


if __name__=="__main__":
    raise SystemExit(main())
