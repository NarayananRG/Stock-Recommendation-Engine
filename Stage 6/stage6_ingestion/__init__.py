"""Stage 6.1A fixture-only immutable ingestion foundation."""

from .evidence_store import IngestionStore
from .fixtures import build_fixture_registries
from .registry import (
    build_entity_registry, build_source_registry, resolve_alias, resolve_entity,
    resolve_source_record, resolve_ticker, verify_entity_registry, verify_source_registry,
)

__all__ = [
    "IngestionStore", "build_entity_registry", "build_source_registry", "resolve_alias",
    "resolve_entity", "resolve_source_record", "resolve_ticker", "verify_entity_registry",
    "verify_source_registry", "build_fixture_registries",
]
