from __future__ import annotations

from typing import Any

import pandas as pd


def checks_frame(checks: list[tuple[str, bool, Any, Any, str]]) -> pd.DataFrame:
    return pd.DataFrame([{"Check":name,"Status":"PASS" if passed else "FAIL","Expected":expected,"Actual":actual,"Details":details} for name,passed,expected,actual,details in checks])


def require_pass(frame: pd.DataFrame) -> None:
    failed=frame[frame["Status"]!="PASS"]
    if not failed.empty:
        raise RuntimeError("Validation failed: "+"; ".join(failed["Check"].astype(str)))
