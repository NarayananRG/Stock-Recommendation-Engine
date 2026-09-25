"""Read-only integrity entry point."""
from __future__ import annotations

from .evidence_store import IngestionStore


def verify_store(store: IngestionStore) -> dict:
    return store.integrity_check()
