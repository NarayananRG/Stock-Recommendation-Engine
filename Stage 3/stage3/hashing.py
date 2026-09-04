"""Deterministic, machine-portable identity helpers for Stage 3."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import platform
from importlib import metadata
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


NA_TOKEN = "<NA>"
FLOAT_FORMAT = "%.12g"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_hash_candidates(path: Path) -> Mapping[str, str]:
    """Return exact and LF-normalized hashes for cross-platform baseline gates."""
    payload = Path(path).read_bytes()
    return {
        "raw": sha256_bytes(payload),
        "lf_normalized": sha256_bytes(payload.replace(b"\r\n", b"\n")),
    }


def matching_text_hash(path: Path, expected: str) -> tuple[str, str]:
    candidates = text_hash_candidates(path)
    for mode, value in candidates.items():
        if value == expected:
            return value, mode
    raise RuntimeError(f"Frozen source hash mismatch: {path}: {candidates}")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def canonical_json_hash(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def source_package_manifest(stage_root: Path, relative_paths: Iterable[str]) -> dict[str, Any]:
    rows = []
    for relative in sorted(set(relative_paths), key=str.lower):
        path = stage_root / relative
        rows.append({"relative_path": Path(relative).as_posix(), "sha256": sha256_file(path)})
    return {
        "hash_algorithm": "SHA-256",
        "normalization": "POSIX stage-relative paths; rows sorted by path; exact file bytes",
        "sources": rows,
        "package_hash": canonical_json_hash(rows),
    }


def deterministic_row_id(schema_version: str, *parts: Any) -> str:
    payload = "|".join([schema_version, *[str(value) for value in parts]])
    return sha256_bytes(payload.encode("utf-8"))


def _canonical_frame(frame: pd.DataFrame, columns: Sequence[str] | None = None) -> pd.DataFrame:
    result = frame.loc[:, list(columns) if columns is not None else list(frame.columns)].copy()
    for column in result.columns:
        series = result[column]
        if pd.api.types.is_datetime64_any_dtype(series):
            result[column] = pd.to_datetime(series, errors="coerce").dt.strftime("%Y-%m-%d")
        elif pd.api.types.is_bool_dtype(series):
            result[column] = series.astype("boolean")
    return result


def canonical_dataframe_bytes(frame: pd.DataFrame, columns: Sequence[str] | None = None) -> bytes:
    canonical = _canonical_frame(frame, columns)
    text = canonical.to_csv(
        index=False,
        columns=list(canonical.columns),
        lineterminator="\n",
        na_rep=NA_TOKEN,
        float_format=FLOAT_FORMAT,
        date_format="%Y-%m-%d",
    )
    return text.encode("utf-8")


def dataframe_content_hash(frame: pd.DataFrame, columns: Sequence[str] | None = None) -> str:
    return sha256_bytes(canonical_dataframe_bytes(frame, columns))


def dataframe_schema(frame: pd.DataFrame) -> list[dict[str, str]]:
    return [{"column": str(column), "dtype": str(frame[column].dtype)} for column in frame.columns]


def dataframe_schema_hash(frame: pd.DataFrame) -> str:
    return canonical_json_hash(dataframe_schema(frame))


def write_deterministic_csv_gz(frame: pd.DataFrame, path: Path) -> None:
    """Write stable gzip bytes (mtime=0, fixed CSV representation)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text:
                frame.to_csv(
                    text,
                    index=False,
                    lineterminator="\n",
                    na_rep=NA_TOKEN,
                    float_format=FLOAT_FORMAT,
                    date_format="%Y-%m-%d",
                )


def write_json(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8", newline="\n")


def environment_report() -> dict[str, Any]:
    def version(name: str) -> str:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return "NOT_INSTALLED"

    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "packages": {"numpy": np.__version__, "pandas": pd.__version__, "yfinance": version("yfinance")},
        "timezone": "Asia/Calcutta",
        "model_training_packages_used": [],
        "network_data_downloaded": False,
    }
