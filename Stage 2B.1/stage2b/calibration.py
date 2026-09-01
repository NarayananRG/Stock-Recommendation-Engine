"""Past-only empirical target-time and confidence calibration."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Tuple
import numpy as np
import pandas as pd


LEVELS = (
    (1, ["Setup", "Market Regime", "Technical Band", "Actionability Band"]),
    (2, ["Setup", "Market Regime"]),
    (3, ["Setup"]),
    (4, []),
)


def score_band(value: Any) -> str:
    try: x = float(value)
    except (TypeError, ValueError): return "MISSING"
    if x < 70: return "<70"
    if x < 80: return "70-79"
    if x < 90: return "80-89"
    return "90-100"


def prepare_outcomes(source: pd.DataFrame, t1: pd.DataFrame, t2: pd.DataFrame) -> pd.DataFrame:
    keep = source.reset_index(drop=True).copy()
    keep = keep[keep["Signal"].isin(["BUY", "STRONG BUY"])].copy()
    keep["Technical Band"] = keep["Technical Score"].map(score_band)
    keep["Actionability Band"] = keep["Actionability Score"].map(score_band)
    for label, frame in (("T1", t1), ("T2", t2)):
        aligned = frame.loc[keep.index]
        if label == "T1" and "Candidate Entry Date" in aligned:
            keep["Entry Date"] = pd.to_datetime(aligned["Candidate Entry Date"], errors="coerce").dt.normalize()
        keep[f"{label} Resolution Date"] = pd.to_datetime(aligned["Candidate Exit Date"], errors="coerce").dt.normalize()
        keep[f"{label} Sessions"] = pd.to_numeric(aligned["Candidate Bars Held"], errors="coerce")
        keep[f"{label} Success"] = aligned["Candidate Exit Reason"].astype(str).str.startswith("TARGET")
    keep["Resolution Date"] = keep[["T1 Resolution Date", "T2 Resolution Date"]].max(axis=1)
    return keep.reset_index(drop=True)


def build_tables(outcomes: pd.DataFrame, year_first_sessions: Dict[int, pd.Timestamp], minimum: int = 30) -> pd.DataFrame:
    rows = []
    for year, first_session in sorted(year_first_sessions.items()):
        eligible = outcomes[outcomes["Resolution Date"].notna() & (outcomes["Resolution Date"] < first_session)].copy()
        data_end = eligible["Resolution Date"].max() if not eligible.empty else pd.NaT
        for level, keys in LEVELS:
            groups: Iterable[Tuple[Any, pd.DataFrame]] = [((), eligible)] if not keys else eligible.groupby(keys, dropna=False, sort=True)
            for key, group in groups:
                if not isinstance(key, tuple): key = (key,)
                row = {"Calibration Year": year, "As Of Date": first_session, "Calibration Data End Date": data_end,
                       "Cohort Level": level, "Observations": len(group), "Eligible": len(group) >= minimum}
                row.update({k: v for k, v in zip(keys, key)})
                for target in ("T1", "T2"):
                    wins = int(group[f"{target} Success"].sum()); n = len(group)
                    hit_days = pd.to_numeric(group.loc[group[f"{target} Success"], f"{target} Sessions"], errors="coerce").dropna()
                    row[f"{target} Successes"] = wins
                    row[f"P({target} Before Stop)"] = (wins + 1) / (n + 2)
                    row[f"{target} Q25"] = hit_days.quantile(.25) if len(hit_days) else np.nan
                    row[f"{target} Median"] = hit_days.quantile(.5) if len(hit_days) else np.nan
                    row[f"{target} Q75"] = hit_days.quantile(.75) if len(hit_days) else np.nan
                row["Cohort"] = "OVERALL" if not keys else "|".join(str(row[k]) for k in keys)
                rows.append(row)
    return pd.DataFrame(rows)


def resolve(tables: pd.DataFrame, signal: Dict[str, Any], year: int) -> Dict[str, Any]:
    subset = tables[(tables["Calibration Year"] == year) & tables["Eligible"]].copy()
    values = {"Setup": signal.get("Setup"), "Market Regime": signal.get("Market Regime"),
              "Technical Band": score_band(signal.get("Technical Score")),
              "Actionability Band": score_band(signal.get("Actionability Score"))}
    for level, keys in LEVELS:
        trial = subset[subset["Cohort Level"] == level]
        for key in keys: trial = trial[trial[key].astype(str) == str(values[key])]
        if not trial.empty:
            r = trial.iloc[0]
            return {"as_of": r["As Of Date"], "data_end": r["Calibration Data End Date"], "cohort": r["Cohort"],
                    "level": int(r["Cohort Level"]), "n": int(r["Observations"]),
                    "t1_q25": r["T1 Q25"], "t1_median": r["T1 Median"], "t1_q75": r["T1 Q75"],
                    "p_t1": r["P(T1 Before Stop)"], "p_t2": r["P(T2 Before Stop)"]}
    return {"as_of": pd.NaT, "data_end": pd.NaT, "cohort": "NO_VALID_COHORT", "level": 0, "n": 0,
            "t1_q25": np.nan, "t1_median": np.nan, "t1_q75": np.nan, "p_t1": np.nan, "p_t2": np.nan}
