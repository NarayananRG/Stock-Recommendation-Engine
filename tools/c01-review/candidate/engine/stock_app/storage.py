from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 6


class AppDatabase:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def initialize(self) -> None:
        self._backup_before_schema_migration()
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS app_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS portfolio_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    buy_price REAL NOT NULL,
                    buy_date TEXT NOT NULL,
                    notes TEXT DEFAULT '',
                    target_return REAL,
                    planned_horizon TEXT,
                    recommendation_id TEXT,
                    engine_version TEXT,
                    position_status TEXT DEFAULT 'OPEN',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS analysis_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_date TEXT NOT NULL UNIQUE,
                    run_status TEXT NOT NULL,
                    official_stock_status TEXT,
                    official_benchmark_status TEXT,
                    cohort001_count INTEGER DEFAULT 0,
                    cohort002_count INTEGER DEFAULT 0,
                    yfinance_calls INTEGER DEFAULT 0,
                    result_classification TEXT,
                    result_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS recommendation_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                    symbol TEXT,
                    recommendation_date TEXT,
                    engine TEXT NOT NULL,
                    engine_version TEXT,
                    score REAL,
                    confidence REAL,
                    expected_return REAL,
                    target_probability REAL,
                    downside_probability REAL,
                    target_return REAL,
                    holding_period TEXT,
                    action TEXT,
                    reasoning TEXT,
                    status TEXT,
                    raw_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS app_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS prediction_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    market_session TEXT NOT NULL,
                    capital REAL NOT NULL,
                    horizon_sessions INTEGER NOT NULL,
                    target_return REAL,
                    engine_version TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    feature_contract_version TEXT NOT NULL,
                    training_cutoff TEXT,
                    validation_contract TEXT NOT NULL,
                    status TEXT NOT NULL,
                    survivorship_limited INTEGER DEFAULT 1,
                    progress_log_json TEXT NOT NULL DEFAULT '[]',
                    request_json TEXT NOT NULL,
                    summary_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS prediction_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES prediction_runs(run_id) ON DELETE CASCADE,
                    rank INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    latest_close REAL,
                    affordable_qty INTEGER NOT NULL,
                    profit_probability REAL,
                    target_probability REAL,
                    expected_return REAL,
                    median_return REAL,
                    downside_risk REAL,
                    max_adverse_excursion REAL,
                    max_favorable_excursion REAL,
                    sample_size INTEGER NOT NULL,
                    confidence_label TEXT NOT NULL,
                    ranking_score REAL NOT NULL,
                    v1_status TEXT NOT NULL,
                    opportunity_status TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(run_id, symbol)
                );
                CREATE TABLE IF NOT EXISTS prediction_evidence_summary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES prediction_runs(run_id) ON DELETE CASCADE,
                    symbol TEXT NOT NULL,
                    similar_situations INTEGER NOT NULL,
                    positive_terminal_count INTEGER NOT NULL,
                    target_hit_count INTEGER,
                    median_return REAL,
                    worst_quartile REAL,
                    best_quartile REAL,
                    limitations TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(run_id, symbol)
                );
                """
            )
            self._migrate_leg3(conn)
            self._migrate_leg4(conn)
            self._migrate_leg7(conn)
            self._migrate_leg8(conn)
            conn.execute("INSERT OR REPLACE INTO app_metadata(key, value) VALUES ('leg7_schema_version', '1')")
            conn.execute("INSERT OR REPLACE INTO app_metadata(key, value) VALUES ('leg8_schema_version', '1')")
            for version in range(1, SCHEMA_VERSION + 1):
                conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (version,))
            conn.execute("INSERT OR REPLACE INTO app_metadata(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))


    def _backup_before_schema_migration(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        current = 0
        try:
            with sqlite3.connect(self.path) as conn:
                exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone()
                if exists:
                    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
                    current = int(row[0] or 0)
        except sqlite3.Error:
            current = 0
        if current >= SCHEMA_VERSION:
            return
        backup_dir = self.path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        target = backup_dir / f"pre_schema_v{SCHEMA_VERSION}_{stamp}.sqlite3"
        source = sqlite3.connect(self.path)
        try:
            dest = sqlite3.connect(target)
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()

    @staticmethod
    def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
        return any(row["name"] == column for row in conn.execute(f"PRAGMA table_info({table})"))

    def _add_column_if_missing(self, conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        if not self._column_exists(conn, table, column):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

    def _migrate_leg3(self, conn: sqlite3.Connection) -> None:
        self._add_column_if_missing(conn, "portfolio_positions", "source", "source TEXT DEFAULT 'MANUAL'")
        self._add_column_if_missing(conn, "portfolio_positions", "linked_lifecycle_id", "linked_lifecycle_id INTEGER")
        self._add_column_if_missing(conn, "portfolio_positions", "closed_at", "closed_at TEXT")
        self._add_column_if_missing(conn, "portfolio_positions", "sale_price", "sale_price REAL")
        self._add_column_if_missing(conn, "portfolio_positions", "sale_charges", "sale_charges REAL DEFAULT 0")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS recommendation_lifecycle (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recommendation_id INTEGER REFERENCES prediction_candidates(id),
                prediction_run_id TEXT REFERENCES prediction_runs(run_id),
                symbol TEXT NOT NULL,
                lifecycle_version TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                state TEXT NOT NULL,
                user_state_label TEXT NOT NULL,
                original_snapshot_json TEXT NOT NULL,
                current_assessment_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(recommendation_id)
            );
            CREATE TABLE IF NOT EXISTS position_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id INTEGER NOT NULL REFERENCES portfolio_positions(id) ON DELETE CASCADE,
                lifecycle_id INTEGER REFERENCES recommendation_lifecycle(id),
                prediction_run_id TEXT,
                recommendation_id INTEGER,
                symbol TEXT NOT NULL,
                source TEXT NOT NULL,
                original_snapshot_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(position_id)
            );
            CREATE TABLE IF NOT EXISTS daily_position_assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id INTEGER NOT NULL REFERENCES portfolio_positions(id) ON DELETE CASCADE,
                lifecycle_id INTEGER REFERENCES recommendation_lifecycle(id),
                market_session TEXT NOT NULL,
                state TEXT NOT NULL,
                action_label TEXT NOT NULL,
                current_close REAL,
                pnl_value REAL,
                pnl_percent REAL,
                sessions_held INTEGER,
                remaining_horizon INTEGER,
                target_progress REAL,
                metrics_json TEXT NOT NULL,
                explanation TEXT NOT NULL,
                engine_version TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(position_id, market_session)
            );
            CREATE TABLE IF NOT EXISTS state_transitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lifecycle_id INTEGER,
                position_id INTEGER,
                old_state TEXT,
                new_state TEXT NOT NULL,
                market_session TEXT,
                reason_code TEXT NOT NULL,
                explanation TEXT NOT NULL,
                metrics_before_json TEXT NOT NULL DEFAULT '{}',
                metrics_after_json TEXT NOT NULL DEFAULT '{}',
                engine_version TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS position_exit_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id INTEGER NOT NULL REFERENCES portfolio_positions(id) ON DELETE CASCADE,
                lifecycle_id INTEGER,
                sale_date TEXT NOT NULL,
                sale_price REAL NOT NULL,
                quantity_sold REAL NOT NULL,
                charges REAL DEFAULT 0,
                gross_return REAL,
                net_return REAL,
                holding_sessions INTEGER,
                target_achieved INTEGER,
                exit_reason TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

    def _migrate_leg4(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS fundamental_snapshot_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                as_of_date TEXT NOT NULL,
                latest_period TEXT,
                publication_timestamp TEXT,
                days_since_publication INTEGER,
                assessment TEXT NOT NULL,
                data_freshness TEXT NOT NULL,
                source TEXT NOT NULL,
                values_json TEXT NOT NULL,
                features_json TEXT NOT NULL,
                data_quality_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, as_of_date)
            );
            CREATE TABLE IF NOT EXISTS fundamental_app_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                event_type TEXT NOT NULL,
                source_document_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_document_id)
            );
            CREATE TABLE IF NOT EXISTS fundamental_source_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                checked_at TEXT DEFAULT CURRENT_TIMESTAMP,
                detail_json TEXT NOT NULL
            );
            """
        )


    def _migrate_leg7(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS leg7_daily_monitoring (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id INTEGER NOT NULL REFERENCES portfolio_positions(id) ON DELETE CASCADE,
                market_session TEXT NOT NULL,
                lifecycle_state TEXT NOT NULL,
                thesis_health TEXT NOT NULL,
                action TEXT NOT NULL,
                reason_codes_json TEXT NOT NULL DEFAULT '[]',
                explanation TEXT NOT NULL,
                target_progress REAL,
                sessions_remaining INTEGER,
                alternative_symbol TEXT,
                alternative_status TEXT NOT NULL DEFAULT 'NONE',
                alternative_streak INTEGER NOT NULL DEFAULT 0,
                gate_results_json TEXT NOT NULL DEFAULT '{}',
                evidence_changes_json TEXT NOT NULL DEFAULT '{}',
                data_freshness_json TEXT NOT NULL DEFAULT '{}',
                monitoring_policy_version TEXT NOT NULL,
                replacement_policy_version TEXT NOT NULL,
                snapshot_hash TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(position_id, market_session)
            );
            CREATE INDEX IF NOT EXISTS idx_leg7_monitoring_session ON leg7_daily_monitoring(market_session);
            CREATE INDEX IF NOT EXISTS idx_leg7_monitoring_action ON leg7_daily_monitoring(action);
            """
        )

    def _migrate_leg8(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS leg8_operational_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_name TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                detail_json TEXT NOT NULL DEFAULT '{}',
                operation_hash TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_leg8_operational_runs_name ON leg8_operational_runs(operation_name, id DESC);
            """
        )

    def integrity_report(self) -> dict[str, Any]:
        with self.connect() as conn:
            integrity_row = conn.execute("PRAGMA integrity_check").fetchone()
            integrity = str(integrity_row[0] if integrity_row else "unknown")
            foreign_keys = [dict(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()]
            journal_row = conn.execute("PRAGMA journal_mode").fetchone()
            journal_mode = str(journal_row[0] if journal_row else "unknown")
        return {
            "integrity_check": integrity,
            "foreign_key_violations": foreign_keys,
            "journal_mode": journal_mode,
        }

    def backup_to(self, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        # sqlite3 connection context managers do not close their connection.  Use
        # explicit close calls so Windows never carries a database handle into the
        # immediate backup-retention step.
        source = self.connect()
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            try:
                destination.close()
            finally:
                source.close()
        return target

    def record_operational_run(self, operation_name: str, status: str, detail: dict[str, Any], completed: bool = True) -> int:
        payload = json.dumps(detail, sort_keys=True, default=str)
        import hashlib
        operation_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO leg8_operational_runs(operation_name, status, completed_at, detail_json, operation_hash) VALUES (?, ?, CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END, ?, ?)",
                (operation_name, status, 1 if completed else 0, payload, operation_hash),
            )
            return int(cur.lastrowid)

    def record_event(self, event_type: str, payload: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO app_events(event_type, payload_json) VALUES (?, ?)",
                (event_type, json.dumps(payload, sort_keys=True, default=str)),
            )
