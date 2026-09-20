from __future__ import annotations

from .management_store import STAGE5D3_SCHEMA_VERSION, STAGE5D3_TABLES


def contract_payload() -> dict[str, object]:
    return {
        "contract_version": "STAGE5D3_MANAGEMENT_V1",
        "schema_version": STAGE5D3_SCHEMA_VERSION,
        "tables": list(STAGE5D3_TABLES),
        "supported_policies": {
            "STATIC_T2_20D": {"maximum_market_sessions": 20, "stop": "ORIGINAL_FIXED", "target": "ORIGINAL_TARGET_2"},
            "D1_TRAIL_ONLY_63D": {"maximum_market_sessions": 63, "stop": "NEXT_SESSION_RAISE_ONLY", "target": "ORIGINAL_TARGET_2"},
        },
        "entry_day_live_limitation": "Stage 5D.2 lacks intraday fill ordering; full-day entry-bar stop/target outcomes remain ENTRY_BAR_EXECUTION_ORDER_UNRESOLVED.",
        "observation_contract": "EXTERNALLY_SUPPLIED_COMPLETED_DAILY_OHLC_ONLY",
        "collision_rule": "STOP_FIRST",
        "managed_quantity_source": "STAGE5D2_EFFECTIVE_NONVOID_RECOMMENDATION_LINKED_TRANSACTIONS",
        "exit_semantics": "DECISION_ONLY_NO_AUTOMATIC_SELL",
        "ml_influence": "NONE",
        "news_influence": "NONE",
        "broker_integration": "NONE",
    }
