"""Entry-window semantic hardening without changing frozen entry logic."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd


def load_frozen_calendars(repo_root: Path, frozen_path: str, tickers: Sequence[str]) -> dict[str, pd.DatetimeIndex]:
    frozen_root = repo_root / frozen_path
    manifest = json.loads((frozen_root / "manifest.json").read_text(encoding="utf-8"))
    file_by_ticker = {str(item["ticker"]): str(item["filename"]) for item in manifest["files"]}
    calendars: dict[str, pd.DatetimeIndex] = {}
    for ticker in sorted(set(str(value) for value in tickers)):
        if ticker not in file_by_ticker:
            raise RuntimeError(f"Frozen data missing ticker {ticker}")
        dates = pd.read_csv(frozen_root / file_by_ticker[ticker], usecols=["Date"])["Date"]
        calendars[ticker] = pd.DatetimeIndex(pd.to_datetime(dates, errors="raise")).normalize()
    return calendars


def harden_entry_semantics(
    stage3: pd.DataFrame,
    calendars: Mapping[str, pd.DatetimeIndex],
    config: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    result = stage3.copy()
    changes: list[dict[str, Any]] = []
    required_values: list[int] = []
    observed_values: list[int] = []
    complete_values: list[bool] = []
    applicable_values: list[bool] = []
    status_values: list[str] = []
    data_end_values: list[bool] = []
    reason_values: list[str] = []
    filled_values: list[Any] = []
    available_values: list[Any] = []

    for row in result.to_dict("records"):
        ticker = str(row["Ticker"])
        signal_date = pd.Timestamp(row["Signal Date"]).normalize()
        setup = str(row["Setup"])
        required = int(config["breakout_entry_window"] if setup == "BREAKOUT" else config["pullback_entry_window"])
        future = calendars[ticker][calendars[ticker] > signal_date][:required]
        observed = int(len(future))
        complete = observed >= required
        stage3_filled = row.get("ENTRY_FILLED")
        is_filled = pd.notna(stage3_filled) and bool(stage3_filled)

        if is_filled:
            filled: Any = True
            data_end = False
            reason = "NONE"
            available = pd.Timestamp(row["ENTRY_DATE"]).normalize()
            status = "FILLED" if bool(row.get("ENTRY_RISK_VALID")) else "FILLED_INVALID_RISK"
        elif complete:
            filled = False
            data_end = False
            reason = "NONE"
            available = pd.Timestamp(future[-1]).normalize()
            status = "NOT_FILLED"
        else:
            filled = pd.NA
            data_end = True
            reason = "NO_FUTURE_SESSION" if observed == 0 else "INCOMPLETE_ENTRY_WINDOW"
            available = pd.NaT
            status = "DATA_END_CENSORED"

        required_values.append(required)
        observed_values.append(observed)
        complete_values.append(complete)
        applicable_values.append(True)
        status_values.append(status)
        data_end_values.append(data_end)
        reason_values.append(reason)
        filled_values.append(filled)
        available_values.append(available)

        old_filled = row.get("ENTRY_FILLED")
        old_censored = bool(row.get("ENTRY_CENSORED")) if pd.notna(row.get("ENTRY_CENSORED")) else True
        changed = (pd.isna(old_filled) != pd.isna(filled)) or (
            pd.notna(old_filled) and pd.notna(filled) and bool(old_filled) != bool(filled)
        ) or old_censored != data_end
        if changed:
            changes.append(
                {
                    "Signal ID": row["Signal ID"],
                    "Ticker": ticker,
                    "Signal Date": signal_date,
                    "Setup": setup,
                    "Required Sessions": required,
                    "Observed Sessions": observed,
                    "Stage 3 ENTRY_FILLED": old_filled,
                    "Stage 3.1 ENTRY_FILLED": filled,
                    "Stage 3 ENTRY_CENSORED": old_censored,
                    "Stage 3.1 ENTRY_DATA_END_CENSORED": data_end,
                    "Reason": reason,
                }
            )

    result["ENTRY_WINDOW_REQUIRED_SESSIONS"] = pd.Series(required_values, index=result.index, dtype="Int64")
    result["ENTRY_WINDOW_OBSERVED_SESSIONS"] = pd.Series(observed_values, index=result.index, dtype="Int64")
    result["ENTRY_WINDOW_COMPLETE"] = pd.Series(complete_values, index=result.index, dtype="boolean")
    result["ENTRY_APPLICABLE"] = pd.Series(applicable_values, index=result.index, dtype="boolean")
    result["ENTRY_STATUS"] = pd.Series(status_values, index=result.index, dtype="string")
    result["ENTRY_DATA_END_CENSORED"] = pd.Series(data_end_values, index=result.index, dtype="boolean")
    result["ENTRY_UNAVAILABLE_REASON"] = pd.Series(reason_values, index=result.index, dtype="string")
    result["ENTRY_FILLED"] = pd.Series(filled_values, index=result.index, dtype="boolean")
    result["ENTRY_LABEL_AVAILABLE_DATE"] = pd.to_datetime(available_values, errors="coerce")
    result["ENTRY_CENSORED"] = result["ENTRY_DATA_END_CENSORED"].astype("boolean")

    change_columns = [
        "Signal ID", "Ticker", "Signal Date", "Setup", "Required Sessions", "Observed Sessions",
        "Stage 3 ENTRY_FILLED", "Stage 3.1 ENTRY_FILLED", "Stage 3 ENTRY_CENSORED",
        "Stage 3.1 ENTRY_DATA_END_CENSORED", "Reason",
    ]
    return result, pd.DataFrame(changes, columns=change_columns)
