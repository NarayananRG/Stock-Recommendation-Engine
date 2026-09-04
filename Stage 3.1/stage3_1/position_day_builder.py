"""Target-specific semantic metadata for unchanged Stage 3 D1 position-day rows."""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd


def harden_position_day_labels(frame: pd.DataFrame, config: Mapping[str, Any]) -> pd.DataFrame:
    result = frame.copy()
    result["D1_FINAL_APPLICABLE"] = pd.Series(True, index=result.index, dtype="boolean")
    d1_data_end = result["D1_LABEL_CENSORED"].fillna(True).astype(bool)
    result["D1_FINAL_STATUS"] = pd.Series(
        ["DATA_END_CENSORED" if value else "AVAILABLE" for value in d1_data_end],
        index=result.index,
        dtype="string",
    )
    result["D1_FINAL_DATA_END_CENSORED"] = d1_data_end.astype("boolean")
    result["D1_FINAL_UNAVAILABLE_REASON"] = pd.Series(
        ["D1_TRAJECTORY_UNRESOLVED_AT_DATA_END" if value else "NONE" for value in d1_data_end],
        index=result.index,
        dtype="string",
    )
    result["D1_LABEL_CENSORED"] = result["D1_FINAL_DATA_END_CENSORED"]

    for horizon in config["position_day_horizons"]:
        legacy = result[f"NEXT_{horizon}_SESSION_CENSORED"].fillna(True).astype(bool)
        result[f"NEXT_{horizon}_SESSION_APPLICABLE"] = pd.Series(True, index=result.index, dtype="boolean")
        result[f"NEXT_{horizon}_SESSION_STATUS"] = pd.Series(
            ["DATA_END_CENSORED" if value else "AVAILABLE" for value in legacy],
            index=result.index,
            dtype="string",
        )
        result[f"NEXT_{horizon}_SESSION_DATA_END_CENSORED"] = legacy.astype("boolean")
        result[f"NEXT_{horizon}_SESSION_UNAVAILABLE_REASON"] = pd.Series(
            [f"INSUFFICIENT_FUTURE_SESSIONS_FOR_{horizon}" if value else "NONE" for value in legacy],
            index=result.index,
            dtype="string",
        )
        result[f"NEXT_{horizon}_SESSION_CENSORED"] = result[f"NEXT_{horizon}_SESSION_DATA_END_CENSORED"]
    return result
