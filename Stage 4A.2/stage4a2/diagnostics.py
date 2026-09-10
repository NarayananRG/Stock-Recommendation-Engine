from __future__ import annotations

import numpy as np
import pandas as pd


def selection_attribution(selections: dict[str, set[str]], ledgers: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for code in ("R1", "R2", "R3", "R4", "R5"):
        for k in (1, 2):
            policy, rule = f"{code}_K{k}", f"R0_K{k}"
            ml, rr = selections[policy], selections[rule]
            ml_filled = set(ledgers[policy].get("Signal ID", pd.Series(dtype=str)).astype(str))
            rr_filled = set(ledgers[rule].get("Signal ID", pd.Series(dtype=str)).astype(str))
            row = {"Policy": policy, "Comparator": rule, "Same-Date Candidate Dates": np.nan,
                   "Same Selections": len(ml & rr), "Different Selections": len(ml ^ rr),
                   "Shared Selected Signal IDs": len(ml & rr), "ML-Only Selected Signal IDs": len(ml - rr),
                   "Rule-Only Selected Signal IDs": len(rr - ml), "Shared Filled Trades": len(ml_filled & rr_filled),
                   "ML-Only Filled Trades": len(ml_filled - rr_filled), "Rule-Only Filled Trades": len(rr_filled - ml_filled)}
            for label, ids in (("ML-Only", ml_filled - rr_filled), ("Rule-Only", rr_filled - ml_filled)):
                frame = ledgers[policy if label == "ML-Only" else rule]
                frame = frame[frame["Signal ID"].astype(str).isin(ids)] if not frame.empty else frame
                r = pd.to_numeric(frame.get("Net R", pd.Series(dtype=float)), errors="coerce")
                row[f"{label} Mean Net R"] = r.mean(); row[f"{label} Median Net R"] = r.median()
                row[f"{label} Win Rate %"] = (pd.to_numeric(frame.get("Net PnL", pd.Series(dtype=float)), errors="coerce") > 0).mean() * 100 if len(frame) else np.nan
                row[f"{label} T1 Rate %"] = frame.get("T1 Reached", pd.Series(dtype=bool)).mean() * 100 if len(frame) else np.nan
                row[f"{label} T2 Rate %"] = frame.get("T2 Reached", pd.Series(dtype=bool)).mean() * 100 if len(frame) else np.nan
                row[f"{label} Average Hold"] = pd.to_numeric(frame.get("Holding Sessions", pd.Series(dtype=float)), errors="coerce").mean()
            rows.append(row)
    return pd.DataFrame(rows)


def exposure_matched_control(policy_daily: pd.DataFrame, rule_daily: pd.DataFrame, policy: str) -> pd.DataFrame:
    p = policy_daily.set_index("Date").sort_index()
    r = rule_daily.set_index("Date").sort_index()
    joined = p[["Exposure"]].rename(columns={"Exposure": "ML Exposure"}).join(
        r[["Exposure", "Daily Return %"]].rename(columns={"Exposure": "Rule Exposure", "Daily Return %": "Rule Daily Return %"}), how="inner"
    )
    joined["Prior ML Exposure"] = joined["ML Exposure"].shift(1).fillna(0)
    joined["Prior Rule Exposure"] = joined["Rule Exposure"].shift(1).fillna(0)
    joined["Scale"] = np.where(joined["Prior Rule Exposure"] > 0, joined["Prior ML Exposure"] / joined["Prior Rule Exposure"], 0.0)
    joined["Scale"] = joined["Scale"].clip(0, 1)
    joined["Exposure-Matched Rule Return %"] = joined["Rule Daily Return %"] * joined["Scale"]
    joined["Exposure-Matched Equity"] = 100000.0 * (1 + joined["Exposure-Matched Rule Return %"] / 100).cumprod()
    joined["Policy"] = policy; joined["Comparator"] = f"R0_K{policy[-1]}"
    return joined.reset_index()
