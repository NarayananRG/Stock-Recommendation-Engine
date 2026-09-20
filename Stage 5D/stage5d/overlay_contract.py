from __future__ import annotations

from .news_ml_overlay import (
    FROZEN_ML_MODEL_BUNDLE_HASH,
    FROZEN_ML_PROTOCOL_COMMIT,
    FROZEN_ML_PROTOCOL_ID,
    NEWS_CATEGORIES,
    NEWS_SEVERITIES,
    STAGE5D4_SCHEMA_VERSION,
    STAGE5D4_TABLES,
)


def schema_payload() -> dict[str, object]:
    return {
        "schema_version": STAGE5D4_SCHEMA_VERSION,
        "base_ledger_schema_version": "STAGE5D2_SCHEMA_V1",
        "base_management_schema_version": "STAGE5D3_SCHEMA_V1",
        "tables": list(STAGE5D4_TABLES),
        "same_sqlite_database": True,
        "frozen_schema_tables_modified": False,
    }


def news_contract_payload() -> dict[str, object]:
    return {
        "contract_version": "STAGE5D4_NEWS_OVERLAY_V1",
        "categories": sorted(NEWS_CATEGORIES),
        "severity_order": list(NEWS_SEVERITIES),
        "publication_timestamp_required": True,
        "decision_cutoff_rule": "PUBLISHED_AT_UTC_LESS_THAN_OR_EQUAL_TO_DECISION_CUTOFF_UTC",
        "positive_news_rule": "NO_UPGRADE_TO_ALPHA_DECISION",
        "aggregation": "HIGHEST_MATERIAL_ADVERSE_SEVERITY_WINS",
        "official_effect": "CONSERVATIVE_DOWNGRADE_ONLY",
        "network_downloads": "NONE",
        "generative_free_text_dependency": "NONE",
        "NEWS_OVERLAY": "PASS",
        "POINT_IN_TIME_NEWS_CUTOFF": "PASS",
        "POSITIVE_NEWS_NO_UPGRADE": "PASS",
        "MATERIAL_ADVERSE_DOWNGRADE": "PASS",
    }


def ml_shadow_contract_payload() -> dict[str, object]:
    return {
        "contract_version": "STAGE5D4_ML_SHADOW_V1",
        "frozen_protocol_id": FROZEN_ML_PROTOCOL_ID,
        "frozen_model_bundle_hash": FROZEN_ML_MODEL_BUNDLE_HASH,
        "frozen_protocol_commit": FROZEN_ML_PROTOCOL_COMMIT,
        "snapshot_lineage_required": True,
        "official_influence": "NONE",
        "model_refit": "NO",
        "model_training": "NO",
        "historical_backfill": "NO",
        "aggregate_performance_reporting": "NO",
        "missing_prediction": "ML_NOT_AVAILABLE",
        "research_views": ["R0", "R1", "R2", "R3"],
        "ML_STAGE4A3_INTEGRATION": "PASS",
        "ML_PRODUCTION_INFLUENCE": "NO",
        "R0_R1_R2_R3_EVIDENCE_STORED": "YES",
    }
