from __future__ import annotations

from typing import Any

import pandas as pd


def checks_to_frame(checks: list[tuple[str, bool, Any, Any]]) -> pd.DataFrame:
    return pd.DataFrame([
        {"Check": name, "Status": "PASS" if passed else "FAIL", "Expected": expected, "Actual": actual}
        for name, passed, expected, actual in checks
    ])


def require_pass(frame: pd.DataFrame) -> None:
    failures = frame[frame["Status"] != "PASS"]
    if not failures.empty:
        raise RuntimeError("Validation failed: " + "; ".join(failures["Check"].astype(str)))


def evidence_classification(paired: pd.DataFrame, bootstrap: pd.DataFrame, random_percentiles: pd.DataFrame, recent: pd.DataFrame, yearly: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, item in paired[paired["Policy"].str.match(r"R[1-4]_K[12]")].iterrows():
        policy = item["Policy"]
        boot = bootstrap[(bootstrap["Policy"] == policy) & (bootstrap["Block Length"] == 63) & (bootstrap["Metric"] == "Terminal Return %")].iloc[0]
        rand = random_percentiles[(random_percentiles["Policy"] == policy) & (random_percentiles["Metric"] == "Total Return %")].iloc[0]
        rec = recent[recent["Policy"] == policy].iloc[0]
        years_better = int(yearly.loc[yearly["Policy"] == policy, "Return >= R0"].sum())
        criteria = {
            "Return > R0": item["Delta Total Return %"] > 0,
            "CAGR > R0": item["Delta CAGR %"] > 0,
            "Expectancy > R0": item["Delta Expectancy R"] > 0,
            "Profit Factor >= R0": item["Delta Profit Factor"] >= 0,
            "Bootstrap lower delta return > 0": boot["Delta 2.5%"] > 0,
            "Random return percentile >= 95": rand["Random Percentile %"] >= 95,
            "Recent delta return >= 0": rec["Delta Return vs R0 %"] >= 0,
            "Max DD not worse by >2pp": item["Delta Maximum Drawdown %"] >= -2,
            "At least 6 years >= R0": years_better >= 6,
            "At least 50 trades": item["Trade Count"] >= 50,
        }
        passed = sum(criteria.values())
        point_names = ("Return > R0", "CAGR > R0", "Expectancy > R0", "Profit Factor >= R0")
        point_passed = sum(bool(criteria[name]) for name in point_names)
        if passed == len(criteria):
            label = "ROBUST POSITIVE ECONOMIC UTILITY"
        elif item["Trade Count"] < 50:
            label = "INSUFFICIENT SAMPLE"
        elif point_passed == len(point_names):
            label = "WEAK POSITIVE ECONOMIC UTILITY"
        elif point_passed == 0:
            label = "NO ECONOMIC UTILITY"
        else:
            label = "MIXED / INCONCLUSIVE"
        rows.append({"Policy": policy, "Economic Evidence Classification": label, "Primary Point Criteria Passed": point_passed,
                     "Criteria Passed": passed, "Criteria Required": len(criteria), **criteria})
    return pd.DataFrame(rows)
