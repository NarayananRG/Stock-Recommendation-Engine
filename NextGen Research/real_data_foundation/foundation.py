"""Offline parsers, verified cost schedules, calibration binding, and drift evidence.

This module deliberately has no HTTP client. Acquisition is an explicit operator step;
all tests operate on committed, sanitized structures or immutable stored research output.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from xml.etree import ElementTree as ET

from common import canonical_bytes, file_sha256, parse_date, parse_time, record, sha256
from pit_universe import SecurityMaster, eligible_universe
from calibration_governance import evaluate_calibration

RESEARCH_AUTHORITY = "RESEARCH_ONLY"


def source_descriptor(path: str | Path, *, archive_id: str, source_url: str,
                      retrieved_at: str, publisher: str, publication_date: str | None = None) -> dict:
    parse_time(retrieved_at)
    p = Path(path)
    if not p.is_file():
        raise ValueError("SOURCE_ARCHIVE_MISSING")
    return record("REAL_SOURCE_ARCHIVE_DESCRIPTOR_V1", {
        "archive_id": archive_id, "publisher": publisher, "source_url": source_url,
        "retrieved_at": retrieved_at, "publication_date": publication_date,
        "sha256": file_sha256(p), "content_length": p.stat().st_size,
        "local_storage_policy": "GITIGNORED_RAW_ARCHIVE", "authority_scope": RESEARCH_AUTHORITY,
    })


def _clean(row: dict) -> dict:
    return {str(k).strip(): (str(v).strip() if v is not None else "") for k, v in row.items()}


def parse_nse_security_master(content: bytes, *, observed_date: str, source_reference: str,
                              source_hash: str | None = None) -> list[dict]:
    digest = hashlib.sha256(content).hexdigest()
    if source_hash and source_hash.lower() != digest:
        raise ValueError("SOURCE_HASH_MISMATCH")
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    required = {"SYMBOL", "NAME OF COMPANY", "SERIES", "DATE OF LISTING", "ISIN NUMBER"}
    if not reader.fieldnames or required - {x.strip() for x in reader.fieldnames}:
        raise ValueError("UNSUPPORTED_NSE_SECURITY_MASTER_STRUCTURE")
    rows = []
    for raw in reader:
        r = _clean(raw)
        symbol, isin = r["SYMBOL"], r["ISIN NUMBER"]
        if not symbol or not isin:
            raise ValueError("MISSING_OFFICIAL_SECURITY_IDENTITY")
        listing = datetime.strptime(r["DATE OF LISTING"], "%d-%b-%Y").date().isoformat()
        rows.append({
            "security_id": f"NSE:{isin}", "entity_id": f"ISIN:{isin}", "ticker": symbol,
            "exchange": "NSE", "isin": isin, "series": r["SERIES"],
            "company_name": r["NAME OF COMPANY"], "listing_date": listing,
            "listing_date_status": "VERIFIED_LISTING_DATE", "eligibility_start": listing,
            "eligibility_end": None, "knowledge_status": "VERIFIED",
            "source_id": "NSE_OFFICIAL_EQUITY_SECURITY_MASTER", "source_reference": source_reference,
            "observed_at": f"{observed_date}T00:00:00+00:00", "provenance_hash": digest,
            "historical_membership_status": "UNKNOWN", "sector_history_status": "UNKNOWN",
        })
    ids = [r["security_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("DUPLICATE_OFFICIAL_SECURITY_IDENTITY")
    return sorted(rows, key=lambda x: x["security_id"])


def _xlsx_rows(content: bytes, sheet_index: int = 0) -> list[list[str]]:
    """Read simple XLSX values with the standard library (offline and dependency-free)."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for item in root.findall("m:si", ns):
                shared.append("".join(t.text or "" for t in item.findall(".//m:t", ns)))
        sheet = ET.fromstring(zf.read(f"xl/worksheets/sheet{sheet_index + 1}.xml"))
        out = []
        for row in sheet.findall(".//m:sheetData/m:row", ns):
            values = []
            for cell in row.findall("m:c", ns):
                value = cell.find("m:v", ns)
                raw = "" if value is None else value.text or ""
                if cell.get("t") == "s" and raw:
                    raw = shared[int(raw)]
                values.append(raw)
            out.append(values)
        return out


def parse_nse_delistings_xlsx(content: bytes, *, retrieved_at: str, source_reference: str,
                              source_hash: str | None = None) -> list[dict]:
    digest = hashlib.sha256(content).hexdigest()
    if source_hash and source_hash.lower() != digest:
        raise ValueError("SOURCE_HASH_MISMATCH")
    table = _xlsx_rows(content)
    expected = ["Symbol", "ISIN", "Company Name", "Board", "Delisted Date", "Type of Delisting"]
    if not table or table[0][:6] != expected:
        raise ValueError("UNSUPPORTED_NSE_DELISTING_STRUCTURE")
    epoch = datetime(1899, 12, 30, tzinfo=timezone.utc)
    return parse_nse_delisting_rows(table[1:], retrieved_at=retrieved_at,
                                    source_reference=source_reference, source_content_hash=digest)


def parse_nse_delisting_rows(table: list[list[str]], *, retrieved_at: str, source_reference: str,
                             source_content_hash: str) -> list[dict]:
    epoch = datetime(1899, 12, 30, tzinfo=timezone.utc)
    rows = []
    for values in table:
        values += [""] * (6 - len(values))
        if not values[0]:
            continue
        try:
            day = (epoch + __import__("datetime").timedelta(days=float(values[4]))).date().isoformat()
        except ValueError:
            day = parse_date(values[4]).isoformat()
        rows.append({
            "exchange": "NSE", "symbol": values[0], "isin": values[1],
            "company_name": values[2], "board": values[3], "effective_delisting_date": day,
            "delisting_type": values[5].strip(), "source_reference": source_reference,
            "source_retrieved_at": retrieved_at, "source_content_hash": source_content_hash,
            "verification_state": "REAL_VERIFIED",
        })
    return sorted(rows, key=lambda x: (x["effective_delisting_date"], x["symbol"]))


def apply_delistings(securities: list[dict], delistings: list[dict]) -> list[dict]:
    by_isin = {r["isin"]: r for r in delistings if r.get("isin")}
    out = []
    for security in securities:
        row = dict(security)
        event = by_isin.get(row.get("isin"))
        if event:
            row["delisting_date"] = event["effective_delisting_date"]
            row["eligibility_end"] = event["effective_delisting_date"]
            row["delisting_source_reference"] = event["source_reference"]
            row["delisting_source_hash"] = event["source_content_hash"]
        out.append(row)
    return out


def build_real_pit_snapshot(securities: list[dict], *, observed_date: str, source_dataset_id: str) -> dict:
    master = SecurityMaster.build(securities, dataset_id=source_dataset_id)
    policy = {"policy_id": "CURRENT_NSE_LISTED_SECURITIES_RESEARCH_V1", "eligible_exchanges": ["NSE"]}
    snapshot = eligible_universe(master, observed_date, policy, f"{observed_date}T23:59:59+00:00")
    snapshot["data_status"] = "REAL_VERIFIED_CURRENT_SNAPSHOT_PARTIAL_HISTORY"
    snapshot["survivorship_bias_fully_solved"] = False
    snapshot["historical_index_membership"] = "DATA_GAP"
    snapshot["historical_sector_membership"] = "UNKNOWN"
    return snapshot


def load_verified_cost_schedule(path: str | Path) -> dict:
    schedule = json.loads(Path(path).read_text(encoding="utf-8"))
    if schedule.get("artifact_id") != "INDIA_EQUITY_COST_SCHEDULE_V1" or schedule.get("verification_state") != "VERIFIED":
        raise ValueError("VERIFIED_COST_SCHEDULE_REQUIRED")
    if not schedule.get("canonical_hash"):
        raise ValueError("COST_SCHEDULE_HASH_REQUIRED")
    body = {k: v for k, v in schedule.items() if k != "canonical_hash"}
    if sha256(body) != schedule["canonical_hash"]:
        raise ValueError("COST_SCHEDULE_HASH_MISMATCH")
    return schedule


def select_cost_schedule(schedule: dict, session_date: str) -> dict:
    day = parse_date(session_date)
    start, end = parse_date(schedule["effective_from"]), parse_date(schedule.get("effective_to"))
    if day < start or (end and day > end):
        raise ValueError("COST_SCHEDULE_NOT_VERIFIED_FOR_DATE")
    return schedule


def calculate_verified_costs(gross: str | Decimal, side: str, schedule: dict,
                             brokerage_bps: str | Decimal = "0") -> dict:
    if side not in {"BUY", "SELL"}:
        raise ValueError("INVALID_SIDE")
    value = Decimal(str(gross))
    amounts, gst_base = {}, Decimal("0")
    for component in schedule["components"]:
        if side not in component["sides"]:
            continue
        amount = value * Decimal(str(component["rate_bps"])) / Decimal("10000")
        amount = amount.quantize(Decimal(component.get("rounding_unit", "0.01")), rounding=ROUND_HALF_UP)
        amounts[component["component"]] = amount
        if component.get("gst_taxable"):
            gst_base += amount
    brokerage = (value * Decimal(str(brokerage_bps)) / Decimal("10000")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    amounts["BROKERAGE"] = brokerage
    gst_base += brokerage
    gst = (gst_base * Decimal(str(schedule["gst"]["rate_percent"])) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    amounts["GST"] = gst
    return {
        "market_statutory_cost": str(sum((v for k, v in amounts.items() if k != "BROKERAGE"), Decimal("0"))),
        "broker_specific_cost": str(brokerage), "gst_taxable_base": str(gst_base),
        "components": {k: str(v) for k, v in sorted(amounts.items())},
    }


def parse_official_announcement(row: dict, *, source_id: str, cutoff_utc: str) -> dict:
    required = {"symbol", "company_name", "subject", "details", "attachment_reference",
                "broadcast_at_utc", "exchange_received_at_utc", "disseminated_at_utc"}
    if required - row.keys():
        raise ValueError("ANNOUNCEMENT_STRUCTURE_INVALID")
    received = parse_time(row["exchange_received_at_utc"])
    broadcast = parse_time(row["broadcast_at_utc"])
    disseminated = parse_time(row["disseminated_at_utc"])
    if not (received <= disseminated <= broadcast <= parse_time(cutoff_utc)):
        raise ValueError("ANNOUNCEMENT_PIT_TIMESTAMP_VIOLATION")
    return record("OFFICIAL_ANNOUNCEMENT_EVIDENCE_V1", {
        **row, "source_id": source_id, "evidence_class": "PRIMARY_EVIDENCE",
        "interpretation": None, "network_calls": 0,
    })


def load_stage4a3_rows(repo_root: str | Path, model: dict) -> tuple[list[dict], dict]:
    root = Path(repo_root)
    predictions = root / "Stage 4A" / "results" / "stage4a_oos_predictions.csv.gz"
    cohort = "BASELINE_PRIMARY" if model["mode"] == "PRIMARY_ONLY" else "RESEARCH_EXTENDED"
    rows = []
    with gzip.open(predictions, "rt", encoding="utf-8") as stream:
        for raw in csv.DictReader(stream):
            if (raw["Evaluation Year"] == "2026" and raw["Dataset Cohort"] == cohort and
                    raw["Target"] == model["target"] and raw["Model Variant"] == model["variant"] and
                    raw["Feature Set"] == model["feature_set"] and raw["Actual Label"] in {"0", "1"}):
                rows.append({"score": raw["Predicted Probability"], "outcome": raw["Actual Label"],
                             "window": raw["Signal Date"][:7], "regime": raw["Market Regime"]})
    identity = {
        "model_name": model["model_name"], "serialized_model_sha256": model["serialized_model_sha256"],
        "model_bundle_hash": "4631eb8a1d0b34212252df3b1aae180f64ec98ba5e7955a84729df0a471c62da",
        "feature_set_hash": model["feature_hash"], "dataset_id": "STAGE4A_OOS_2026_IMMUTABLE",
        "dataset_hash": file_sha256(predictions), "evaluation_period": "2026-01-01..2026-08-28",
        "target": model["target"], "sample_count": len(rows),
    }
    return rows, identity


def real_calibration_audit(repo_root: str | Path, policy: dict) -> dict:
    root = Path(repo_root)
    manifest = json.loads((root / "Stage 4A.3/results/stage4a3_model_bundle_manifest.json").read_text(encoding="utf-8"))
    evaluations = []
    for model in manifest["models"]:
        rows, identity = load_stage4a3_rows(root, model)
        result = evaluate_calibration(rows, model_id=identity["model_name"],
            model_hash=identity["serialized_model_sha256"], dataset_id=identity["dataset_id"],
            dataset_hash=identity["dataset_hash"], cutoff="2026-08-28", target=identity["target"], policy=policy)
        result["identity_binding"] = identity
        result["terminology_classification"] = "UNCALIBRATED_MODEL_SCORE"
        result["calibration_status"] = "INSUFFICIENT_EVIDENCE" if result.get("status", "").startswith("INSUFFICIENT") else "UNCALIBRATED_MODEL_SCORE"
        evaluations.append(result)
    return record("REAL_CALIBRATION_AUDIT_V1", {
        "model_bundle_hash": manifest["FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH"],
        "evaluations": evaluations, "retraining_performed": False, "legacy_artifacts_mutated": False,
    })


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _std(values: list[float]) -> float:
    m = _mean(values)
    return math.sqrt(sum((x - m) ** 2 for x in values) / len(values))


def _tvd(a: list[str], b: list[str]) -> float:
    ca, cb = Counter(a), Counter(b)
    return 0.5 * sum(abs(ca[k] / len(a) - cb[k] / len(b)) for k in set(ca) | set(cb))


def assess_drift(reference: list[dict], current: list[dict], policy: dict) -> dict:
    minimum = int(policy.get("minimum_sample", 0))
    if len(reference) < minimum or len(current) < minimum:
        status, metrics = "INSUFFICIENT_DATA", {}
    else:
        metrics = {}
        for field in policy.get("numeric_fields", []):
            left, right = [float(x[field]) for x in reference], [float(x[field]) for x in current]
            scale = _std(left)
            metrics[f"{field}_standardized_mean_shift"] = abs(_mean(right) - _mean(left)) / scale if scale else (0.0 if _mean(right) == _mean(left) else float("inf"))
        for field in policy.get("categorical_fields", []):
            metrics[f"{field}_total_variation"] = _tvd([str(x[field]) for x in reference], [str(x[field]) for x in current])
        breaches = sum(value >= float(policy["possible_threshold"]) for value in metrics.values())
        material = sum(value >= float(policy["material_threshold"]) for value in metrics.values())
        status = "MATERIAL_DRIFT" if material >= int(policy.get("material_metric_count", 2)) else "POSSIBLE_DRIFT" if breaches else "STABLE"
    return record("MODEL_DRIFT_ASSESSMENT_V1", {
        "reference_count": len(reference), "current_count": len(current), "metrics": metrics,
        "drift_status": status, "configuration_status": policy.get("configuration_status", "NOT_CONFIGURED_FOR_AUTOMATIC_ACTION"),
        "automatic_action": "NONE", "retraining_permitted": False, "authority_scope": RESEARCH_AUTHORITY,
    })


def retraining_research_gate(stats: dict, drift: dict) -> dict:
    gates = {
        "sample_sufficient": bool(stats.get("sample_sufficient")),
        "outcomes_mature": bool(stats.get("outcomes_mature")),
        "benchmark_comparable": bool(stats.get("benchmark_comparable")),
        "drift_evidence_present": drift.get("drift_status") in {"POSSIBLE_DRIFT", "MATERIAL_DRIFT"},
    }
    return {"gates": gates, "may_permit_offline_challenger_research": all(gates.values()),
            "automatic_training": False, "automatic_promotion": False}


def coverage_report(rows: list[dict]) -> dict:
    required = {"capability", "required_dataset", "candidate_source", "source_verified", "source_implemented",
                "earliest_verified_date", "latest_verified_date", "completeness", "known_gaps", "usability"}
    if any(required - row.keys() for row in rows):
        raise ValueError("INCOMPLETE_COVERAGE_ROW")
    ordered = sorted(rows, key=lambda x: x["capability"])
    return record("NEXTGEN_DATA_COVERAGE_REPORT_V1", {
        "capabilities": ordered, "gap_count": sum(bool(x["known_gaps"]) for x in ordered),
        "survivorship_bias_fully_solved": False, "authority_scope": RESEARCH_AUTHORITY,
    })
