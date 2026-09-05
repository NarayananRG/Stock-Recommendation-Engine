"""Path-independent hashing and deterministic serialization."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def canonical_json_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


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


def dataframe_content_hash(frame: pd.DataFrame, columns: Sequence[str] | None = None) -> str:
    selected = list(columns) if columns is not None else list(frame.columns)
    output = io.StringIO(newline="")
    output.write(",".join(json.dumps(str(c), ensure_ascii=False) for c in selected) + "\n")
    for row in frame.loc[:, selected].itertuples(index=False, name=None):
        output.write(",".join(json.dumps(_scalar(v), ensure_ascii=False) for v in row) + "\n")
    return hashlib.sha256(output.getvalue().encode("utf-8")).hexdigest()


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n", date_format="%Y-%m-%d", float_format="%.12g")


def write_csv_gz(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = frame.to_csv(index=False, lineterminator="\n", date_format="%Y-%m-%d", float_format="%.12g", na_rep="").encode("utf-8")
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            zipped.write(payload)


def write_json(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8", newline="\n")


def source_package_manifest(stage_root: Path, relative_paths: Iterable[str]) -> dict[str, Any]:
    rows = []
    for relative in sorted(str(v).replace("\\", "/") for v in relative_paths):
        path = stage_root / relative
        rows.append({"relative_path": relative, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    identity = [{"relative_path": row["relative_path"], "sha256": row["sha256"]} for row in rows]
    return {"sources": rows, "package_hash": canonical_json_hash(identity)}
