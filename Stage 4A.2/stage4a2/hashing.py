from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import numpy as np


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _scalar(value: Any) -> str:
    if value is None or value is pd.NA:
        return "<NA>"
    try:
        if pd.isna(value):
            return "<NA>"
    except (TypeError, ValueError):
        pass
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    if isinstance(value, (bool, np.bool_)):
        return "TRUE" if bool(value) else "FALSE"
    if isinstance(value, (float, np.floating)):
        return format(float(value), ".12g")
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return str(value).replace("\r\n", "\n").replace("\r", "\n")


def dataframe_content_hash(frame: pd.DataFrame, columns: Iterable[str] | None = None) -> str:
    selected = list(columns) if columns is not None else list(frame.columns)
    output = io.StringIO(newline="")
    output.write(",".join(json.dumps(str(c), ensure_ascii=False) for c in selected) + "\n")
    for row in frame.loc[:, selected].itertuples(index=False, name=None):
        output.write(",".join(json.dumps(_scalar(v), ensure_ascii=False) for v in row) + "\n")
    return hashlib.sha256(output.getvalue().encode("utf-8")).hexdigest()


def package_hash(root: Path, relative_paths: Iterable[str]) -> str:
    entries = [(str(path).replace("\\", "/"), sha256_file(root / path)) for path in sorted(relative_paths)]
    return canonical_json_hash(entries)
