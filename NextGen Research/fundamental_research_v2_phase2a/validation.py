"""Fail-closed validation for Phase 2A.1 official PIT filing events."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterable, Sequence

from .core import TARGET_QUARTER_ENDS, effective_availability_ts, normalize_symbol


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def validate_pit_events(
    events: Iterable[dict],
    *,
    required_symbols: Sequence[str],
    require_all_target_quarters: bool = True,
) -> dict:
    rows = [dict(x) for x in events]
    symbols = sorted({normalize_symbol(x) for x in required_symbols})
    failures: list[dict] = []
    warnings: list[dict] = []

    ids = [x.get("event_id") for x in rows]
    if any(not x for x in ids):
        failures.append({"code": "EVENT_ID_MISSING"})
    if len([x for x in ids if x]) != len(set(x for x in ids if x)):
        failures.append({"code": "DUPLICATE_EVENT_ID"})

    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    by_symbol_quarter: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for i, row in enumerate(rows):
        try:
            symbol = normalize_symbol(row["symbol"])
            quarter = row["quarter_end"]
            basis = row["reporting_basis"]
            submission = row["submission_type"]
            publication = _dt(row["publication_ts"])
            qdate = datetime.fromisoformat(quarter)
        except Exception as exc:
            failures.append({"code": "MALFORMED_EVENT", "row_index": i, "detail": str(exc)})
            continue

        if publication.date() < qdate.date():
            failures.append({"code": "PUBLICATION_PRECEDES_QUARTER_END", "event_id": row.get("event_id")})

        if submission == "ORIGINAL":
            if not row.get("broadcast_ts"):
                failures.append({"code": "ORIGINAL_BROADCAST_MISSING", "event_id": row.get("event_id")})
            elif _dt(row["broadcast_ts"]) != publication:
                failures.append({"code": "ORIGINAL_PUBLICATION_NOT_BROADCAST", "event_id": row.get("event_id")})
            if row.get("creation_ts") and row.get("broadcast_ts"):
                if _dt(row["creation_ts"]) < _dt(row["broadcast_ts"]):
                    warnings.append({
                        "code": "ORIGINAL_TIMESTAMP_ORDER_DISAGREEMENT",
                        "event_id": row.get("event_id"),
                        "broadcast_ts": row.get("broadcast_ts"),
                        "creation_ts": row.get("creation_ts"),
                        "availability_ts": effective_availability_ts(row),
                    })
        elif submission == "REVISION":
            if not row.get("revised_ts"):
                failures.append({"code": "REVISION_TIMESTAMP_MISSING", "event_id": row.get("event_id")})
            elif _dt(row["revised_ts"]) != publication:
                failures.append({"code": "REVISION_PUBLICATION_NOT_REVISED_TS", "event_id": row.get("event_id")})
            # Current NSE Integrated Filing rows use mutually exclusive
            # exchange-received fields: Original -> broadcast_Date,
            # Revision -> revised_Date. A revision row should therefore not
            # require or compare broadcast_ts. creation_ts, when present, is
            # the later dissemination/creation timestamp.
            if row.get("creation_ts") and row.get("revised_ts"):
                if _dt(row["creation_ts"]) < _dt(row["revised_ts"]):
                    warnings.append({
                        "code": "REVISION_TIMESTAMP_ORDER_DISAGREEMENT",
                        "event_id": row.get("event_id"),
                        "revised_ts": row.get("revised_ts"),
                        "creation_ts": row.get("creation_ts"),
                        "availability_ts": effective_availability_ts(row),
                    })
        else:
            failures.append({"code": "UNSUPPORTED_SUBMISSION_TYPE", "event_id": row.get("event_id")})

        grouped[(symbol, quarter, basis)].append(row)
        by_symbol_quarter[(symbol, quarter)].append(row)

    target = set(TARGET_QUARTER_ENDS)
    for symbol in symbols:
        present = {q for (s, q), xs in by_symbol_quarter.items() if s == symbol and xs}
        missing = sorted(target - present)
        if require_all_target_quarters and missing:
            failures.append({"code": "TARGET_QUARTER_MISSING", "symbol": symbol, "quarters": missing})

        for quarter in sorted(present & target):
            xs = by_symbol_quarter[(symbol, quarter)]
            if not any(x.get("submission_type") == "ORIGINAL" for x in xs):
                failures.append({"code": "ORIGINAL_EVENT_MISSING", "symbol": symbol, "quarter_end": quarter})

    revision_count = 0
    for (symbol, quarter, basis), xs in grouped.items():
        originals = sorted(
            (x for x in xs if x.get("submission_type") == "ORIGINAL"),
            key=lambda x: _dt(effective_availability_ts(x)),
        )
        revisions = sorted(
            (x for x in xs if x.get("submission_type") == "REVISION"),
            key=lambda x: _dt(effective_availability_ts(x)),
        )
        revision_count += len(revisions)
        if revisions and not originals:
            failures.append({
                "code": "REVISION_WITHOUT_ORIGINAL",
                "symbol": symbol,
                "quarter_end": quarter,
                "basis": basis,
            })
            continue
        if originals and revisions:
            first_original = _dt(effective_availability_ts(originals[0]))
            for revision in revisions:
                if _dt(effective_availability_ts(revision)) <= first_original:
                    failures.append({
                        "code": "REVISION_AVAILABLE_NOT_AFTER_ORIGINAL",
                        "symbol": symbol,
                        "quarter_end": quarter,
                        "basis": basis,
                        "event_id": revision.get("event_id"),
                    })

    # Earliest original publication for successive target quarters should move forward
    # within the same symbol/basis. Revisions are excluded because a late correction can
    # legitimately occur after a later quarter was originally filed.
    for symbol in symbols:
        bases = sorted({b for (s, q, b) in grouped if s == symbol and q in target})
        for basis in bases:
            sequence = []
            for quarter in TARGET_QUARTER_ENDS:
                originals = [
                    x for x in grouped.get((symbol, quarter, basis), [])
                    if x.get("submission_type") == "ORIGINAL"
                ]
                if originals:
                    earliest = min(originals, key=lambda x: _dt(effective_availability_ts(x)))
                    sequence.append((quarter, _dt(effective_availability_ts(earliest))))
            for prev, cur in zip(sequence, sequence[1:]):
                if cur[1] <= prev[1]:
                    warnings.append({
                        "code": "LATE_OR_OUT_OF_ORDER_ORIGINAL_FILING",
                        "symbol": symbol,
                        "basis": basis,
                        "prior_quarter": prev[0],
                        "current_quarter": cur[0],
                        "prior_publication_ts": prev[1].isoformat(),
                        "current_publication_ts": cur[1].isoformat(),
                        "interpretation": (
                            "Not a PIT failure. NSE may receive an older reporting "
                            "period after a newer one. Availability remains governed "
                            "strictly by each event's own availability_ts."
                        ),
                    })

    by_symbol = {}
    for symbol in symbols:
        xs = [x for x in rows if normalize_symbol(x.get("symbol", "")) == symbol]
        by_symbol[symbol] = {
            "event_count": len(xs),
            "quarters": sorted({x.get("quarter_end") for x in xs if x.get("quarter_end") in target}),
            "original_count": sum(x.get("submission_type") == "ORIGINAL" for x in xs),
            "revision_count": sum(x.get("submission_type") == "REVISION" for x in xs),
            "bases": sorted({x.get("reporting_basis") for x in xs if x.get("reporting_basis")}),
        }

    return {
        "artifact_type": "FUNDAMENTAL_RESEARCH_V2_PHASE2A1_PIT_VALIDATION_V1",
        "status": "PASS" if not failures else "FAIL",
        "event_count": len(rows),
        "required_symbol_count": len(symbols),
        "revision_event_count": revision_count,
        "by_symbol": by_symbol,
        "failure_count": len(failures),
        "failures": failures,
        "warning_count": len(warnings),
        "warnings": warnings,
        "authority": "SHADOW_ONLY",
        "production_model_changed": False,
        "model_training_started": False,
    }
