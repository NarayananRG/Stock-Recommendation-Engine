"""Hash gates, parity comparison, and fail-fast validation utilities."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
import hashlib
import numpy as np
import pandas as pd


EXPECTED = {
 "STAGE21_CODE_HASH": "91d3d84760c4b2427d500f0bee0f2dc0ceeb7e4f2e31d51d17a64342777993d5",
 "STAGE221_CODE_HASH": "8e6514353cc32a5b8bed1212df0c12d76de11d0624e4931fda4028f0be3ed31f",
 "STAGE222_FINAL_CODE_HASH": "63345c591b46c656b204236d147993cb283d57fdbccd0246b7cef281d7968730",
 "DATA_CONTENT_HASH": "2b6a2bb93fcc6c3aa80d2115a002b8cba370f61442edb592ffc9bc95eaa02e35",
 "STRATEGY_HASH": "e62dc4e75c056a216cc4bdaa589a95f9553ce40e37aa6690974759b7975ad23c",
 "EXECUTION_BASELINE_HASH": "9434b39d2d7bbd8203a4674b4acdebfecf898afbc08cf7bc144729ec4b326c2b",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""): h.update(chunk)
    return h.hexdigest()


def hash_gates(paths: Dict[str, Path], identity: Dict[str, Any]) -> List[Dict[str, Any]]:
    actual = {"STAGE21_CODE_HASH": sha256(paths["stage21"]), "STAGE221_CODE_HASH": sha256(paths["stage221"]),
              "STAGE222_FINAL_CODE_HASH": sha256(paths["stage222"]), "DATA_CONTENT_HASH": identity["DATA_CONTENT_HASH"],
              "STRATEGY_HASH": identity["STRATEGY_HASH"], "EXECUTION_BASELINE_HASH": identity["EXECUTION_HASH"]}
    rows = []
    for name, expected in EXPECTED.items():
        rows.append({"Check": name, "Status": "PASS" if actual.get(name) == expected else "FAIL", "Expected": expected, "Actual": actual.get(name)})
    if any(r["Status"] == "FAIL" for r in rows): raise RuntimeError("Permanent baseline hash gate failed")
    return rows


def compare_frames(name: str, actual: pd.DataFrame, expected: pd.DataFrame, keys: List[str]) -> tuple[int, pd.DataFrame]:
    meta = {c for c in expected.columns if c in {"Experiment ID","STRATEGY_HASH","EXECUTION_HASH","STAGE21_CODE_HASH","STAGE221_CODE_HASH","STAGE222_CODE_HASH","DATA_CONTENT_HASH","MANIFEST_DOCUMENT_HASH","Survivorship Bias Warning","Signal ID"}}
    cols = [c for c in expected.columns if c not in meta and c in actual.columns]
    left = actual[cols].copy(); right = expected[cols].copy()
    for c in cols:
        if "Date" in c: left[c] = pd.to_datetime(left[c], errors="coerce"); right[c] = pd.to_datetime(right[c], errors="coerce")
    left = left.sort_values([k for k in keys if k in cols]).reset_index(drop=True)
    right = right.sort_values([k for k in keys if k in cols]).reset_index(drop=True)
    diffs = []
    if len(left) != len(right): diffs.append({"Artifact": name, "Row": -1, "Column": "ROW_COUNT", "Actual": len(left), "Expected": len(right)})
    for i in range(min(len(left), len(right))):
        for c in cols:
            a, b = left.at[i,c], right.at[i,c]
            if pd.isna(a) and pd.isna(b): continue
            if (pd.isna(a) and str(b).strip() == "") or (pd.isna(b) and str(a).strip() == ""): continue
            if pd.api.types.is_numeric_dtype(left[c]) and pd.api.types.is_numeric_dtype(right[c]):
                equal = bool(np.isclose(float(a), float(b), rtol=0, atol=1e-9, equal_nan=True))
            else: equal = str(a) == str(b)
            if not equal: diffs.append({"Artifact": name, "Row": i, "Column": c, "Actual": a, "Expected": b})
    return len(diffs), pd.DataFrame(diffs)
