from __future__ import annotations

SCHEMA_VERSION = "STAGE5D2_SCHEMA_V1"

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE ledger_meta (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        schema_version TEXT NOT NULL,
        database_id TEXT NOT NULL UNIQUE,
        created_at_utc TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE allocation_runs (
        allocation_run_id TEXT PRIMARY KEY,
        decision_date TEXT NOT NULL,
        profile_version INTEGER NOT NULL,
        capital_ceiling_inr TEXT NOT NULL,
        selected_horizon TEXT NOT NULL,
        management_policy_id TEXT,
        horizon_session_limit INTEGER,
        portfolio_summary_json TEXT NOT NULL,
        portfolio_snapshot_json TEXT NOT NULL,
        recommendation_count INTEGER NOT NULL CHECK (recommendation_count >= 0),
        actionable_recommendation_count INTEGER NOT NULL CHECK (actionable_recommendation_count >= 0),
        canonical_payload_json TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL,
        persisted_at_utc TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE recommendations (
        recommendation_id TEXT PRIMARY KEY,
        allocation_run_id TEXT NOT NULL REFERENCES allocation_runs(allocation_run_id),
        signal_id TEXT NOT NULL,
        profile_version INTEGER NOT NULL,
        ordinal INTEGER NOT NULL CHECK (ordinal > 0),
        ticker TEXT NOT NULL,
        signal_date TEXT NOT NULL,
        decision_date TEXT NOT NULL,
        deterministic_signal TEXT NOT NULL,
        setup TEXT,
        trade_quality TEXT,
        technical_score TEXT,
        actionability_score TEXT,
        planned_rr_t1 TEXT,
        planned_rr_t2 TEXT,
        rs60 TEXT,
        market_regime TEXT,
        market_score TEXT,
        entry_low TEXT,
        entry_high TEXT,
        sizing_entry_price TEXT,
        stop TEXT,
        target_1 TEXT,
        target_2 TEXT,
        recommended_quantity INTEGER NOT NULL CHECK (recommended_quantity >= 0),
        estimated_purchase_value_inr TEXT NOT NULL,
        risk_budget_inr TEXT NOT NULL,
        risk_per_share_inr TEXT,
        selected_horizon TEXT NOT NULL,
        management_policy_id TEXT,
        management_policy_source TEXT,
        management_policy_max_sessions INTEGER,
        management_policy_validation_semantics TEXT,
        horizon_status TEXT NOT NULL,
        portfolio_action_status TEXT NOT NULL,
        plain_language_reason TEXT NOT NULL,
        canonical_payload_json TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL,
        persisted_at_utc TEXT NOT NULL,
        UNIQUE (allocation_run_id, ordinal)
    )
    """,
    """
    CREATE TABLE recommendation_events (
        event_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL UNIQUE,
        recommendation_id TEXT NOT NULL REFERENCES recommendations(recommendation_id),
        event_type TEXT NOT NULL CHECK (event_type IN ('PROPOSED','PENDING_ENTRY','DECLINED','CANCELLED','EXPIRED','PARTIALLY_FILLED','FILLED')),
        effective_date TEXT NOT NULL,
        recorded_at_utc TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL,
        idempotency_key TEXT NOT NULL UNIQUE
    )
    """,
    """
    CREATE TABLE user_transactions (
        transaction_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id TEXT NOT NULL UNIQUE,
        idempotency_key TEXT NOT NULL UNIQUE,
        ticker TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        side TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        price_inr TEXT NOT NULL,
        fees_inr TEXT NOT NULL,
        recommendation_id TEXT REFERENCES recommendations(recommendation_id),
        signal_id TEXT,
        external_reference TEXT,
        notes TEXT,
        canonical_payload_json TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL,
        recorded_at_utc TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE transaction_voids (
        void_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        void_id TEXT NOT NULL UNIQUE,
        transaction_id TEXT NOT NULL REFERENCES user_transactions(transaction_id),
        idempotency_key TEXT NOT NULL UNIQUE,
        reason TEXT NOT NULL,
        voided_at_utc TEXT NOT NULL,
        canonical_payload_json TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE opening_positions (
        opening_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        opening_position_id TEXT NOT NULL UNIQUE,
        idempotency_key TEXT NOT NULL UNIQUE,
        ticker TEXT NOT NULL,
        effective_date TEXT NOT NULL,
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        average_cost_per_share_inr TEXT NOT NULL,
        notes TEXT,
        canonical_payload_json TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL,
        recorded_at_utc TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE position_state_snapshots (
        snapshot_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id TEXT NOT NULL UNIQUE,
        as_of_date TEXT NOT NULL,
        ticker TEXT NOT NULL,
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        average_cost_per_share_inr TEXT NOT NULL,
        current_market_price_inr TEXT NOT NULL,
        market_value_inr TEXT NOT NULL,
        unrealized_pnl_inr TEXT NOT NULL,
        management_policy_id TEXT,
        source_recommendation_id TEXT REFERENCES recommendations(recommendation_id),
        source_signal_id TEXT,
        canonical_payload_json TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL,
        persisted_at_utc TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE recommendation_outcome_versions (
        recommendation_id TEXT NOT NULL REFERENCES recommendations(recommendation_id),
        outcome_version INTEGER NOT NULL CHECK (outcome_version > 0),
        as_of_date TEXT NOT NULL,
        outcome_status TEXT NOT NULL CHECK (outcome_status IN ('PENDING','RESOLVED','CENSORED')),
        entry_filled INTEGER,
        entry_date TEXT,
        stop_hit INTEGER,
        target_1_hit INTEGER,
        target_2_hit INTEGER,
        max_price_after_signal TEXT,
        min_price_after_signal TEXT,
        mfe_pct TEXT,
        mae_pct TEXT,
        mfe_r TEXT,
        mae_r TEXT,
        time_to_entry_sessions INTEGER,
        time_to_t1_sessions INTEGER,
        time_to_t2_sessions INTEGER,
        holding_sessions INTEGER,
        realized_r TEXT,
        exit_reason TEXT,
        methodology_version TEXT NOT NULL,
        source_data_hash TEXT,
        canonical_payload_json TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL,
        persisted_at_utc TEXT NOT NULL,
        PRIMARY KEY (recommendation_id, outcome_version)
    )
    """,
    "CREATE INDEX idx_recommendations_date ON recommendations(decision_date)",
    "CREATE INDEX idx_recommendations_ticker ON recommendations(ticker)",
    "CREATE INDEX idx_events_recommendation ON recommendation_events(recommendation_id, event_sequence)",
    "CREATE INDEX idx_transactions_ticker_date ON user_transactions(ticker, trade_date, transaction_sequence)",
    "CREATE INDEX idx_transactions_recommendation ON user_transactions(recommendation_id)",
    "CREATE INDEX idx_outcomes_recommendation ON recommendation_outcome_versions(recommendation_id, outcome_version)",
)

TABLES = (
    "ledger_meta",
    "allocation_runs",
    "recommendations",
    "recommendation_events",
    "user_transactions",
    "transaction_voids",
    "opening_positions",
    "position_state_snapshots",
    "recommendation_outcome_versions",
)
