"""Deterministic logical-content and artifact hashing for Stage 3.1."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import platform
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def canonical_json_hash(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def source_package_manifest(stage_root: Path, relative_paths: Iterable[str]) -> dict[str, Any]:
    sources = []
    for relative in sorted(str(value).replace("\\", "/") for value in relative_paths):
        path = stage_root / relative
        sources.append({"relative_path": relative, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    return {"sources": sources, "package_hash": canonical_json_hash([{"relative_path": x["relative_path"], "sha256": x["sha256"]} for x in sources])}


def deterministic_row_id(schema_version: str, *parts: Any) -> str:
    payload = "|".join([schema_version, *[str(value) for value in parts]])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_scalar(value: Any) -> str:
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


def canonical_dataframe_bytes(frame: pd.DataFrame, columns: Sequence[str] | None = None) -> bytes:
    selected = list(columns) if columns is not None else list(frame.columns)
    output = io.StringIO(newline="")
    output.write(",".join(json.dumps(str(column), ensure_ascii=False) for column in selected) + "\n")
    for row in frame.loc[:, selected].itertuples(index=False, name=None):
        output.write(",".join(json.dumps(_canonical_scalar(value), ensure_ascii=False) for value in row) + "\n")
    return output.getvalue().encode("utf-8")


def dataframe_content_hash(frame: pd.DataFrame, columns: Sequence[str] | None = None) -> str:
    return sha256_bytes(canonical_dataframe_bytes(frame, columns))


def dataframe_schema(frame: pd.DataFrame) -> list[dict[str, str]]:
    return [{"column": str(column), "dtype": str(frame[column].dtype)} for column in frame.columns]


def dataframe_schema_hash(frame: pd.DataFrame) -> str:
    return canonical_json_hash(dataframe_schema(frame))


def write_deterministic_csv_gz(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = frame.to_csv(
        index=False,
        lineterminator="\n",
        date_format="%Y-%m-%d",
        float_format="%.12g",
        na_rep="",
    ).encode("utf-8")
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            zipped.write(payload)


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n", date_format="%Y-%m-%d", float_format="%.12g")


def write_json(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8", newline="\n")


def directory_hash(root: Path) -> str:
    records = []
    for path in sorted(value for value in root.rglob("*") if value.is_file()):
        records.append({"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)})
    return canonical_json_hash(records)


def environment_report() -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "packages": {"pandas": pd.__version__, "numpy": np.__version__, "yfinance": "NOT_USED"},
        "network_data_downloaded": False,
        "model_training_packages_used": [],
        "timezone": "Asia/Calcutta",
    }
