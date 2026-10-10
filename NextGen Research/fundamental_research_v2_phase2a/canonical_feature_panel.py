"""Canonical basis-separated feature panel for Fundamental Research V2 Phase 2A.4."""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from typing import Iterable

from .scaled_mapping_validation import latest_event_groups

TARGET_QUARTERS=(
    "2025-03-31",
    "2025-06-30",
    "2025-09-30",
    "2025-12-31",
    "2026-03-31",
    "2026-06-30",
)

FEATURES=(
    "REVENUE",
    "PAT",
    "PBT",
    "TAX",
    "FINANCE_COST",
    "DEPRECIATION",
    "OPERATING_CASH_FLOW",
    "CASH_AND_EQUIVALENTS",
    "TOTAL_ASSETS",
    "DEBT_EQUITY_RATIO",
    "EPS",
)


def numeric_or_none(value):
    if value in (None, ""):
        return None
    try:
        return format(Decimal(str(value)), "f")
    except InvalidOperation:
        return None


def compact_by_event_id(documents: Iterable[dict]) -> dict[str, dict]:
    result={}
    for doc in documents:
        event_id=doc.get("source_event_id")
        if not event_id:
            raise ValueError("COMPACT_DOCUMENT_EVENT_ID_MISSING")
        if event_id in result:
            raise ValueError(f"DUPLICATE_COMPACT_EVENT_ID:{event_id}")
        result[event_id]=doc
    return result


def build_panel_rows(events: Iterable[dict], documents: Iterable[dict], terminal_event_ids: set[str]) -> list[dict]:
    expected=latest_event_groups(events)
    docs=compact_by_event_id(documents)
    rows=[]

    for event in expected:
        event_id=event.get("event_id")
        doc=docs.get(event_id)
        terminal=event_id in terminal_event_ids

        if doc is None and not terminal:
            raise ValueError(f"UNEXPLAINED_COMPACT_DOCUMENT_MISSING:{event_id}")
        if doc is not None and terminal:
            raise ValueError(f"TERMINAL_GAP_HAS_COMPACT_DOCUMENT:{event_id}")
        if doc is not None and doc.get("hard_failures"):
            raise ValueError(f"SEMANTIC_HARD_FAILURE_IN_PANEL_INPUT:{event_id}")

        row={
            "symbol":event.get("symbol"),
            "quarter_end":event.get("quarter_end"),
            "reporting_basis":event.get("reporting_basis"),
            "submission_type":event.get("submission_type"),
            "event_id":event_id,
            "availability_ts":event.get("availability_ts"),
            "provider_seq_id":event.get("provider_seq_id"),
            "archive_gap":terminal,
            "domain":doc.get("domain") if doc else None,
            "source_document_kind":doc.get("source_document_kind") if doc else None,
            "retrieval_representation":doc.get("retrieval_representation") if doc else None,
            "source_content_sha256":doc.get("source_content_sha256") if doc else None,
        }

        features=(doc or {}).get("features") or {}
        for feature in FEATURES:
            info=features.get(feature)
            if terminal:
                status="SOURCE_DOCUMENT_UNAVAILABLE"
                concept=None
                value=None
            elif info is None:
                status="NOT_MAPPED_FOR_DOMAIN"
                concept=None
                value=None
            else:
                status=info.get("status")
                concept=info.get("selected_concept")
                selected=info.get("selected") or {}
                value=numeric_or_none(selected.get("normalized_value"))

            row[f"{feature}__status"]=status
            row[f"{feature}__concept"]=concept
            row[f"{feature}__value"]=value

        rows.append(row)

    rows.sort(key=lambda x:(str(x["symbol"]),str(x["reporting_basis"]),str(x["quarter_end"])))
    return rows


def continuity_audit(rows: Iterable[dict]) -> dict:
    items=list(rows)
    by_history=defaultdict(list)
    for row in items:
        by_history[(row["symbol"],row["reporting_basis"])].append(row)

    feature_summary=[]
    history_summary=[]
    quarter_feature=defaultdict(lambda: {"present":0,"missing":0,"archive_gap":0})
    basis_feature=defaultdict(lambda: {"present":0,"missing":0,"archive_gap":0})

    for (symbol,basis),history in sorted(by_history.items()):
        ordered=sorted(history,key=lambda x:x["quarter_end"])
        qmap={x["quarter_end"]:x for x in ordered}
        feature_presence={}
        for feature in FEATURES:
            present_quarters=[]
            missing_quarters=[]
            archive_quarters=[]
            for quarter in TARGET_QUARTERS:
                row=qmap.get(quarter)
                if row is None:
                    missing_quarters.append(quarter)
                    continue
                status=row.get(f"{feature}__status")
                value=row.get(f"{feature}__value")
                if row.get("archive_gap"):
                    archive_quarters.append(quarter)
                    quarter_feature[(quarter,feature)]["archive_gap"]+=1
                    basis_feature[(basis,feature)]["archive_gap"]+=1
                elif status in {"SELECTED","SELECTED_EQUIVALENT_DUPLICATES"} and value is not None:
                    present_quarters.append(quarter)
                    quarter_feature[(quarter,feature)]["present"]+=1
                    basis_feature[(basis,feature)]["present"]+=1
                else:
                    missing_quarters.append(quarter)
                    quarter_feature[(quarter,feature)]["missing"]+=1
                    basis_feature[(basis,feature)]["missing"]+=1
            feature_presence[feature]={
                "present_quarters":present_quarters,
                "missing_quarters":missing_quarters,
                "archive_gap_quarters":archive_quarters,
                "present_count":len(present_quarters),
            }
        history_summary.append({
            "symbol":symbol,
            "reporting_basis":basis,
            "observed_row_count":len(ordered),
            "quarters_present":[x["quarter_end"] for x in ordered],
            "feature_presence":feature_presence,
        })

    for (quarter,feature),counts in sorted(quarter_feature.items()):
        total=sum(counts.values())
        feature_summary.append({
            "scope":"QUARTER",
            "quarter_end":quarter,
            "reporting_basis":None,
            "feature":feature,
            **counts,
            "present_rate_excluding_archive_gap":(
                counts["present"]/(counts["present"]+counts["missing"])
                if counts["present"]+counts["missing"] else None
            ),
            "row_count":total,
        })

    for (basis,feature),counts in sorted(basis_feature.items()):
        total=sum(counts.values())
        feature_summary.append({
            "scope":"BASIS",
            "quarter_end":None,
            "reporting_basis":basis,
            "feature":feature,
            **counts,
            "present_rate_excluding_archive_gap":(
                counts["present"]/(counts["present"]+counts["missing"])
                if counts["present"]+counts["missing"] else None
            ),
            "row_count":total,
        })

    archive_count=sum(1 for x in items if x.get("archive_gap"))
    status_counts=Counter()
    for row in items:
        for feature in FEATURES:
            status_counts[row.get(f"{feature}__status")]+=1

    return {
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A4_CONTINUITY_AUDIT_V1",
        "authority":"SHADOW_ONLY",
        "row_count":len(items),
        "history_count":len(by_history),
        "archive_gap_row_count":archive_count,
        "feature_status_counts":dict(status_counts),
        "feature_summary":feature_summary,
        "history_summary":history_summary,
        "production_model_changed":False,
        "model_training_started":False,
    }
