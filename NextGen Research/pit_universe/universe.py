"""Point-in-time universe contracts; contains no real historical constituent data."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from common import parse_date, parse_time, record, sha256

KNOWLEDGE = {"VERIFIED", "UNKNOWN", "NOT_AVAILABLE"}


def _validate_security(row: dict) -> dict:
    required = {"security_id", "entity_id", "ticker", "exchange", "listing_date", "eligibility_start", "knowledge_status"}
    missing = sorted(required - row.keys())
    if missing:
        raise ValueError(f"missing security fields: {','.join(missing)}")
    if row["knowledge_status"] not in KNOWLEDGE:
        raise ValueError("invalid knowledge status")
    listing = parse_date(row["listing_date"])
    start = parse_date(row["eligibility_start"])
    end = parse_date(row.get("eligibility_end"))
    delisting = parse_date(row.get("delisting_date"))
    if listing > start or (end and start > end) or (delisting and delisting < listing):
        raise ValueError("impossible date interval")
    if delisting and end and end > delisting:
        raise ValueError("eligibility after delisting")
    if row["knowledge_status"] == "VERIFIED":
        for field in ("source_id", "source_reference", "observed_at", "provenance_hash"):
            if not row.get(field):
                raise ValueError("VERIFIED facts require provenance")
        parse_time(row["observed_at"])
    elif any(row.get(k) for k in ("source_id", "source_reference", "provenance_hash")):
        raise ValueError("UNKNOWN/NOT_AVAILABLE cannot fabricate provenance")
    periods = row.get("symbol_periods", [])
    last_end = None
    for p in sorted(periods, key=lambda x: x["start"]):
        ps, pe = parse_date(p["start"]), parse_date(p.get("end"))
        if pe and pe < ps:
            raise ValueError("invalid symbol period")
        if last_end is None and periods.index(p) > 0:
            raise ValueError("open symbol period must be last")
        if last_end and ps <= last_end:
            raise ValueError("overlapping symbol periods")
        last_end = pe
    return dict(row)


@dataclass(frozen=True)
class SecurityMaster:
    records: tuple[dict, ...]
    dataset_id: str

    @classmethod
    def build(cls, rows: list[dict], dataset_id: str = "TEST_ONLY_SYNTHETIC_PIT_MASTER") -> "SecurityMaster":
        checked = [_validate_security(r) for r in rows]
        ids = [r["security_id"] for r in checked]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate security identity")
        ticker_periods: list[tuple] = []
        for r in checked:
            periods = r.get("symbol_periods") or [{"ticker": r["ticker"], "start": r["listing_date"], "end": r.get("delisting_date")}]
            for p in periods:
                ticker_periods.append((r["exchange"], p["ticker"], parse_date(p["start"]), parse_date(p.get("end")), r["security_id"]))
        for i, a in enumerate(ticker_periods):
            for b in ticker_periods[i + 1:]:
                if a[:2] == b[:2] and a[4] != b[4]:
                    a_end, b_end = a[3] or parse_date("9999-12-31"), b[3] or parse_date("9999-12-31")
                    if max(a[2], b[2]) <= min(a_end, b_end):
                        raise ValueError("contradictory ticker period")
        ordered = tuple(sorted(checked, key=lambda x: x["security_id"]))
        return cls(ordered, dataset_id)

    @property
    def dataset_hash(self) -> str:
        return sha256({"dataset_id": self.dataset_id, "records": self.records})


def eligible_universe(master: SecurityMaster, as_of_date: str, policy: dict, query_cutoff: str | None = None) -> dict:
    asof = parse_date(as_of_date)
    cutoff = parse_time(query_cutoff or f"{as_of_date}T23:59:59+00:00")
    included, unknown, excluded = [], 0, 0
    for row in master.records:
        if row["knowledge_status"] != "VERIFIED":
            unknown += 1
            continue
        observed = parse_time(row["observed_at"])
        archival = bool(row.get("archival_effective_date_verified")) and parse_date(row.get("effective_date")) <= asof
        if observed > cutoff and not archival:
            unknown += 1
            continue
        listing, start = parse_date(row["listing_date"]), parse_date(row["eligibility_start"])
        end, delisting = parse_date(row.get("eligibility_end")), parse_date(row.get("delisting_date"))
        permitted_exchange = row["exchange"] in policy.get("eligible_exchanges", [row["exchange"]])
        eligible = listing <= asof and start <= asof and (end is None or asof <= end) and (delisting is None or asof <= delisting) and permitted_exchange
        if not eligible:
            excluded += 1
            continue
        symbol = row["ticker"]
        for p in row.get("symbol_periods", []):
            if parse_date(p["start"]) <= asof and (not p.get("end") or asof <= parse_date(p["end"])):
                symbol = p["ticker"]
        included.append({"security_id": row["security_id"], "entity_id": row["entity_id"], "ticker": symbol, "exchange": row["exchange"]})
    payload = {
        "as_of_date": as_of_date,
        "policy_id": policy["policy_id"],
        "policy_hash": sha256(policy),
        "dataset_id": master.dataset_id,
        "dataset_hash": master.dataset_hash,
        "included_securities": sorted(included, key=lambda x: x["security_id"]),
        "excluded_count": excluded,
        "unknown_count": unknown,
        "architecture_status": "ARCHITECTURE_IMPLEMENTED",
        "data_status": "DATA_INCOMPLETE",
    }
    return record("PIT_UNIVERSE_SNAPSHOT_V1", payload)

