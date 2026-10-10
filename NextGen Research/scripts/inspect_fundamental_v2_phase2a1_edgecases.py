from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "fundamental_v2_phase2a1_scaled"
EVENTS = OUT / "all_target_events.json"
VALIDATION = OUT / "scaled_pit_validation.json"
REPORT = OUT / "scaled_pit_edgecase_timelines.json"

def key(e):
    return (
        e.get("symbol"),
        e.get("quarter_end"),
        e.get("reporting_basis"),
        e.get("publication_ts") or "",
        e.get("event_id") or "",
    )

def main() -> int:
    events=json.loads(EVENTS.read_text(encoding="utf-8"))
    validation=json.loads(VALIDATION.read_text(encoding="utf-8"))
    failures=validation.get("failures") or []

    wanted=set()
    ids=set()
    for f in failures:
        if f.get("event_id"):
            ids.add(f["event_id"])
        if f.get("symbol") and f.get("quarter_end") and f.get("basis"):
            wanted.add((f["symbol"],f["quarter_end"],f["basis"]))

    # Pull full timelines for every failed semantic group.
    for e in events:
        if e.get("event_id") in ids:
            wanted.add((e.get("symbol"),e.get("quarter_end"),e.get("reporting_basis")))

    groups=[]
    for symbol,quarter,basis in sorted(wanted):
        xs=sorted([
            e for e in events
            if e.get("symbol")==symbol
            and e.get("quarter_end")==quarter
            and e.get("reporting_basis")==basis
        ], key=key)
        groups.append({
            "symbol":symbol,
            "quarter_end":quarter,
            "basis":basis,
            "events":[{
                "event_id":e.get("event_id"),
                "submission_type":e.get("submission_type"),
                "broadcast_ts":e.get("broadcast_ts"),
                "revised_ts":e.get("revised_ts"),
                "creation_ts":e.get("creation_ts"),
                "publication_ts":e.get("publication_ts"),
                "availability_ts":e.get("availability_ts"),
                "provider_seq_id":e.get("provider_seq_id"),
                "xbrl_url":e.get("xbrl_url"),
                "revision_remarks":e.get("revision_remarks"),
                "source_sha256":e.get("source_sha256"),
            } for e in xs],
        })

    # Also surface the creation-before-broadcast row directly.
    direct=[]
    for e in events:
        if e.get("event_id") in ids:
            direct.append({
                "symbol":e.get("symbol"),
                "quarter_end":e.get("quarter_end"),
                "basis":e.get("reporting_basis"),
                "event_id":e.get("event_id"),
                "submission_type":e.get("submission_type"),
                "broadcast_ts":e.get("broadcast_ts"),
                "revised_ts":e.get("revised_ts"),
                "creation_ts":e.get("creation_ts"),
                "publication_ts":e.get("publication_ts"),
                "availability_ts":e.get("availability_ts"),
                "provider_seq_id":e.get("provider_seq_id"),
                "xbrl_url":e.get("xbrl_url"),
                "revision_remarks":e.get("revision_remarks"),
            })

    report={
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A1_EDGECASE_TIMELINES_V1",
        "failure_count":len(failures),
        "failures":failures,
        "groups":groups,
        "direct_failed_events":direct,
        "authority":"SHADOW_ONLY",
    }
    REPORT.write_text(json.dumps(report,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(report,indent=2,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
