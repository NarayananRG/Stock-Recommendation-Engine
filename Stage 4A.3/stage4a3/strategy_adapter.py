from __future__ import annotations

import pandas as pd


SIGNAL_COLUMNS = ["Signal ID","Ticker","Signal Date","Original Signal","Signal","Setup","Market Regime","Trade Quality","Actionability Score","Technical Score","Planned Entry","Initial Stop","Original T1","Original T2","Dataset Cohort"]


def baseline_primary_at_signal_close(frame: pd.DataFrame) -> pd.DataFrame:
    """Read-only Stage 3.1 cohort adapter; no future outcome filtering is permitted."""
    missing = [name for name in SIGNAL_COLUMNS if name not in frame]
    if missing:
        raise ValueError(f"MISSING_FROZEN_SIGNAL_FIELDS: {missing}")
    result = frame.loc[frame["Dataset Cohort"].eq("BASELINE_PRIMARY")].copy()
    if result["Signal ID"].duplicated().any():
        raise ValueError("DUPLICATE_SIGNAL_ID")
    return result
