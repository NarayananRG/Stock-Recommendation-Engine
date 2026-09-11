from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str) + "\n").encode("utf-8")


def canonical_json_hash(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


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
        return format(float(value), ".17g")
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return str(value).replace("\r\n", "\n").replace("\r", "\n")


def dataframe_content_hash(frame: pd.DataFrame, columns: Iterable[str] | None = None) -> str:
    selected = list(columns) if columns is not None else list(frame.columns)
    output = io.StringIO(newline="")
    output.write(",".join(json.dumps(str(column), ensure_ascii=False) for column in selected) + "\n")
    for row in frame.loc[:, selected].itertuples(index=False, name=None):
        output.write(",".join(json.dumps(_scalar(value), ensure_ascii=False) for value in row) + "\n")
    return sha256_bytes(output.getvalue().encode("utf-8"))


def package_manifest(root: Path, relative_paths: Iterable[str]) -> dict[str, Any]:
    rows = [{"relative_path":str(path).replace("\\","/"),"sha256":sha256_file(root/path),"bytes":(root/path).stat().st_size} for path in sorted(relative_paths)]
    return {"sources":rows,"package_hash":canonical_json_hash([(row["relative_path"],row["sha256"]) for row in rows])}
