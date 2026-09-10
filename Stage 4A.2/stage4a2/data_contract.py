from __future__ import annotations

from pathlib import Path

import pandas as pd


EVALUATION_START = pd.Timestamp("2016-01-01")
EVALUATION_END = pd.Timestamp("2026-08-28")


def load_baseline_primary(repo_root: Path) -> pd.DataFrame:
    path = repo_root / "Stage 3.1" / "results" / "stage3_1_trade_opportunity_dataset.csv.gz"
    frame = pd.read_csv(path, low_memory=False)
    frame["Signal Date"] = pd.to_datetime(frame["Signal Date"]).dt.normalize()
    frame = frame.loc[
        frame["Dataset Cohort"].eq("BASELINE_PRIMARY")
        & frame["Signal Date"].between(EVALUATION_START, EVALUATION_END)
    ].copy()
    if frame["Signal ID"].duplicated().any():
        raise ValueError("BASELINE_PRIMARY Signal ID is not unique")
    if not frame["Signal"].isin(["BUY", "STRONG BUY"]).all():
        raise ValueError("BASELINE_PRIMARY contains a non BUY/STRONG BUY row")
    return frame.sort_values(["Signal Date", "Signal ID"], kind="mergesort").reset_index(drop=True)


def signal_time_view(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "Signal ID", "Ticker", "Signal Date", "Signal", "Original Signal", "Setup",
        "Market Regime", "Actionability Score", "Technical Score", "Dataset Cohort",
    ]
    return frame[columns].copy()
