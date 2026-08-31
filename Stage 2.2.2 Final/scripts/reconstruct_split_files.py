"""Reconstruct compressed or numbered transport artifacts from the manifest."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import shutil
from pathlib import Path
from typing import Dict, List, Tuple


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


def validate_file(path: Path, expected_size: int, expected_sha256: str, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    actual_size = path.stat().st_size
    if actual_size != expected_size:
        raise RuntimeError(
            f"{label} size mismatch for {path}: expected {expected_size}, got {actual_size}"
        )
    actual_hash = sha256_file(path)
    if actual_hash.lower() != expected_sha256.lower():
        raise RuntimeError(
            f"{label} SHA-256 mismatch for {path}: expected {expected_sha256}, got {actual_hash}"
        )


def load_manifest(manifest_path: Path) -> List[Dict[str, str]]:
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


def part_paths(stored: Path, expected_count: int) -> List[Path]:
    if expected_count < 1:
        return []
    expected = [
        stored.with_name(f"{stored.name}.part{number:03d}")
        for number in range(1, expected_count + 1)
    ]
    missing = [path for path in expected if not path.is_file()]
    discovered = sorted(stored.parent.glob(stored.name + ".part*"))
    extras = [path for path in discovered if path not in expected]
    if missing or extras:
        details = []
        if missing:
            details.append("missing=" + ", ".join(path.name for path in missing))
        if extras:
            details.append("unexpected=" + ", ".join(path.name for path in extras))
        raise RuntimeError(f"Invalid part sequence for {stored}: {'; '.join(details)}")
    return expected


def concatenate_parts(parts: List[Path], destination: Path) -> None:
    with destination.open("wb") as output:
        for part in parts:
            with part.open("rb") as source:
                shutil.copyfileobj(source, output, length=BUFFER_SIZE)


def reconstruct_all(repo_root: Path, manifest_path: Path) -> List[Tuple[str, str]]:
    repo_root = repo_root.resolve()
    rows = load_manifest(manifest_path)
    results: List[Tuple[str, str]] = []
    for row in rows:
        target = safe_path(repo_root, row["path"])
        stored = safe_path(repo_root, row["stored_path"])
        target_size = int(row["size_bytes"])
        target_hash = row["sha256"].strip().lower()
        stored_size = int(row["stored_size_bytes"])
        stored_hash = row["stored_sha256"].strip().lower()
        compression = row["compression"].strip().upper()
        part_count = int(row["part_count"])

        if target.is_file():
            validate_file(target, target_size, target_hash, "Artifact")
            results.append((row["path"], "ALREADY_VALID"))
            continue

        stored_temporary: Path | None = None
        target_temporary = target.with_name(target.name + ".reconstructing.tmp")
        try:
            if part_count:
                parts = part_paths(stored, part_count)
                stored_temporary = stored.with_name(stored.name + ".joining.tmp")
                stored_temporary.parent.mkdir(parents=True, exist_ok=True)
                concatenate_parts(parts, stored_temporary)
                validate_file(
                    stored_temporary, stored_size, stored_hash, "Joined transport artifact"
                )
                stored_source = stored_temporary
            else:
                validate_file(stored, stored_size, stored_hash, "Transport artifact")
                stored_source = stored

            target.parent.mkdir(parents=True, exist_ok=True)
            if compression == "GZIP":
                with gzip.open(stored_source, "rb") as source, target_temporary.open("wb") as output:
                    shutil.copyfileobj(source, output, length=BUFFER_SIZE)
            elif compression == "NONE":
                shutil.copyfile(stored_source, target_temporary)
            else:
                raise ValueError(f"Unsupported compression {compression!r} for {row['path']}")

            validate_file(target_temporary, target_size, target_hash, "Reconstructed artifact")
            target_temporary.replace(target)
        finally:
            if target_temporary.exists():
                target_temporary.unlink()
            if stored_temporary is not None and stored_temporary.exists():
                stored_temporary.unlink()

        method = compression
        if part_count:
            method += f"_{part_count}_PARTS"
        results.append((row["path"], f"RECONSTRUCTED_FROM_{method}"))
    return results


def build_parser() -> argparse.ArgumentParser:
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    parser = argparse.ArgumentParser(
        description="Reconstruct manifest artifacts from compressed and/or numbered transport files"
    )
    parser.add_argument("--repo-root", type=Path, default=repo_root)
    parser.add_argument("--manifest", type=Path, default=repo_root / "artifact_manifest.csv")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    results = reconstruct_all(args.repo_root, args.manifest)
    for path, status in results:
        print(f"{status}: {path}")
    print(f"RECONSTRUCTION: PASS ({len(results)} manifest artifacts verified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
