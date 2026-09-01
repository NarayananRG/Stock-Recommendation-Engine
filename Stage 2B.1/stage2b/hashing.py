"""Portable identity and immutable-data verification for Stage 2B.1."""
from __future__ import annotations

import hashlib
import json
import platform
from importlib import metadata
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def resolve_dependency_root(repo_root: Path, override: Optional[Path], name: str) -> Path:
    """Resolve one dependency without searching arbitrary ancestors."""
    candidate = Path(override).expanduser().resolve() if override else (repo_root / name).resolve()
    if not candidate.is_dir():
        hint = f" (from explicit override {override})" if override else f" (expected repository sibling {name!r})"
        raise FileNotFoundError(f"Required dependency root is missing: {candidate}{hint}")
    return candidate


def package_manifest(stage_root: Path, sources: Iterable[Path]) -> Tuple[Dict[str, Any], str]:
    rows = []
    for path in sorted({Path(p).resolve() for p in sources}, key=lambda p: p.as_posix().lower()):
        relative = path.relative_to(stage_root.resolve()).as_posix()
        rows.append({"relative_path": relative, "sha256": sha256_file(path)})
    package_hash = canonical_hash(rows)
    return {"hash_algorithm": "SHA-256", "normalization": "POSIX repository-relative paths; rows sorted by path", "sources": rows, "package_hash": package_hash}, package_hash


def environment_report() -> Dict[str, Any]:
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
    }


def frozen_data_checks(
    data_dir: Path,
    expected_tickers: Sequence[str],
) -> Tuple[pd.DataFrame, Dict[str, Any], str, str]:
    """Verify canonical manifest identity, every file, ticker set, and CSV schema."""
    manifest_path = data_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Frozen manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    embedded = str(manifest.get("manifest_sha256", ""))
    unhashed = dict(manifest); unhashed.pop("manifest_sha256", None)
    canonical = canonical_hash(unhashed)
    checks = [{"Type": "HASH_GATE", "Check": "manifest canonical hash", "Status": "PASS" if canonical == embedded else "FAIL", "Expected": embedded, "Actual": canonical}]
    tickers = []
    required_columns = ["Date", "Open", "High", "Low", "Close", "Volume"]
    for item in manifest.get("files", []):
        ticker = str(item["ticker"]); tickers.append(ticker); file_path = data_dir / str(item["filename"])
        exists = file_path.is_file()
        checks.append({"Type": "HASH_GATE", "Check": f"file exists: {ticker}", "Status": "PASS" if exists else "FAIL", "Expected": item["filename"], "Actual": str(exists)})
        if not exists:
            continue
        actual_hash = sha256_file(file_path)
        checks.append({"Type": "HASH_GATE", "Check": f"file SHA-256: {ticker}", "Status": "PASS" if actual_hash == item["sha256"] else "FAIL", "Expected": item["sha256"], "Actual": actual_hash})
        frame = pd.read_csv(file_path)
        actual_columns = list(frame.columns)
        checks.append({"Type": "INTEGRATION", "Check": f"columns: {ticker}", "Status": "PASS" if actual_columns == required_columns else "FAIL", "Expected": "|".join(required_columns), "Actual": "|".join(actual_columns)})
        dates = pd.to_datetime(frame.get("Date"), errors="coerce")
        duplicates = int(dates.duplicated().sum())
        first = dates.min().strftime("%Y-%m-%d") if dates.notna().any() else "NaT"
        last = dates.max().strftime("%Y-%m-%d") if dates.notna().any() else "NaT"
        checks.append({"Type": "INTEGRATION", "Check": f"duplicate dates: {ticker}", "Status": "PASS" if duplicates == int(item.get("duplicate_date_count", 0)) == 0 else "FAIL", "Expected": item.get("duplicate_date_count", 0), "Actual": duplicates})
        checks.append({"Type": "INTEGRATION", "Check": f"date bounds: {ticker}", "Status": "PASS" if first == item.get("first_date") and last == item.get("last_date") else "FAIL", "Expected": f"{item.get('first_date')}..{item.get('last_date')}", "Actual": f"{first}..{last}"})
    wanted = {"^NSEI", *map(str, expected_tickers)}
    actual = set(tickers)
    checks.append({"Type": "HASH_GATE", "Check": "exact frozen ticker set", "Status": "PASS" if actual == wanted else "FAIL", "Expected": "|".join(sorted(wanted)), "Actual": "|".join(sorted(actual))})
    content = [{"ticker": item["ticker"], "filename": item["filename"], "sha256": item["sha256"]} for item in sorted(manifest.get("files", []), key=lambda row: row["ticker"])]
    data_hash = canonical_hash(content)
    document_hash = canonical_hash(manifest)
    frame = pd.DataFrame(checks)
    if (frame["Status"] != "PASS").any():
        failed = frame.loc[frame["Status"] != "PASS", "Check"].tolist()
        raise RuntimeError(f"Frozen data integrity failed: {failed}")
    return frame, manifest, data_hash, document_hash
