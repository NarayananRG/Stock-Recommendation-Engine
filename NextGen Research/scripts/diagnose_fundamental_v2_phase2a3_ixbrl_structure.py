from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
FAILURES=ROOT/"results"/"fundamental_v2_phase2a3_scaled_mapping_validation"/"retrieval_failures.json"
OUT=ROOT/"results"/"fundamental_v2_phase2a3_ixbrl_diagnostic"
OUT.mkdir(parents=True,exist_ok=True)

UA=(
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0 Safari/537.36"
)
session=requests.Session()
session.headers.update({
    "User-Agent":UA,
    "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language":"en-US,en;q=0.9",
})

PATTERNS={
    "literal_xbrli_context": r"<\s*xbrli:context\b",
    "literal_context_any_prefix": r"<\s*[A-Za-z0-9_.-]+:context\b",
    "escaped_xbrli_context": r"&lt;\s*xbrli:context\b",
    "ix_header": r"<\s*ix:header\b",
    "ix_resources": r"<\s*ix:resources\b",
    "ix_nonfraction": r"<\s*ix:nonfraction\b",
    "contextref_attribute": r"\bcontextref\s*=",
    "iframe": r"<\s*iframe\b",
    "script": r"<\s*script\b",
    "object": r"<\s*object\b",
    "embed": r"<\s*embed\b",
    "data_uri": r"data:(?:text|application)/",
}

SNIPPET_TERMS=[
    "xbrli:context",
    "&lt;xbrli:context",
    "ix:header",
    "ix:resources",
    "ix:nonfraction",
    "contextref",
    "<iframe",
    "<object",
    "<embed",
]


def official(url: str) -> bool:
    parsed=urlparse(url)
    return parsed.scheme=="https" and (parsed.hostname or "").lower()=="nsearchives.nseindia.com"


def snippet(text: str, term: str, radius: int=450) -> str | None:
    pos=text.lower().find(term.lower())
    if pos<0:
        return None
    start=max(0,pos-radius)
    end=min(len(text),pos+len(term)+radius)
    return text[start:end].replace("\r"," ").replace("\n"," ")


def main() -> int:
    if not FAILURES.exists():
        raise RuntimeError("PHASE2A3_RETRIEVAL_FAILURES_MISSING")

    failures=json.loads(FAILURES.read_text(encoding="utf-8"))
    targets=[]
    for row in failures:
        url=row.get("ixbrl_url")
        if not url or not official(url):
            continue
        targets.append(row)

    results=[]
    for idx,row in enumerate(targets,start=1):
        url=row["ixbrl_url"]
        response=session.get(url,timeout=90)
        response.raise_for_status()
        body=response.content
        encoding=response.encoding or "utf-8"
        text=body.decode(encoding,errors="replace")

        counts={
            name:len(re.findall(pattern,text,flags=re.IGNORECASE))
            for name,pattern in PATTERNS.items()
        }
        xmlns_prefixes=sorted(set(
            m.group(1).lower()
            for m in re.finditer(
                r"xmlns:([A-Za-z0-9_.-]+)\s*=",text,flags=re.IGNORECASE
            )
        ))
        snippets={
            term:snippet(text,term)
            for term in SNIPPET_TERMS
            if snippet(text,term) is not None
        }
        result={
            "symbol":row.get("symbol"),
            "quarter_end":row.get("quarter_end"),
            "reporting_basis":row.get("reporting_basis"),
            "event_id":row.get("event_id"),
            "ixbrl_url":url,
            "http_status":response.status_code,
            "content_type":response.headers.get("Content-Type"),
            "content_length_bytes":len(body),
            "encoding_used":encoding,
            "first_500_chars":text[:500],
            "pattern_counts":counts,
            "xmlns_prefixes":xmlns_prefixes,
            "snippets":snippets,
        }
        results.append(result)
        print(json.dumps({
            "index":idx,
            "symbol":result["symbol"],
            "quarter_end":result["quarter_end"],
            "basis":result["reporting_basis"],
            "bytes":result["content_length_bytes"],
            "content_type":result["content_type"],
            "pattern_counts":counts,
            "xmlns_prefixes":xmlns_prefixes[:30],
            "snippet_keys":list(snippets),
        },indent=2,sort_keys=True))

    summary={
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A3_IXBRL_STRUCTURE_DIAGNOSTIC_V1",
        "authority":"SHADOW_ONLY",
        "target_count":len(targets),
        "result_count":len(results),
        "results":results,
        "production_model_changed":False,
        "model_training_started":False,
    }
    (OUT/"diagnostic.json").write_text(
        json.dumps(summary,indent=2,sort_keys=True),encoding="utf-8"
    )
    print(json.dumps({
        "artifact_type":summary["artifact_type"],
        "target_count":summary["target_count"],
        "result_count":summary["result_count"],
        "output":str(OUT/"diagnostic.json"),
    },indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
