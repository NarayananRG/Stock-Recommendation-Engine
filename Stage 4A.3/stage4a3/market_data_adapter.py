from __future__ import annotations

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd


IST = ZoneInfo("Asia/Kolkata")
AFTER_CLOSE = time(15, 45)


def validate_capture_window(now: datetime, signal_date: str, manifest: dict[str, Any]) -> None:
    local = now.astimezone(IST)
    intended = pd.Timestamp(signal_date).date()
    if local.date() == intended and local.time().replace(tzinfo=None) < AFTER_CLOSE:
        raise RuntimeError("BEFORE_AFTER_CLOSE_WINDOW")
    maximum = pd.Timestamp(manifest["maximum_market_data_date"]).date()
    nifty_maximum = pd.Timestamp(manifest["nifty_maximum_date"]).date()
    if maximum < intended or nifty_maximum < intended:
        raise RuntimeError("DATA_NOT_READY")
    if maximum > intended or nifty_maximum > intended:
        raise RuntimeError("FUTURE_MARKET_DATA_BLOCKED")
    required = {"provider_identifier", "download_timestamp_utc", "ticker_count_requested", "ticker_count_received", "missing_tickers", "raw_data_logical_hash"}
    missing = sorted(required - set(manifest))
    if missing:
        raise ValueError(f"MARKET_DATA_MANIFEST_INCOMPLETE: {missing}")
