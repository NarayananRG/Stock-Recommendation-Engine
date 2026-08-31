"""Verify logical artifacts and their compressed/split transport representation."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
from typing import Dict, List


BUFFER_SIZE = 1024 * 1024
REQUIRED_COLUMNS = {
    "path", "size_bytes", "sha256", "stored_path", "stored_size_bytes",
    "stored_sha256", "compression", "part_count",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(BUFFER_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest(manifest_path: Path) -> List[Dict[str, str]]:
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Artifact manifest missing: {manifest_path}")
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        columns = set(reader.fieldnames or [])
    if not rows or not REQUIRED_COLUMNS.issubset(columns):
        raise ValueError(
            "Artifact manifest is empty or missing columns: "
            + ", ".join(sorted(REQUIRED_COLUMNS - columns))
        )
    return rows


def safe_path(repo_root: Path, relative_text: str) -> Path:
    relative = Path(relative_text)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Unsafe path in manifest: {relative_text}")
    resolved = (repo_root / relative).resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError(f"Path escapes repository root: {relative_text}") from exc
    return resolved


def validate_file(path: Path, expected_size: int, expected_hash: str, label: str) -> str | None:
    if not path.is_file():
        return f"missing {label}: {path}"
    actual_size = path.stat().st_size
    if actual_size != expected_size:
        return f"{label} size mismatch: {path} expected={expected_size} actual={actual_size}"
    actual_hash = sha256_file(path)
    if actual_hash.lower() != expected_hash.lower():
        return f"{label} SHA-256 mismatch: {path} expected={expected_hash} actual={actual_hash}"
    return None


def validate_parts(stored: Path, count: int, expected_size: int, expected_hash: str) -> str | None:
    expected = [
        stored.with_name(f"{stored.name}.part{number:03d}")
        for number in range(1, count + 1)
    ]
    missing = [path.name for path in expected if not path.is_file()]
    discovered = sorted(stored.parent.glob(stored.name + ".part*"))
    extras = [path.name for path in discovered if path not in expected]
    if missing or extras:
        return f"invalid part sequence for {stored}: missing={missing} unexpected={extras}"
    digest = hashlib.sha256()
    total = 0
    for part in expected:
        total += part.stat().st_size
        with part.open("rb") as handle:
            for chunk in iter(lambda: handle.read(BUFFER_SIZE), b""):
                digest.update(chunk)
    if total != expected_size:
        return f"joined transport size mismatch: {stored} expected={expected_size} actual={total}"
    actual_hash = digest.hexdigest()
    if actual_hash.lower() != expected_hash.lower():
        return f"joined transport SHA-256 mismatch: {stored} expected={expected_hash} actual={actual_hash}"
    return None


def verify_manifest(repo_root: Path, manifest_path: Path) -> int:
    repo_root = repo_root.resolve()
    rows = read_manifest(manifest_path)
    failures: List[str] = []
    for row in rows:
        target = safe_path(repo_root, row["path"])
        stored = safe_path(repo_root, row["stored_path"])
        failure = validate_file(
            target, int(row["size_bytes"]), row["sha256"].strip(), "artifact"
        )
        if failure:
            failures.append(failure)

        part_count = int(row["part_count"])
        if part_count:
            failure = validate_parts(
                stored,
                part_count,
                int(row["stored_size_bytes"]),
                row["stored_sha256"].strip(),
            )
        else:
            failure = validate_file(
                stored,
                int(row["stored_size_bytes"]),
                row["stored_sha256"].strip(),
                "transport artifact",
            )
        if failure:
            failures.append(failure)

    if failures:
        raise RuntimeError("Artifact verification failed:\n" + "\n".join(failures))
    return len(rows)


def build_parser() -> argparse.ArgumentParser:
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    parser = argparse.ArgumentParser(description="Verify artifact_manifest.csv")
    parser.add_argument("--repo-root", type=Path, default=repo_root)
    parser.add_argument("--manifest", type=Path, default=repo_root / "artifact_manifest.csv")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    count = verify_manifest(args.repo_root, args.manifest)
    print(f"ARTIFACT VERIFICATION: PASS ({count} artifacts and transport files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
