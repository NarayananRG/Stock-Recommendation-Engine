from __future__ import annotations

import json
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
SCALED=ROOT/"results"/"fundamental_v2_phase2a3_scaled_mapping_validation"/"summary.json"
DIAG=ROOT/"results"/"fundamental_v2_phase2a3_ixbrl_diagnostic"/"diagnostic.json"
OUT=ROOT/"results"/"fundamental_v2_phase2a3_scaled_mapping_validation"/"phase2a3_closure_v1.json"

TERMINAL_ZERO_PATTERNS={
    "contextref_attribute",
    "escaped_xbrli_context",
    "ix_header",
    "ix_nonfraction",
    "ix_resources",
    "literal_context_any_prefix",
    "literal_xbrli_context",
}


def require(value, code):
    if not value:
        raise RuntimeError(code)


def main() -> int:
    require(SCALED.exists(),"PHASE2A3_SCALED_SUMMARY_MISSING")
    require(DIAG.exists(),"PHASE2A3_IXBRL_DIAGNOSTIC_MISSING")

    scaled=json.loads(SCALED.read_text(encoding="utf-8"))
    diag=json.loads(DIAG.read_text(encoding="utf-8"))

    expected=int(scaled.get("expected_document_count") or 0)
    parsed=int(scaled.get("parsed_document_count") or 0)
    retrieval_failures=int(scaled.get("retrieval_failure_count") or 0)
    semantic_failures=int(scaled.get("semantic_hard_failure_count") or 0)
    url_gaps=int(scaled.get("latest_event_xbrl_url_gap_count") or 0)

    require(expected==2181,"UNEXPECTED_SCALED_DOCUMENT_COUNT")
    require(parsed==2171,"UNEXPECTED_PARSED_DOCUMENT_COUNT")
    require(retrieval_failures==10,"UNEXPECTED_RETRIEVAL_FAILURE_COUNT")
    require(semantic_failures==0,"SEMANTIC_FAILURE_PRESENT")
    require(url_gaps==0,"LATEST_EVENT_METADATA_URL_GAP_PRESENT")

    results=diag.get("results") or []
    require(diag.get("target_count")==10,"DIAGNOSTIC_TARGET_COUNT_MISMATCH")
    require(diag.get("result_count")==10,"DIAGNOSTIC_RESULT_COUNT_MISMATCH")
    require(len(results)==10,"DIAGNOSTIC_RESULTS_MISMATCH")

    terminal=[]
    for row in results:
        counts=row.get("pattern_counts") or {}
        require(row.get("http_status")==200,"IXBRL_DIAGNOSTIC_HTTP_NOT_200")
        require(str(row.get("content_type") or "").lower().startswith("text/html"),
                "IXBRL_DIAGNOSTIC_NOT_HTML")
        require(all(int(counts.get(name) or 0)==0 for name in TERMINAL_ZERO_PATTERNS),
                "IXBRL_DIAGNOSTIC_XBRL_STRUCTURE_PRESENT")
        terminal.append({
            "symbol":row.get("symbol"),
            "quarter_end":row.get("quarter_end"),
            "reporting_basis":row.get("reporting_basis"),
            "event_id":row.get("event_id"),
            "ixbrl_url":row.get("ixbrl_url"),
            "content_type":row.get("content_type"),
            "content_length_bytes":row.get("content_length_bytes"),
            "classification":"OFFICIAL_HTML_WITHOUT_XBRL_CONTEXT_OR_FACT_STRUCTURE",
        })

    coverage=parsed/expected if expected else 0.0
    affected_symbols=sorted({x.get("symbol") for x in terminal if x.get("symbol")})

    closure={
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A3_CLOSURE_V1",
        "authority":"SHADOW_ONLY",
        "status":"PASS_WITH_QUANTIFIED_OFFICIAL_ARCHIVE_GAPS",
        "phase2a3_closed":True,
        "expected_document_count":expected,
        "parsed_document_count":parsed,
        "parsed_document_coverage":coverage,
        "terminal_official_archive_gap_count":len(terminal),
        "affected_symbol_count":len(affected_symbols),
        "affected_symbols":affected_symbols,
        "semantic_hard_failure_count":semantic_failures,
        "latest_event_metadata_xbrl_url_gap_count":url_gaps,
        "terminal_gap_classification":"LATEST_EVENT_PRIMARY_XBRL_404_AND_SAME_EVENT_IXBRL_URL_RETURNS_HTML_WITHOUT_INLINE_XBRL_STRUCTURE",
        "terminal_gaps":terminal,
        "mapping_validation_conclusion":[
            "Frozen period/domain mapping contract scaled successfully across every parsed document.",
            "No semantic hard failures were observed across 2,171 parsed latest-event filing groups.",
            "The 10 remaining gaps are official archive representation gaps, not mapping failures.",
            "No older filing version was substituted for the missing latest filing representation.",
            "The 10 gaps remain explicitly missing and must not be zero-filled or silently sourced from non-official providers."
        ],
        "feature_coverage":scaled.get("feature_coverage") or [],
        "production_model_changed":False,
        "model_training_started":False,
        "next_gate":"PHASE2A4_CANONICAL_FEATURE_PANEL_AND_CROSS_QUARTER_CONTINUITY_AUDIT",
    }

    OUT.write_text(json.dumps(closure,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps({
        "artifact_type":closure["artifact_type"],
        "status":closure["status"],
        "phase2a3_closed":closure["phase2a3_closed"],
        "parsed_document_count":closure["parsed_document_count"],
        "expected_document_count":closure["expected_document_count"],
        "parsed_document_coverage":closure["parsed_document_coverage"],
        "terminal_official_archive_gap_count":closure["terminal_official_archive_gap_count"],
        "affected_symbols":closure["affected_symbols"],
        "semantic_hard_failure_count":closure["semantic_hard_failure_count"],
        "next_gate":closure["next_gate"],
        "output":str(OUT),
    },indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
