from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "NextGen Research"
sys.path.insert(0, str(ROOT))

from fundamental_research_v2_phase2a import (  # noqa: E402
    AUTHORITY,
    SOURCE_PRIORITY,
    TARGET_QUARTER_ENDS,
    build_filing_event,
    coverage_audit,
    dedupe_events,
    first_decision_after_publication,
    growth_continuity,
    normalize_basis,
    normalize_symbol,
    phase2a_readiness,
    publication_age_bucket,
    require_official_fundamental_url,
    select_latest_available_filing,
)

RESULTS = []


def require(value, message="assertion failed"):
    if not value:
        raise AssertionError(message)


def raises(error, fn, contains=None):
    try:
        fn()
    except error as exc:
        if contains:
            require(contains in str(exc), str(exc))
        return
    raise AssertionError(f"expected {error.__name__}")


def case(category, name, fn):
    try:
        fn(); status, detail = "PASS", ""
    except Exception as exc:
        status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
    RESULTS.append({"category": category, "test": name, "status": status, "detail": detail})


NSE_URL = "https://www.nseindia.com/companies-listing/corporate-integrated-filing"
BSE_URL = "https://www.bseindia.com/corporates/Comp_Results.aspx"
SHA = "a" * 64


def original(symbol="ABC", quarter="2025-06-30", basis="Consolidated", broadcast="18-Jul-2025 16:01:12", family="IND-AS"):
    return build_filing_event({
        "Symbol": symbol,
        "Company Name": f"{symbol} Limited",
        "Quarter End Date": quarter,
        "Type of Submission": "Original",
        "Audited / Unaudited": "Un-Audited",
        "CONSOLIDATED / Standalone": basis,
        "BROADCAST DATE/TIME": broadcast,
        "Revised DATE/TIME": "-",
        "Revision Remarks": "-",
        "IND AS/ NON IND AS": family,
    }, source_url=NSE_URL, source_sha256=SHA, source_exchange="NSE")


def revision(symbol="ABC", quarter="2025-06-30", basis="Consolidated", revised="20-Jul-2025 12:30:00", family="IND-AS"):
    return build_filing_event({
        "Symbol": symbol,
        "Company Name": f"{symbol} Limited",
        "Quarter End Date": quarter,
        "Type of Submission": "Revision",
        "Audited / Unaudited": "Un-Audited",
        "CONSOLIDATED / Standalone": basis,
        "BROADCAST DATE/TIME": "18-Jul-2025 16:01:12",
        "Revised DATE/TIME": revised,
        "Revision Remarks": "XBRL correction",
        "IND AS/ NON IND AS": family,
    }, source_url=NSE_URL, source_sha256="b" * 64, source_exchange="NSE")


# Governance and sources
case("GOVERNANCE", "shadow only", lambda: require(AUTHORITY == "SHADOW_ONLY"))
case("GOVERNANCE", "NSE primary BSE secondary", lambda: require(SOURCE_PRIORITY == ("NSE", "BSE")))
case("GOVERNANCE", "six target quarters", lambda: require(len(TARGET_QUARTER_ENDS) == 6))
case("SOURCE", "NSE accepted", lambda: require(require_official_fundamental_url(NSE_URL) == NSE_URL))
case("SOURCE", "BSE accepted", lambda: require(require_official_fundamental_url(BSE_URL) == BSE_URL))
case("SOURCE", "third party rejected", lambda: raises(ValueError, lambda: require_official_fundamental_url("https://finance.yahoo.com/x"), "OFFICIAL_NSE_OR_BSE_SOURCE_REQUIRED"))

# Identity and basis
case("IDENTITY", "MANDM alias canonicalized", lambda: require(normalize_symbol("MANDM") == "M&M"))
case("IDENTITY", "M&M stable", lambda: require(normalize_symbol("M&M") == "M&M"))
case("IDENTITY", "empty symbol rejected", lambda: raises(ValueError, lambda: normalize_symbol(""), "SYMBOL_REQUIRED"))
case("BASIS", "consolidated normalized", lambda: require(normalize_basis("Consolidated") == "CONSOLIDATED"))
case("BASIS", "non-consolidated normalized", lambda: require(normalize_basis("Non-Consolidated") == "STANDALONE"))
case("BASIS", "unknown basis rejected", lambda: raises(ValueError, lambda: normalize_basis("mixed"), "REPORTING_BASIS_REQUIRED"))

# PIT event semantics
O = original()
R = revision()
case("EVENT", "original publication is broadcast", lambda: require(O["publication_ts"].startswith("2025-07-18T16:01:12")))
case("EVENT", "revision publication is revised timestamp", lambda: require(R["publication_ts"].startswith("2025-07-20T12:30:00")))
case("EVENT", "event ids differ for revision", lambda: require(O["event_id"] != R["event_id"]))
case("EVENT", "publication before quarter rejected", lambda: raises(ValueError, lambda: original(broadcast="18-May-2025 16:01:12"), "PUBLICATION_PRECEDES_QUARTER_END"))
case("EVENT", "revision needs revision timestamp", lambda: raises(ValueError, lambda: build_filing_event({
    "Symbol":"ABC", "Quarter End Date":"2025-06-30", "Type of Submission":"Revision",
    "CONSOLIDATED / Standalone":"Standalone", "BROADCAST DATE/TIME":"18-Jul-2025 16:00:00",
    "Revised DATE/TIME":"-"
}, source_url=NSE_URL, source_sha256=SHA), "REVISION_TIMESTAMP_REQUIRED"))

# Dedupe and selection
case("DEDUPE", "exact duplicate collapses", lambda: require(len(dedupe_events([O, O])) == 1))
case("PIT", "before original none", lambda: require(select_latest_available_filing([O, R], symbol="ABC", decision_ts="2025-07-18T15:00:00+05:30") is None))
case("PIT", "after original before revision gets original", lambda: require(select_latest_available_filing([O, R], symbol="ABC", decision_ts="2025-07-19T12:00:00+05:30")["submission_type"] == "ORIGINAL"))
case("PIT", "after revision gets revision", lambda: require(select_latest_available_filing([O, R], symbol="ABC", decision_ts="2025-07-21T12:00:00+05:30")["submission_type"] == "REVISION"))
case("PIT", "first decision strictly after publication", lambda: require(first_decision_after_publication(O, ["2025-07-18T15:30:00+05:30", "2025-07-18T16:30:00+05:30", "2025-07-21T16:00:00+05:30"]).startswith("2025-07-18T16:30:00")))

# Continuity
P = original(quarter="2025-03-31", broadcast="25-Apr-2025 10:00:00")
C = original(quarter="2025-06-30", broadcast="18-Jul-2025 16:01:12")
case("CONTINUITY", "same basis/family allowed", lambda: require(growth_continuity(P, C)["allowed"]))
case("CONTINUITY", "basis switch blocked", lambda: require("REPORTING_BASIS_SWITCH" in growth_continuity(P, original(quarter="2025-06-30", basis="Standalone"))["reasons"]))
case("CONTINUITY", "accounting family switch blocked", lambda: require("ACCOUNTING_FAMILY_SWITCH" in growth_continuity(P, original(quarter="2025-06-30", family="NON-IND-AS"))["reasons"]))
case("CONTINUITY", "reverse period blocked", lambda: require("NON_FORWARD_PERIOD" in growth_continuity(C, P)["reasons"]))

# Event-decay buckets
for value, expected in [(0,"EVENT_DECISION_0"),(1,"DECISIONS_1_5"),(5,"DECISIONS_1_5"),(6,"DECISIONS_6_20"),(20,"DECISIONS_6_20"),(21,"DECISIONS_21_63"),(63,"DECISIONS_21_63"),(64,"DECISIONS_64_PLUS")]:
    case("DECAY", f"bucket {value}", lambda v=value,e=expected: require(publication_age_bucket(v) == e))
case("DECAY", "negative blocked", lambda: raises(ValueError, lambda: publication_age_bucket(-1), "NEGATIVE_EVENT_AGE"))

# Coverage/readiness
all_events = []
for i, quarter in enumerate(TARGET_QUARTER_ENDS):
    month = {"03":"04","06":"07","09":"10","12":"01"}[quarter[5:7]]
    year = int(quarter[:4]) + (1 if quarter[5:7] == "12" else 0)
    day = "25"
    all_events.append(original(symbol="ABC", quarter=quarter, broadcast=f"{day}-{['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][int(month)-1]}-{year} 10:00:00"))
COV = coverage_audit(all_events, target_symbols=["ABC"])
READY = phase2a_readiness(coverage=COV, timestamp_integrity=True, continuity_audited=True, parser_breadth_audited=True, source_manifest_complete=True)
case("COVERAGE", "all target quarters present", lambda: require(COV["all_target_quarters_present"]))
case("READINESS", "ready only after all data gates", lambda: require(READY["status"] == "READY_FOR_EVENT_DECAY_RESEARCH"))
case("READINESS", "training remains false", lambda: require(READY["model_training_started"] is False))
case("READINESS", "promotion remains false", lambda: require(READY["promotion_allowed"] is False))
case("READINESS", "missing coverage gate fails", lambda: require(phase2a_readiness(coverage={"all_target_quarters_present":False}, timestamp_integrity=True, continuity_audited=True, parser_breadth_audited=True, source_manifest_complete=True)["status"] == "NOT_READY"))

# Contract lock
contract = json.loads((ROOT / "fundamental_research_v2_phase2a" / "phase2a_contract.json").read_text(encoding="utf-8"))
case("CONTRACT", "phase name locked", lambda: require(contract["phase"] == "FUNDAMENTAL_RESEARCH_V2_PHASE2A_OFFICIAL_PIT_RECOVERY_AND_EVENT_DECAY_FOUNDATION"))
case("CONTRACT", "training prohibited", lambda: require(contract["model_training_allowed"] is False))
case("CONTRACT", "production frozen", lambda: require(contract["production_model_changed"] is False and contract["production_app_changed"] is False))
case("CONTRACT", "deep audit signal preserved", lambda: require(abs(contract["baseline_findings"]["deep_audit_20_session_event_spread"] - 0.075892) < 1e-12))

failed = [x for x in RESULTS if x["status"] != "PASS"]
print(json.dumps({"tests": len(RESULTS), "passed": len(RESULTS)-len(failed), "failed": len(failed), "failures": failed}, indent=2))
if failed:
    raise SystemExit(1)
