from __future__ import annotations

import hashlib
from typing import Mapping

import pandas as pd


def random_key(seed: int, signal_id: str) -> str:
    return hashlib.sha256(f"{seed}|{signal_id}".encode("utf-8")).hexdigest()


def rank_policy(universe: pd.DataFrame, code: str, scores: Mapping[str, pd.Series] | None = None) -> pd.DataFrame:
    frame = universe[["Signal ID", "Ticker", "Signal Date", "Signal", "Original Signal", "Setup", "Market Regime", "Actionability Score", "Technical Score"]].copy()
    frame["Same-Date Candidate Count"] = frame.groupby("Signal Date")["Signal ID"].transform("size")
    if code == "R0":
        frame["Ranking Score"] = frame["Actionability Score"].astype(float) * 1000.0 + frame["Technical Score"].astype(float)
        frame = frame.sort_values(["Signal Date", "Actionability Score", "Technical Score", "Signal ID"], ascending=[True, False, False, True], kind="mergesort")
    else:
        if scores is None or code not in scores:
            raise KeyError(code)
        frame["Ranking Score"] = frame["Signal ID"].map(scores[code])
        if frame["Ranking Score"].isna().any():
            raise RuntimeError(f"Missing score for {code}")
        frame = frame.sort_values(["Signal Date", "Ranking Score", "Signal ID"], ascending=[True, False, True], kind="mergesort")
    frame["Same-Date Rank"] = frame.groupby("Signal Date").cumcount() + 1
    return frame.sort_values(["Signal Date", "Signal ID"], kind="mergesort").reset_index(drop=True)


def select_named(universe: pd.DataFrame, scores: Mapping[str, pd.Series]) -> tuple[dict[str, set[str]], pd.DataFrame]:
    selections: dict[str, set[str]] = {"ALL_BASELINE_PRIMARY": set(universe["Signal ID"].astype(str))}
    audit = universe[["Signal ID", "Ticker", "Signal Date", "Stop Loss", "Target 1", "Target 2"]].copy()
    audit["Same-Date Candidate Count"] = audit.groupby("Signal Date")["Signal ID"].transform("size")
    for code in ("R0", "R1", "R2", "R3", "R4", "R5"):
        ranked = rank_policy(universe, code, scores)
        lookup = ranked.set_index("Signal ID")
        audit[f"{code} Score"] = audit["Signal ID"].map(lookup["Ranking Score"])
        audit[f"{code} Rank"] = audit["Signal ID"].map(lookup["Same-Date Rank"]).astype(int)
        for k in (1, 2):
            name = f"{code}_K{k}"
            selected = set(ranked.loc[ranked["Same-Date Rank"] <= k, "Signal ID"].astype(str))
            selections[name] = selected
            audit[f"{name} Selected"] = audit["Signal ID"].astype(str).isin(selected)
    return selections, audit


def select_random(universe: pd.DataFrame, seed: int, k: int) -> set[str]:
    frame = universe[["Signal ID", "Signal Date"]].copy()
    frame["key"] = frame["Signal ID"].astype(str).map(lambda value: random_key(seed, value))
    frame = frame.sort_values(["Signal Date", "key", "Signal ID"], kind="mergesort")
    rank = frame.groupby("Signal Date").cumcount() + 1
    return set(frame.loc[rank <= k, "Signal ID"].astype(str))
