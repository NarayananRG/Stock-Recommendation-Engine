"""Atomic content-addressed storage for exact fixture payload bytes."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .canonical import sha256_bytes
from .errors import IntegrityFailure


class RawPayloadStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def relative_reference(self, digest: str) -> str:
        return f"raw/{digest[:2]}/{digest}"

    def path_for(self, digest: str) -> Path:
        return self.root / digest[:2] / digest

    def put(self, payload: bytes) -> tuple[str, str, int]:
        if not isinstance(payload, bytes):
            raise TypeError("RAW_PAYLOAD_MUST_BE_BYTES")
        digest = sha256_bytes(payload)
        target = self.path_for(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if sha256_bytes(target.read_bytes()) != digest or target.read_bytes() != payload:
                raise IntegrityFailure("RAW_PAYLOAD_EXISTING_OBJECT_MISMATCH")
            return digest, self.relative_reference(digest), len(payload)
        descriptor, temporary = tempfile.mkstemp(prefix="stage6_raw_", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if sha256_bytes(Path(temporary).read_bytes()) != digest:
                raise IntegrityFailure("RAW_PAYLOAD_ATOMIC_WRITE_MISMATCH")
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return digest, self.relative_reference(digest), len(payload)

    def verify(self, digest: str, expected_size: int | None = None) -> Path:
        path = self.path_for(digest)
        if not path.is_file():
            raise IntegrityFailure("RAW_PAYLOAD_MISSING")
        data = path.read_bytes()
        if sha256_bytes(data) != digest:
            raise IntegrityFailure("RAW_PAYLOAD_HASH_MISMATCH")
        if expected_size is not None and len(data) != expected_size:
            raise IntegrityFailure("RAW_PAYLOAD_SIZE_MISMATCH")
        return path
