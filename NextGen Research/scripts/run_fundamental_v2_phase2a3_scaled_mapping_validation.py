from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.scaled_mapping_validation import (  # noqa: E402
    compact_document_resolution,
    latest_event_groups,
    summarize_resolutions,
)
from fundamental_research_v2_phase2a.xbrl_extraction import parse_xbrl_document  # noqa: E402

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
session=requests.Session()
session.headers.update({
    "User-Agent":UA,
    "Accept":"application/xml,text/xml,text/plain,*/*",
    "Accept-Language":"en-US,en;q=0.9",
})


def safe(value: str) -> str:
    return (
        value.replace("&","AND").replace("/","_").replace(":","_")
        .replace(" ","_").replace("|","_")
    )


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
        time.sleep(0.35)
        return body
    raise RuntimeError("XBRL_FETCH_RETRY_EXHAUSTED")


def main() -> int:
    if not EVENTS.exists():
        raise RuntimeError("PHASE2A1_SCALED_EVENTS_MISSING")
    if not CONTRACT.exists():
        raise RuntimeError("PHASE2A2_FROZEN_MAPPING_CONTRACT_MISSING")

    events=json.loads(EVENTS.read_text(encoding="utf-8"))
    contract=json.loads(CONTRACT.read_text(encoding="utf-8"))
    selected=latest_event_groups(events)

    url_gaps=[]
    retrieval_failures=[]
    resolutions=[]

    for idx,event in enumerate(selected,start=1):
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
                resolutions.append(cached)
                if idx % 25 == 0 or idx == len(selected):
                    print(f"[{idx}/{len(selected)}] checkpoint resume; parsed={len(resolutions)} failures={len(retrieval_failures)} url_gaps={len(url_gaps)}")
                continue

        url=event.get("xbrl_url")
        if not url:
            url_gaps.append({
                "symbol":event.get("symbol"),
                "quarter_end":event.get("quarter_end"),
                "reporting_basis":event.get("reporting_basis"),
                "event_id":event.get("event_id"),
                "code":"LATEST_EVENT_XBRL_URL_MISSING",
            })
            continue

        try:
            body=fetch_bytes(url)
            document=parse_xbrl_document(body,source_url=url,source_event=event)
            compact=compact_document_resolution(document,contract)
            path.write_text(json.dumps(compact,indent=2,sort_keys=True),encoding="utf-8")
            resolutions.append(compact)
        except Exception as exc:
            retrieval_failures.append({
                "symbol":event.get("symbol"),
                "quarter_end":event.get("quarter_end"),
                "reporting_basis":event.get("reporting_basis"),
                "event_id":event.get("event_id"),
                "xbrl_url":url,
                "error":f"{type(exc).__name__}: {exc}",
            })

        if idx % 25 == 0 or idx == len(selected):
            print(f"[{idx}/{len(selected)}] parsed={len(resolutions)} failures={len(retrieval_failures)} url_gaps={len(url_gaps)}")

        checkpoint={
            "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A3_CHECKPOINT_V1",
            "authority":"SHADOW_ONLY",
            "expected_document_count":len(selected),
            "processed_index":idx,
            "parsed_document_count":len(resolutions),
            "retrieval_failure_count":len(retrieval_failures),
            "latest_event_xbrl_url_gap_count":len(url_gaps),
            "production_model_changed":False,
            "model_training_started":False,
        }
        (OUT/"checkpoint.json").write_text(
            json.dumps(checkpoint,indent=2,sort_keys=True),encoding="utf-8"
        )

    summary=summarize_resolutions(
        resolutions,
        expected_document_count=len(selected),
        retrieval_failures=retrieval_failures,
        url_gaps=url_gaps,
    )
    (OUT/"summary.json").write_text(
        json.dumps(summary,indent=2,sort_keys=True),encoding="utf-8"
    )
    (OUT/"retrieval_failures.json").write_text(
        json.dumps(retrieval_failures,indent=2,sort_keys=True),encoding="utf-8"
    )
    (OUT/"xbrl_url_gaps.json").write_text(
        json.dumps(url_gaps,indent=2,sort_keys=True),encoding="utf-8"
    )
    (OUT/"feature_coverage.json").write_text(
        json.dumps(summary["feature_coverage"],indent=2,sort_keys=True),encoding="utf-8"
    )

    print(json.dumps(summary,indent=2,sort_keys=True))

    if summary["status"]=="INCOMPLETE_RETRIEVAL":
        return 4
    if summary["status"]=="FAIL_SCALED_MAPPING_AMBIGUITY":
        return 5
    return 0


if __name__=="__main__":
    raise SystemExit(main())
