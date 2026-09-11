from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from .hashing import canonical_json_hash


COVERAGE_COLUMNS = [
    "Sequence", "Market Session Date", "Status", "Detected UTC",
    "Detection Source", "Previous Coverage Hash", "Coverage Hash",
]
COVERAGE_GENESIS = "STAGE4A3_SESSION_COVERAGE_GENESIS"


def _row_hash(row: dict[str, object]) -> str:
    return canonical_json_hash({key: str(row[key]) for key in COVERAGE_COLUMNS if key != "Coverage Hash"})


def load_coverage(path: Path) -> pd.DataFrame:
    if not path.exists() or not path.stat().st_size:
        return pd.DataFrame(columns=COVERAGE_COLUMNS)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def verify_coverage(path: Path) -> bool:
    frame = load_coverage(path)
    prior = COVERAGE_GENESIS
    seen: set[str] = set()
    for number, row in frame.iterrows():
        values = row.to_dict()
        day = str(values["Market Session Date"])
        if (
            int(values["Sequence"]) != number + 1
            or values["Previous Coverage Hash"] != prior
            or day in seen
            or values["Status"] not in {"CAPTURED", "MISSED"}
            or _row_hash(values) != values["Coverage Hash"]
        ):
            return False
        seen.add(day)
        prior = values["Coverage Hash"]
    return True


def append_coverage(path: Path, market_session_date: str, status: str,
                    detected_utc: str, detection_source: str) -> bool:
    if status not in {"CAPTURED", "MISSED"}:
        raise ValueError("INVALID_SESSION_COVERAGE_STATUS")
    frame = load_coverage(path)
    if not verify_coverage(path):
        raise RuntimeError("SESSION_COVERAGE_CHAIN_INVALID")
    existing = frame.loc[frame["Market Session Date"].eq(market_session_date)]
    if not existing.empty:
        if existing.iloc[0]["Status"] != status:
            raise RuntimeError("CONTRADICTORY_SESSION_COVERAGE_STATUS")
        return False
    prior = COVERAGE_GENESIS if frame.empty else str(frame.iloc[-1]["Coverage Hash"])
    row = {
        "Sequence": len(frame) + 1,
        "Market Session Date": market_session_date,
        "Status": status,
        "Detected UTC": detected_utc,
        "Detection Source": detection_source,
        "Previous Coverage Hash": prior,
    }
    row["Coverage Hash"] = _row_hash(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.concat([frame, pd.DataFrame([row], columns=COVERAGE_COLUMNS)], ignore_index=True).to_csv(
        path, index=False, lineterminator="\n"
    )
    return True


def audit_prior_sessions(audit_root: Path, activation_local_date: str,
                         current_signal_date: str, valid_market_sessions: Iterable[str],
                         detected_utc: str) -> list[str]:
    """Record gaps only; this function never creates or backfills snapshots."""
    coverage_path = audit_root / "session_coverage_index.csv"
    snapshot_path = audit_root / "prospective_snapshot_index.csv"
    snapshots = pd.read_csv(snapshot_path, dtype=str) if snapshot_path.exists() and snapshot_path.stat().st_size else pd.DataFrame()
    captured = set(snapshots.get("Signal Date", pd.Series(dtype=str)).astype(str))
    activation = pd.Timestamp(activation_local_date).normalize()
    current = pd.Timestamp(current_signal_date).normalize()
    eligible = sorted({pd.Timestamp(value).normalize() for value in valid_market_sessions if activation < pd.Timestamp(value).normalize() < current})
    missed: list[str] = []
    for session in eligible:
        day = session.date().isoformat()
        status = "CAPTURED" if day in captured else "MISSED"
        if append_coverage(coverage_path, day, status, detected_utc, "FROZEN_NIFTY_SESSION_HISTORY") and status == "MISSED":
            missed.append(day)
    return missed


def coverage_counts(path: Path, as_of_date: str | None = None) -> dict[str, int]:
    if not verify_coverage(path):
        raise RuntimeError("SESSION_COVERAGE_CHAIN_INVALID")
    frame = load_coverage(path)
    if as_of_date and not frame.empty:
        frame = frame.loc[pd.to_datetime(frame["Market Session Date"]) <= pd.Timestamp(as_of_date)]
    return {
        "eligible_sessions": len(frame),
        "captured_sessions": int(frame["Status"].eq("CAPTURED").sum()) if len(frame) else 0,
        "missed_sessions": int(frame["Status"].eq("MISSED").sum()) if len(frame) else 0,
    }
