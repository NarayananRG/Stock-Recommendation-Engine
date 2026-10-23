from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


SCHEMA_VERSION = 4
PIT_VALID = {"FULL_PIT_VALID", "PIT_VALID_WITH_OPTIONAL_GAPS"}
BUY_ACTIONS = {"MOMENTUM BUY", "RECOVERY BUY", "MOMENTUM + RECOVERY BUY"}


@dataclass(frozen=True)
class ExecutionAssumptions:
    starting_capital: float = 100000.0
    slippage_bps: float = 10.0
    transaction_cost_bps: float = 5.0
    whole_shares: bool = True
    entry: str = "NEXT_OFFICIAL_OPEN"
    exit: str = "NEXT_OFFICIAL_OPEN"
    broker_execution: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}_{hashlib.sha256(_json(parts).encode()).hexdigest()[:24]}"


def evidence_hash(row: dict[str, Any]) -> str:
    evidence = row.get("evidence") or (row.get("live_decision") or {}).get("evidence") or {}
    return hashlib.sha256(_json(evidence).encode()).hexdigest()


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def pit_price_bars(bars: Iterable[dict[str, Any]], session: str) -> list[dict[str, Any]]:
    """Return only market observations known at the historical decision cutoff."""
    return [dict(bar) for bar in bars if str(bar.get("date") or "")[:10] <= session]


def pit_filings(filings: Iterable[dict[str, Any]], decision_cutoff: str) -> list[dict[str, Any]]:
    """Reject filings whose effective availability timestamp is after the cutoff."""
    return [
        dict(filing)
        for filing in filings
        if str(filing.get("effective_availability_ts") or "") <= decision_cutoff
    ]


def pit_valuation_observations(observations: Iterable[dict[str, Any]], session: str) -> list[dict[str, Any]]:
    """Historical valuation references may contain only earlier observations."""
    return [dict(row) for row in observations if str(row.get("session") or "") < session]


def freeze_point_in_time_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    """Detach a historical decision snapshot from mutable current evidence."""
    frozen = json.loads(_json(value))
    frozen["snapshot_sha256"] = hashlib.sha256(_json(frozen).encode()).hexdigest()
    return frozen


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args: Any) -> bool | None:
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, timeout=30, isolation_level=None, factory=_ClosingConnection)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    con.execute("pragma journal_mode=WAL")
    con.execute("pragma synchronous=FULL")
    migrate(con)
    return con


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "select 1 from sqlite_master where type='table' and name=?", (name,)
    ).fetchone() is not None


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f"pragma table_info({table})")}


def migrate(con: sqlite3.Connection) -> None:
    """Upgrade in place and fail closed on ambiguous financial duplicates."""
    try:
        con.executescript(
            """
        begin immediate;
        create table if not exists validation_schema_meta_v2 (
          key text primary key, value text not null
        );
        create table if not exists paper_v2_portfolios (
          portfolio_id text primary key, created_at text not null, status text not null,
          starting_capital real not null, starting_session text not null,
          starting_run_id text not null, app_version text not null,
          production_model_version text not null, evidence_pipeline_version text not null,
          router_sha256 text not null, state_json text not null
        );
        create table if not exists paper_v2_positions (
          position_id text primary key, portfolio_id text not null, symbol text not null,
          state text not null, qty integer not null, entry_price real not null,
          position_json text not null,
          foreign key(portfolio_id) references paper_v2_portfolios(portfolio_id)
        );
        create index if not exists paper_v2_positions_lookup
          on paper_v2_positions(portfolio_id,symbol,state);
        create table if not exists paper_v2_orders (
          order_id text primary key, portfolio_id text not null, symbol text not null,
          side text not null, state text not null, signal_session text not null,
          fill_session text, reserved_capital real not null default 0, eligible_session text,
          order_json text not null,
          foreign key(portfolio_id) references paper_v2_portfolios(portfolio_id)
        );
        create index if not exists paper_v2_orders_lookup
          on paper_v2_orders(portfolio_id,state,signal_session);
        create table if not exists paper_v2_journal (
          event_id text primary key, portfolio_id text not null, market_session text not null,
          production_run_id text not null, event_type text not null,
          idempotency_key text not null unique, created_at text not null, event_json text not null,
          foreign key(portfolio_id) references paper_v2_portfolios(portfolio_id)
        );
        create table if not exists paper_v2_nav (
          portfolio_id text not null, market_session text not null, nav_json text not null,
          primary key(portfolio_id,market_session),
          foreign key(portfolio_id) references paper_v2_portfolios(portfolio_id)
        );
        create table if not exists paper_v2_session_commits (
          portfolio_id text not null, market_session text not null, production_run_id text not null,
          result_json text not null, committed_at text not null,
          primary key(portfolio_id,market_session),
          foreign key(portfolio_id) references paper_v2_portfolios(portfolio_id)
        );
        create table if not exists paper_v2_fills (
          order_id text primary key, portfolio_id text not null, fill_session text not null,
          fill_json text not null, created_at text not null,
          foreign key(order_id) references paper_v2_orders(order_id),
          foreign key(portfolio_id) references paper_v2_portfolios(portfolio_id)
        );
        create table if not exists paper_v2_migrations (
          source_schema text not null, source_portfolio_id text not null,
          target_portfolio_id text not null, source_fingerprint text not null,
          result_json text not null, migrated_at text not null,
          primary key(source_schema,source_portfolio_id),
          foreign key(target_portfolio_id) references paper_v2_portfolios(portfolio_id)
        );
        create table if not exists replay_v2_runs (
          replay_id text primary key, created_at text not null, config_json text not null,
          result_json text not null
        );
        create table if not exists replay_v2_sessions (
          replay_id text not null, market_session text not null, replayability text not null,
          coverage_json text not null, session_json text,
          primary key(replay_id,market_session)
        );
            """
        )
        if "eligible_session" not in _columns(con, "paper_v2_orders"):
            con.execute("alter table paper_v2_orders add column eligible_session text")

        active_count = int(con.execute(
            "select count(*) from paper_v2_portfolios where status='ACTIVE'"
        ).fetchone()[0])
        if active_count > 1:
            raise RuntimeError("PAPER_V2_MIGRATION_BLOCKED_MULTIPLE_ACTIVE_PORTFOLIOS")

        duplicate_origins = con.execute(
            "select portfolio_id,signal_session,symbol,side,count(*) from paper_v2_orders "
            "group by portfolio_id,signal_session,symbol,side having count(*)>1"
        ).fetchall()
        if duplicate_origins:
            raise RuntimeError("PAPER_V2_MIGRATION_BLOCKED_AMBIGUOUS_ORDER_DUPLICATES")

        con.execute(
            "create unique index if not exists paper_v2_one_active "
            "on paper_v2_portfolios(status) where status='ACTIVE'"
        )
        con.execute(
            "create unique index if not exists paper_v2_order_origin "
            "on paper_v2_orders(portfolio_id,signal_session,symbol,side)"
        )
        con.execute(
            "insert into validation_schema_meta_v2(key,value) values('schema_version',?) "
            "on conflict(key) do update set value=excluded.value",
            (str(SCHEMA_VERSION),),
        )
        con.commit()
    except Exception:
        con.rollback()
        raise


def legacy_portfolios(db_path: Path) -> list[dict[str, Any]]:
    with _connect(db_path) as con:
        exists = con.execute(
            "select 1 from sqlite_master where type='table' and name='paper_portfolios'"
        ).fetchone()
        if not exists:
            return []
        return [
            {
                "portfolio_id": row[0],
                "created_at": row[1],
                "starting_session": row[2],
                "starting_capital": row[3],
                "classification": "LEGACY_VALIDATION_V1",
                "read_only": True,
                "excluded_from_v2_performance": True,
            }
            for row in con.execute(
                "select portfolio_id,created_at,starting_session,starting_capital "
                "from paper_portfolios order by created_at desc"
            )
        ]


def ensure_legacy_continuity(
    db_path: Path,
    *,
    app_version: str,
    production_model_version: str,
    evidence_pipeline_version: str,
    router_sha256: str,
) -> dict[str, Any]:
    """Promote one unambiguous active V1 prospective ledger into V2 exactly once."""
    with _connect(db_path) as con:
        con.execute("begin immediate")
        try:
            current = con.execute(
                "select portfolio_id from paper_v2_portfolios where status='ACTIVE'"
            ).fetchone()
            if current:
                con.rollback()
                return {"status": "V2_ALREADY_ACTIVE", "portfolio_id": current[0], "migrated": False}
            if not _table_exists(con, "paper_portfolios"):
                con.rollback()
                return {"status": "NO_LEGACY_PORTFOLIO", "migrated": False}

            legacy_rows = con.execute(
                "select portfolio_id,created_at,starting_session,starting_capital,state_json "
                "from paper_portfolios order by created_at"
            ).fetchall()
            candidates: list[tuple[sqlite3.Row, dict[str, Any]]] = []
            for row in legacy_rows:
                try:
                    state = json.loads(row["state_json"])
                except Exception as error:
                    raise RuntimeError("LEGACY_CONTINUITY_BLOCKED_INVALID_PORTFOLIO_STATE") from error
                if str(state.get("status") or "ACTIVE").upper() == "ACTIVE":
                    candidates.append((row, state))
            if not candidates:
                con.rollback()
                return {"status": "NO_ACTIVE_LEGACY_PORTFOLIO", "migrated": False}
            if len(candidates) != 1:
                raise RuntimeError("LEGACY_CONTINUITY_BLOCKED_MULTIPLE_ACTIVE_PORTFOLIOS")

            source, legacy_state = candidates[0]
            source_id = str(source["portfolio_id"])
            prior = con.execute(
                "select target_portfolio_id,result_json from paper_v2_migrations "
                "where source_schema='LEGACY_VALIDATION_V1' and source_portfolio_id=?",
                (source_id,),
            ).fetchone()
            if prior:
                con.rollback()
                return {**json.loads(prior["result_json"]), "migrated": False, "repeat": True}

            def source_rows(table: str, json_column: str) -> list[tuple[sqlite3.Row, dict[str, Any]]]:
                if not _table_exists(con, table):
                    return []
                rows = con.execute(
                    f"select * from {table} where portfolio_id=? order by rowid", (source_id,)
                ).fetchall()
                result = []
                for row in rows:
                    try:
                        result.append((row, json.loads(row[json_column])))
                    except Exception as error:
                        raise RuntimeError(f"LEGACY_CONTINUITY_BLOCKED_INVALID_{table.upper()}_JSON") from error
                return result

            positions = source_rows("paper_positions", "state_json")
            orders = source_rows("paper_orders", "order_json")
            journal = source_rows("paper_journal", "event_json")
            nav_rows = source_rows("paper_nav", "nav_json")
            fingerprint_input = {
                "portfolio": dict(source),
                "positions": [dict(row) for row, _ in positions],
                "orders": [dict(row) for row, _ in orders],
                "journal": [dict(row) for row, _ in journal],
                "nav": [dict(row) for row, _ in nav_rows],
            }
            source_fingerprint = hashlib.sha256(_json(fingerprint_input).encode()).hexdigest()

            open_positions = [
                item for _, item in positions if str(item.get("state") or "").upper() != "CLOSED"
            ]
            invested = round(sum(
                int(item.get("qty") or 0)
                * float(item.get("last_price") or item.get("current_mark_price") or item.get("entry_price") or 0)
                for item in open_positions
            ), 2)
            cash = round(float(legacy_state.get("cash") or 0), 2)
            calculated_nav = round(cash + invested, 2)
            legacy_nav = round(float(legacy_state.get("nav") if legacy_state.get("nav") is not None else calculated_nav), 2)
            if abs(legacy_nav - calculated_nav) > 0.02:
                raise RuntimeError("LEGACY_CONTINUITY_BLOCKED_ECONOMIC_STATE_MISMATCH")
            target_state = {
                "portfolio_id": source_id,
                "created_at": str(source["created_at"]),
                "status": "ACTIVE",
                "starting_capital": round(float(source["starting_capital"]), 2),
                "cash": cash,
                "nav": legacy_nav,
                "invested_value": invested,
                "realized_pnl": round(float(legacy_state.get("realized_pnl") or 0), 2),
                "unrealized_pnl": round(float(legacy_state.get("unrealized_pnl") or 0), 2),
                "exposure": round(invested / legacy_nav, 6) if legacy_nav else 0.0,
                "valuation_quality": "LEGACY_OFFICIAL_MARKS_PRESERVED",
                "source_schema": "LEGACY_VALIDATION_V1",
                "source_portfolio_id": source_id,
                "source_fingerprint": source_fingerprint,
                "continuity_migrated_at": _now(),
            }
            earliest_run = next(
                (str(item.get("production_run_id")) for _, item in journal if item.get("production_run_id")),
                "LEGACY_CONTINUITY",
            )
            con.execute(
                "insert into paper_v2_portfolios "
                "(portfolio_id,created_at,status,starting_capital,starting_session,starting_run_id,app_version,production_model_version,evidence_pipeline_version,router_sha256,state_json) "
                "values(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    source_id, source["created_at"], "ACTIVE", target_state["starting_capital"],
                    source["starting_session"], earliest_run, app_version, production_model_version,
                    evidence_pipeline_version, router_sha256, _json(target_state),
                ),
            )

            for row, original in positions:
                mapped = dict(original)
                mapped.update(
                    source_schema="LEGACY_VALIDATION_V1",
                    source_position_id=row["position_id"],
                    entry_signal_session=original.get("entry_signal_session") or original.get("entry_signal_date"),
                    entry_fill_session=original.get("entry_fill_session") or original.get("entry_fill_date"),
                    current_mark_price=original.get("current_mark_price") or original.get("last_price") or original.get("entry_price"),
                    current_mark_session=original.get("current_mark_session") or original.get("last_valuation_session"),
                )
                state_name = str(original.get("state") or row["state"] or "HOLD").upper()
                if state_name == "HELD":
                    state_name = "HOLD"
                mapped["state"] = state_name
                con.execute(
                    "insert into paper_v2_positions(position_id,portfolio_id,symbol,state,qty,entry_price,position_json) values(?,?,?,?,?,?,?)",
                    (row["position_id"], source_id, row["symbol"], state_name, row["qty"], row["entry_price"], _json(mapped)),
                )

            for row, original in orders:
                mapped = dict(original)
                mapped.update(source_schema="LEGACY_VALIDATION_V1", source_order_id=row["order_id"])
                allocation = original.get("allocation") or {}
                pending = str(row["state"]).upper().startswith("PENDING")
                reserved = float(allocation.get("capital") or allocation.get("estimated_cost") or 0) if pending and str(row["side"]).upper() == "BUY" else 0.0
                eligible = original.get("eligible_session") or original.get("expected_execution_session")
                mapped["reserved_capital"] = round(reserved, 2)
                mapped["eligible_session"] = eligible
                con.execute(
                    "insert into paper_v2_orders(order_id,portfolio_id,symbol,side,state,signal_session,fill_session,reserved_capital,eligible_session,order_json) "
                    "values(?,?,?,?,?,?,?,?,?,?)",
                    (row["order_id"], source_id, row["symbol"], row["side"], row["state"], row["signal_session"], row["fill_session"], round(reserved, 2), eligible, _json(mapped)),
                )
                fill = original.get("fill")
                if fill and row["fill_session"]:
                    con.execute(
                        "insert into paper_v2_fills(order_id,portfolio_id,fill_session,fill_json,created_at) values(?,?,?,?,?)",
                        (row["order_id"], source_id, row["fill_session"], _json({**fill, "source_schema": "LEGACY_VALIDATION_V1"}), _now()),
                    )

            canonical_sessions: set[str] = set()
            for row, original in sorted(journal, key=lambda item: str(item[1].get("created_at") or "")):
                source_event_id = str(row["event_id"])
                session = str(row["market_session"] or source["starting_session"])
                source_type = str(row["event_type"] or original.get("event_type") or "EVENT")
                imported = {
                    **original,
                    "source_schema": "LEGACY_VALIDATION_V1",
                    "source_event_id": source_event_id,
                    "event_type": f"LEGACY {source_type}",
                }
                event_id = stable_id("SREV2LEG", source_id, source_event_id)
                key = f"LEGACY_VALIDATION_V1|{source_id}|{source_event_id}"
                con.execute(
                    "insert into paper_v2_journal(event_id,portfolio_id,market_session,production_run_id,event_type,idempotency_key,created_at,event_json) "
                    "values(?,?,?,?,?,?,?,?)",
                    (event_id, source_id, session, str(row["production_run_id"] or "LEGACY_UNKNOWN_RUN"), imported["event_type"], key, row["created_at"], _json({**imported, "event_id": event_id, "portfolio_id": source_id})),
                )
                if source_type in {"DAILY_DECISION", "SIGNAL_GENERATED"} and session not in canonical_sessions:
                    canonical_sessions.add(session)
                    result = {
                        "status": "MIGRATED_LEGACY_DECISION",
                        "recorded": True,
                        "duplicate": False,
                        "market_session": session,
                        "production_run_id": str(row["production_run_id"] or "LEGACY_UNKNOWN_RUN"),
                        "source_event_id": source_event_id,
                        "source_schema": "LEGACY_VALIDATION_V1",
                    }
                    con.execute(
                        "insert into paper_v2_session_commits(portfolio_id,market_session,production_run_id,result_json,committed_at) values(?,?,?,?,?)",
                        (source_id, session, result["production_run_id"], _json(result), str(row["created_at"] or _now())),
                    )

            for row, original in nav_rows:
                session = str(row["market_session"])
                nav = {**original, "source_schema": "LEGACY_VALIDATION_V1"}
                con.execute(
                    "insert into paper_v2_nav(portfolio_id,market_session,nav_json) values(?,?,?) "
                    "on conflict(portfolio_id,market_session) do nothing",
                    (source_id, session, _json(nav)),
                )
            if not nav_rows:
                con.execute(
                    "insert into paper_v2_nav(portfolio_id,market_session,nav_json) values(?,?,?)",
                    (source_id, str(source["starting_session"]), _json({"market_session": source["starting_session"], **target_state})),
                )

            result = {
                "status": "LEGACY_CONTINUITY_MIGRATED",
                "migrated": True,
                "source_schema": "LEGACY_VALIDATION_V1",
                "source_portfolio_id": source_id,
                "portfolio_id": source_id,
                "source_fingerprint": source_fingerprint,
                "positions": len(positions),
                "pending_orders": sum(str(row["state"]).upper().startswith("PENDING") for row, _ in orders),
                "orders": len(orders),
                "decisions": len(canonical_sessions),
                "journal_rows": len(journal),
                "snapshots": len(nav_rows),
                "starting_capital": target_state["starting_capital"],
                "cash": cash,
                "nav": legacy_nav,
            }
            con.execute(
                "insert into paper_v2_migrations(source_schema,source_portfolio_id,target_portfolio_id,source_fingerprint,result_json,migrated_at) values(?,?,?,?,?,?)",
                ("LEGACY_VALIDATION_V1", source_id, source_id, source_fingerprint, _json(result), _now()),
            )
            con.commit()
            return result
        except Exception:
            con.rollback()
            raise


def create_portfolio(
    db_path: Path,
    *,
    starting_session: str,
    starting_run_id: str,
    starting_capital: float = 100000.0,
    app_version: str,
    production_model_version: str,
    evidence_pipeline_version: str,
    router_sha256: str,
) -> dict[str, Any]:
    if not starting_session or not starting_run_id:
        raise ValueError("CURRENT_ACCEPTED_PRODUCTION_RUN_REQUIRED")
    if not math.isfinite(float(starting_capital)) or float(starting_capital) <= 0:
        raise ValueError("STARTING_CAPITAL_MUST_BE_POSITIVE")
    created = _now()
    portfolio_id = stable_id("SREVP2", created, uuid.uuid4().hex, starting_run_id)
    state = {
        "portfolio_id": portfolio_id,
        "created_at": created,
        "status": "ACTIVE",
        "starting_capital": round(float(starting_capital), 2),
        "cash": round(float(starting_capital), 2),
        "nav": round(float(starting_capital), 2),
        "invested_value": 0.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "exposure": 0.0,
        "valuation_quality": "CURRENT_OFFICIAL_MARKS",
    }
    with _connect(db_path) as con:
        con.execute("begin immediate")
        try:
            existing = con.execute(
                "select portfolio_id from paper_v2_portfolios where status='ACTIVE'"
            ).fetchone()
            if existing:
                con.rollback()
                return load_portfolio(db_path, existing[0])
            con.execute(
                "insert into paper_v2_portfolios values(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    portfolio_id, created, "ACTIVE", state["starting_capital"], starting_session,
                    starting_run_id, app_version, production_model_version,
                    evidence_pipeline_version, router_sha256, _json(state),
                ),
            )
            con.execute(
                "insert into paper_v2_nav values(?,?,?)",
                (portfolio_id, starting_session, _json({"market_session": starting_session, **state})),
            )
            con.commit()
        except Exception:
            con.rollback()
            raise
    return load_portfolio(db_path, portfolio_id)


def _portfolio_row(con: sqlite3.Connection, portfolio_id: str) -> sqlite3.Row:
    row = con.execute("select * from paper_v2_portfolios where portfolio_id=?", (portfolio_id,)).fetchone()
    if not row:
        raise ValueError("PAPER_V2_PORTFOLIO_NOT_FOUND")
    return row


def _loads_rows(rows: Iterable[sqlite3.Row], column: str) -> list[dict[str, Any]]:
    return [json.loads(row[column]) for row in rows]


def list_portfolios(db_path: Path) -> list[dict[str, Any]]:
    with _connect(db_path) as con:
        return [
            {
                "portfolio_id": row["portfolio_id"], "created_at": row["created_at"],
                "status": row["status"], "starting_capital": row["starting_capital"],
                "starting_session": row["starting_session"], "starting_run_id": row["starting_run_id"],
                "app_version": row["app_version"], "production_model_version": row["production_model_version"],
                "evidence_pipeline_version": row["evidence_pipeline_version"],
            }
            for row in con.execute("select * from paper_v2_portfolios order by created_at desc")
        ]


def load_portfolio(db_path: Path, portfolio_id: str | None = None) -> dict[str, Any]:
    with _connect(db_path) as con:
        if portfolio_id is None:
            found = con.execute("select portfolio_id from paper_v2_portfolios where status='ACTIVE'").fetchone()
            if not found:
                return {
                    "active": False,
                    "schema": "SRE_PAPER_PORTFOLIO_V2",
                    "starting_capital": 100000.0,
                    "portfolios": list_portfolios(db_path),
                    "legacy_portfolios": legacy_portfolios(db_path),
                }
            portfolio_id = found[0]
        row = _portfolio_row(con, portfolio_id)
        state = json.loads(row["state_json"])
        positions = _loads_rows(
            con.execute("select position_json from paper_v2_positions where portfolio_id=? order by symbol,position_id", (portfolio_id,)),
            "position_json",
        )
        pending = _loads_rows(
            con.execute("select order_json from paper_v2_orders where portfolio_id=? and state like 'PENDING%' order by signal_session,symbol", (portfolio_id,)),
            "order_json",
        )
        journal = _loads_rows(
            con.execute("select event_json from paper_v2_journal where portfolio_id=? order by created_at desc,event_id desc limit 500", (portfolio_id,)),
            "event_json",
        )
        nav = _loads_rows(
            con.execute("select nav_json from paper_v2_nav where portfolio_id=? order by market_session", (portfolio_id,)),
            "nav_json",
        )
        fills = _loads_rows(
            con.execute("select fill_json from paper_v2_fills where portfolio_id=? order by fill_session,order_id", (portfolio_id,)),
            "fill_json",
        )
        migration = con.execute(
            "select result_json from paper_v2_migrations where target_portfolio_id=? order by migrated_at desc limit 1",
            (portfolio_id,),
        ).fetchone()
        pending_capital = round(sum(float(x.get("reserved_capital") or 0) for x in pending if x.get("side") == "BUY"), 2)
        return {
            **state,
            "schema": "SRE_PAPER_PORTFOLIO_V2",
            "active": row["status"] == "ACTIVE",
            "read_only": row["status"] != "ACTIVE",
            "starting_session": row["starting_session"],
            "starting_run_id": row["starting_run_id"],
            "app_version": row["app_version"],
            "production_model_version": row["production_model_version"],
            "evidence_pipeline_version": row["evidence_pipeline_version"],
            "router_sha256": row["router_sha256"],
            "positions": positions,
            "pending_orders": pending,
            "pending_capital": pending_capital,
            "journal": journal,
            "nav_history": nav,
            "fills": fills,
            "last_processed_session": nav[-1].get("market_session") if nav else None,
            "continuity": json.loads(migration[0]) if migration else {"status": "NATIVE_V2"},
            "portfolios": list_portfolios(db_path),
            "legacy_portfolios": legacy_portfolios(db_path),
        }


def _event(
    con: sqlite3.Connection,
    *,
    portfolio_id: str,
    session: str,
    run_id: str,
    event_type: str,
    symbol: str = "PORTFOLIO",
    identity: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    key = f"{portfolio_id}|{session}|{event_type}|{symbol}|{identity}"
    event = {
        "schema": "SRE_PAPER_JOURNAL_V2",
        "event_id": stable_id("SREV2", key),
        "portfolio_id": portfolio_id,
        "market_session": session,
        "production_run_id": run_id,
        "event_type": event_type,
        "symbol": symbol,
        "created_at": _now(),
        **(payload or {}),
    }
    con.execute(
        "insert or ignore into paper_v2_journal(event_id,portfolio_id,market_session,production_run_id,event_type,idempotency_key,created_at,event_json) values(?,?,?,?,?,?,?,?)",
        (event["event_id"], portfolio_id, session, run_id, event_type, key, event["created_at"], _json(event)),
    )
    saved = con.execute("select event_json from paper_v2_journal where idempotency_key=?", (key,)).fetchone()
    return json.loads(saved[0])


def _fill_terms(open_price: float, side: str, assumptions: ExecutionAssumptions) -> dict[str, float]:
    price = float(open_price)
    slip = price * assumptions.slippage_bps / 10000.0
    fill = price + slip if side == "BUY" else price - slip
    cost = price * assumptions.transaction_cost_bps / 10000.0
    return {
        "official_open": round(price, 6),
        "simulated_fill_price": round(fill, 6),
        "transaction_cost_per_share": round(cost, 6),
        "net_price": round(fill + cost if side == "BUY" else fill - cost, 6),
    }


def _revalue(con: sqlite3.Connection, portfolio_id: str, state: dict[str, Any], session: str) -> None:
    positions = _loads_rows(
        con.execute("select position_json from paper_v2_positions where portfolio_id=? and state!='CLOSED'", (portfolio_id,)),
        "position_json",
    )
    invested = sum(int(p["qty"]) * float(p.get("current_mark_price") or p["entry_price"]) for p in positions)
    unrealized = sum(float(p.get("unrealized_pnl") or 0) for p in positions)
    current = all(p.get("current_mark_session") == session for p in positions)
    state.update(
        invested_value=round(invested, 2),
        unrealized_pnl=round(unrealized, 2),
        nav=round(float(state["cash"]) + invested, 2),
        valuation_quality="CURRENT_OFFICIAL_MARKS" if current else "STALE_MARK",
    )
    state["exposure"] = round(invested / state["nav"], 6) if state["nav"] else 0.0


def process_paper_session(
    db_path: Path,
    *,
    portfolio_id: str,
    expected_session: str,
    latest_official_session: str,
    official_freshness: str,
    production_session: str,
    production_run_id: str,
    app_version: str,
    production_model_version: str,
    evidence_pipeline_version: str,
    candidates: list[dict[str, Any]],
    allocation_plan: dict[str, Any],
    official_opens: dict[str, float],
    official_closes: dict[str, float],
    available_sessions: list[str] | None = None,
    official_opens_by_session: dict[str, dict[str, float]] | None = None,
    monitoring: dict[str, dict[str, Any]] | None = None,
    assumptions: ExecutionAssumptions | None = None,
    crash_hook: str | None = None,
) -> dict[str, Any]:
    assumptions = assumptions or ExecutionAssumptions()
    if latest_official_session != expected_session or official_freshness != "PASS":
        return {"status": "NO PAPER ACTION — OFFICIAL DATA NOT READY", "recorded": False}
    decision_ready = production_session == expected_session and bool(production_run_id)
    monitoring = monitoring or {}
    available_sessions = sorted(set(available_sessions or [expected_session]))
    official_opens_by_session = dict(official_opens_by_session or {})
    official_opens_by_session.setdefault(expected_session, dict(official_opens))
    with _connect(db_path) as con:
        con.execute("begin immediate")
        try:
            portfolio = _portfolio_row(con, portfolio_id)
            if portfolio["status"] != "ACTIVE":
                raise ValueError("PAPER_V2_PORTFOLIO_IS_READ_ONLY")
            existing_commit = con.execute(
                "select result_json from paper_v2_session_commits where portfolio_id=? and market_session=?",
                (portfolio_id, expected_session),
            ).fetchone()
            existing_result = json.loads(existing_commit[0]) if existing_commit else None
            state = json.loads(portfolio["state_json"])
            event_chain = ["SESSION_RESOLVED", "OFFICIAL_DATA_READY", "PORTFOLIO_LOADED", "PORTFOLIO_SCHEMA_READY", "LEGACY_CONTINUITY_CHECKED", "PENDING_ORDER_SCAN"]
            fills: list[dict[str, Any]] = []
            orders = con.execute(
                "select * from paper_v2_orders where portfolio_id=? and state like 'PENDING%' order by signal_session,order_id",
                (portfolio_id,),
            ).fetchall()
            for stored in orders:
                order = json.loads(stored["order_json"])
                future = [session for session in available_sessions if session > order["signal_session"]]
                eligible_session = str(stored["eligible_session"] or order.get("eligible_session") or (future[0] if future else ""))
                if not eligible_session or eligible_session > expected_session:
                    continue
                if not stored["eligible_session"]:
                    order["eligible_session"] = eligible_session
                    con.execute(
                        "update paper_v2_orders set eligible_session=?,order_json=? where order_id=?",
                        (eligible_session, _json(order), order["order_id"]),
                    )
                open_price = _finite((official_opens_by_session.get(eligible_session) or {}).get(order["symbol"]))
                if open_price is None or open_price <= 0:
                    _event(
                        con, portfolio_id=portfolio_id, session=expected_session,
                        run_id=production_run_id or "NO_CURRENT_RUN", event_type="EXECUTION BLOCKED",
                        symbol=order["symbol"], identity=order["order_id"],
                        payload={"order_id": order["order_id"], "eligible_session": eligible_session, "reason": "MISSING_OFFICIAL_OPEN"},
                    )
                    continue
                terms = _fill_terms(open_price, order["side"], assumptions)
                if order["side"] == "BUY":
                    budget = min(float(state["cash"]), float(order["reserved_capital"]))
                    qty = int(budget // terms["net_price"])
                    if qty <= 0:
                        continue
                    total = round(qty * terms["net_price"], 2)
                    state["cash"] = round(float(state["cash"]) - total, 2)
                    position = {
                        "position_id": stable_id("SREVP2POS", portfolio_id, order["symbol"], order["order_id"]),
                        "portfolio_id": portfolio_id, "symbol": order["symbol"], "qty": qty, "state": "HOLD",
                        "entry_signal_session": order["signal_session"], "entry_fill_session": eligible_session,
                        "entry_price": terms["net_price"], "current_mark_session": eligible_session,
                        "current_mark_price": terms["net_price"], "current_state": "HOLD",
                        "current_thesis_health": "ENTRY", "unrealized_pnl": 0.0,
                        "strategy": order.get("strategy"), "confidence": order.get("confidence"),
                        "thesis_snapshot": order.get("thesis_snapshot"), "evidence_hash": order.get("evidence_hash"),
                    }
                    con.execute(
                        "insert into paper_v2_positions(position_id,portfolio_id,symbol,state,qty,entry_price,position_json) values(?,?,?,?,?,?,?)",
                        (position["position_id"], portfolio_id, position["symbol"], "HOLD", qty, position["entry_price"], _json(position)),
                    )
                    event_type = "BUY FILLED"
                    payload = {"order_id": order["order_id"], "signal_session": order["signal_session"], "fill_session": eligible_session, "quantity": qty, "total_cost": total, **terms}
                else:
                    # Bind exits to the monitored holding. Old unbound orders may
                    # execute only when their ticker identifies exactly one holding.
                    position_id = order.get("position_id")
                    matches = con.execute(
                        "select * from paper_v2_positions where portfolio_id=? and symbol=? and state!='CLOSED'"
                        + (" and position_id=?" if position_id else ""),
                        (portfolio_id, order["symbol"], position_id) if position_id else (portfolio_id, order["symbol"]),
                    ).fetchall()
                    if len(matches) != 1:
                        _event(con, portfolio_id=portfolio_id, session=expected_session,
                               run_id=production_run_id or "NO_CURRENT_RUN", event_type="EXECUTION BLOCKED",
                               symbol=order["symbol"], identity=order["order_id"],
                               payload={"order_id": order["order_id"], "position_id": position_id,
                                        "reason": "EXIT_POSITION_IDENTITY_UNRESOLVED"})
                        continue
                    found = matches[0]
                    position = json.loads(found["position_json"])
                    proceeds = round(int(position["qty"]) * terms["net_price"], 2)
                    pnl = round(proceeds - int(position["qty"]) * float(position["entry_price"]), 2)
                    state["cash"] = round(float(state["cash"]) + proceeds, 2)
                    state["realized_pnl"] = round(float(state.get("realized_pnl") or 0) + pnl, 2)
                    position.update(state="CLOSED", current_state="CLOSED", exit_signal_session=order["signal_session"], exit_fill_session=eligible_session, exit_price=terms["net_price"], realized_pnl=pnl)
                    con.execute("update paper_v2_positions set state='CLOSED',position_json=? where position_id=?", (_json(position), found["position_id"]))
                    event_type = "EXIT FILLED"
                    payload = {"order_id": order["order_id"], "signal_session": order["signal_session"], "fill_session": eligible_session, "quantity": position["qty"], "position_id": position["position_id"], "proceeds": proceeds, "realized_pnl": pnl, **terms}
                order.update(state="FILLED", fill_session=eligible_session, fill=terms)
                con.execute(
                    "insert into paper_v2_fills(order_id,portfolio_id,fill_session,fill_json,created_at) values(?,?,?,?,?)",
                    (order["order_id"], portfolio_id, eligible_session, _json({**payload, "side": order["side"], "symbol": order["symbol"]}), _now()),
                )
                con.execute(
                    "update paper_v2_orders set state='FILLED',fill_session=?,reserved_capital=0,order_json=? where order_id=?",
                    (eligible_session, _json(order), order["order_id"]),
                )
                fills.append(_event(con, portfolio_id=portfolio_id, session=eligible_session, run_id=production_run_id or "NO_CURRENT_RUN", event_type=event_type, symbol=order["symbol"], identity=order["order_id"], payload=payload))
                event_chain.append("ORDER_EXECUTED")
            if not fills:
                event_chain.append("NO_PENDING_EXECUTION")
            if crash_hook == "AFTER_FILL_JOURNAL":
                raise RuntimeError("SIMULATED_CRASH_AFTER_FILL_JOURNAL")

            active_positions = con.execute(
                "select * from paper_v2_positions where portfolio_id=? and state!='CLOSED' order by symbol",
                (portfolio_id,),
            ).fetchall()
            pending_exit_rows = con.execute(
                "select order_json from paper_v2_orders where portfolio_id=? and state='PENDING_EXIT_NEXT_OPEN'",
                (portfolio_id,),
            ).fetchall()
            pending_exit_positions = {json.loads(row[0]).get("position_id") for row in pending_exit_rows}
            legacy_pending_symbols = {json.loads(row[0])["symbol"] for row in pending_exit_rows
                                      if not json.loads(row[0]).get("position_id")}
            pending_exit_symbols = {json.loads(row[0])["symbol"] for row in pending_exit_rows}
            monitoring_events = []
            for stored in active_positions:
                position = json.loads(stored["position_json"])
                symbol = position["symbol"]
                mark = _finite(official_closes.get(symbol))
                if mark is not None and mark > 0:
                    position["current_mark_session"] = expected_session
                    position["current_mark_price"] = mark
                    position["unrealized_pnl"] = round(int(position["qty"]) * (mark - float(position["entry_price"])), 2)
                else:
                    position["mark_status"] = "STALE MARK"
                if not decision_ready or existing_commit:
                    con.execute("update paper_v2_positions set position_json=? where position_id=?", (_json(position), stored["position_id"]))
                    continue
                monitor = monitoring.get(position["position_id"]) or monitoring.get(symbol) or {"state": "REVIEW — INSUFFICIENT EVIDENCE", "reason": "Current verified position monitoring is unavailable"}
                monitor_state = str(monitor.get("state") or "REVIEW — INSUFFICIENT EVIDENCE").upper()
                if monitor_state not in {"HOLD", "WEAKENING", "EXIT SIGNAL", "REVIEW — INSUFFICIENT EVIDENCE"}:
                    monitor_state = "REVIEW — INSUFFICIENT EVIDENCE"
                position["current_state"] = monitor_state
                position["current_thesis_health"] = monitor.get("reason") or monitor_state
                if monitor_state == "EXIT SIGNAL" and symbol in pending_exit_symbols and position["position_id"] not in pending_exit_positions:
                    # Existing schema permits one SELL per ticker/session. Defer a
                    # second holding explicitly; never redirect its exit order.
                    monitor_state = "REVIEW — INSUFFICIENT EVIDENCE"
                    position["current_state"] = monitor_state
                    position["current_thesis_health"] = "EXIT_DEFERRED_OTHER_POSITION_ORDER_PENDING"
                db_state = "PENDING_EXIT_NEXT_OPEN" if monitor_state == "EXIT SIGNAL" else monitor_state
                if monitor_state == "EXIT SIGNAL" and position["position_id"] not in pending_exit_positions and symbol not in legacy_pending_symbols:
                    order_id = stable_id("SREVP2ORD", portfolio_id, position["position_id"], expected_session, "SELL")
                    order = {"order_id": order_id, "portfolio_id": portfolio_id, "symbol": symbol, "side": "SELL", "position_id": position["position_id"], "state": "PENDING_EXIT_NEXT_OPEN", "signal_session": expected_session, "production_run_id": production_run_id, "eligible_session": None}
                    con.execute(
                        "insert into paper_v2_orders(order_id,portfolio_id,symbol,side,state,signal_session,fill_session,reserved_capital,eligible_session,order_json) values(?,?,?,?,?,?,?,?,?,?)",
                        (order_id, portfolio_id, symbol, "SELL", order["state"], expected_session, None, 0.0, None, _json(order)),
                    )
                    pending_exit_positions.add(position["position_id"])
                    pending_exit_symbols.add(symbol)
                    monitoring_events.append(_event(con, portfolio_id=portfolio_id, session=expected_session, run_id=production_run_id, event_type="EXIT SIGNAL", symbol=symbol, identity=order_id, payload={"reason": position["current_thesis_health"], "order_id": order_id, "position_id": position["position_id"]}))
                else:
                    monitoring_events.append(_event(con, portfolio_id=portfolio_id, session=expected_session, run_id=production_run_id, event_type=monitor_state, symbol=symbol, identity=position["position_id"], payload={"reason": position["current_thesis_health"], "position_id": position["position_id"]}))
                con.execute("update paper_v2_positions set state=?,position_json=? where position_id=?", (db_state, _json(position), stored["position_id"]))

            held = {row[0] for row in con.execute("select symbol from paper_v2_positions where portfolio_id=? and state!='CLOSED'", (portfolio_id,))}
            pending = {row[0] for row in con.execute("select symbol from paper_v2_orders where portfolio_id=? and state like 'PENDING%'", (portfolio_id,))}
            reserved = float(con.execute("select coalesce(sum(reserved_capital),0) from paper_v2_orders where portfolio_id=? and state='PENDING_NEXT_OPEN'", (portfolio_id,)).fetchone()[0])
            available = max(0.0, float(state["cash"]) - reserved)
            allocations = {str(x.get("symbol") or x.get("ticker") or "").upper(): x for x in allocation_plan.get("new_buys", [])}
            new_orders = []
            decision_candidates = candidates if decision_ready and not existing_commit else []
            for row in decision_candidates:
                live = row.get("live_decision") or row
                symbol = str(row.get("symbol") or row.get("ticker") or "").upper().replace(".NS", "")
                action = str(live.get("final_action") or row.get("final_action") or row.get("opportunity_status") or "").upper()
                if not symbol or action not in BUY_ACTIONS or live.get("executable", row.get("executable")) is not True:
                    continue
                if str(row.get("market_session") or production_session) != expected_session or symbol in held or symbol in pending:
                    continue
                allocation = allocations.get(symbol)
                capital = _finite((allocation or {}).get("estimated_cost") or (allocation or {}).get("capital"))
                if capital is None or capital <= 0 or capital > available + 0.005:
                    continue
                available -= capital
                order_id = stable_id("SREVP2ORD", portfolio_id, symbol, expected_session, "BUY")
                order = {
                    "order_id": order_id, "portfolio_id": portfolio_id, "symbol": symbol, "side": "BUY",
                    "state": "PENDING_NEXT_OPEN", "signal_session": expected_session,
                    "production_run_id": production_run_id, "live_decision_v1_action": action, "eligible_session": None,
                    "strategy": live.get("strategy_style") or row.get("strategy_style"),
                    "confidence": live.get("confidence") or row.get("confidence_label"),
                    "reserved_capital": round(capital, 2), "allocation": allocation,
                    "thesis_snapshot": {"momentum": live.get("momentum_thesis"), "recovery": live.get("recovery_thesis"), "invalidation": live.get("invalidation")},
                    "evidence_snapshot": live.get("evidence") or row.get("evidence") or {},
                    "evidence_hash": evidence_hash(row), "app_version": app_version,
                    "production_model_version": production_model_version,
                    "evidence_pipeline_version": evidence_pipeline_version,
                }
                con.execute(
                    "insert into paper_v2_orders(order_id,portfolio_id,symbol,side,state,signal_session,fill_session,reserved_capital,eligible_session,order_json) values(?,?,?,?,?,?,?,?,?,?)",
                    (order_id, portfolio_id, symbol, "BUY", order["state"], expected_session, None, capital, None, _json(order)),
                )
                new_orders.append(order)
                _event(con, portfolio_id=portfolio_id, session=expected_session, run_id=production_run_id, event_type="BUY SIGNAL", symbol=symbol, identity=order_id, payload={"order_id": order_id, "allocation": allocation, "action": action, "evidence_hash": order["evidence_hash"]})
            if decision_ready and not existing_commit:
                event_chain.append("RECOMMENDATION_CREATED")
                event_chain.append("PORTFOLIO_ACTION_EVALUATED")
                if new_orders:
                    event_chain.append("ORDER_CREATED")
                else:
                    event_chain.append("NO_EXECUTABLE_RECOMMENDATION")
                    _event(
                        con, portfolio_id=portfolio_id, session=expected_session,
                        run_id=production_run_id, event_type="NO EXECUTABLE RECOMMENDATION",
                        payload={"reason": "NO_QUALIFIED_ALLOCATED_ACTION", "recommendations_observed": len(candidates)},
                    )
            elif existing_commit:
                event_chain.append("RECOMMENDATION_REUSED")
            _revalue(con, portfolio_id, state, expected_session)
            con.execute("update paper_v2_portfolios set state_json=? where portfolio_id=?", (_json(state), portfolio_id))
            nav_record = {"market_session": expected_session, "cash": state["cash"], "invested_value": state["invested_value"], "nav": state["nav"], "realized_pnl": state["realized_pnl"], "unrealized_pnl": state["unrealized_pnl"], "valuation_quality": state["valuation_quality"]}
            con.execute(
                "insert into paper_v2_nav(portfolio_id,market_session,nav_json) values(?,?,?) "
                "on conflict(portfolio_id,market_session) do update set nav_json=excluded.nav_json",
                (portfolio_id, expected_session, _json(nav_record)),
            )
            event_chain.extend(["PORTFOLIO_SNAPSHOT_WRITTEN", "DAILY_FLOW_COMPLETE"])
            status = "RECORDED" if decision_ready else "LIFECYCLE_COMPLETE_ANALYSIS_NOT_CURRENT"
            result = {"status": status, "recorded": bool(decision_ready or fills), "duplicate": bool(existing_commit), "decision_reused": bool(existing_commit), "market_session": expected_session, "production_run_id": (existing_result or {}).get("production_run_id") or production_run_id, "lifecycle_run_id": production_run_id, "fills": fills, "monitoring_events": monitoring_events, "new_orders": new_orders, "event_chain": event_chain, **nav_record}
            if decision_ready and not existing_commit:
                con.execute(
                    "insert into paper_v2_session_commits(portfolio_id,market_session,production_run_id,result_json,committed_at) values(?,?,?,?,?)",
                    (portfolio_id, expected_session, production_run_id, _json(result), _now()),
                )
            con.commit()
            return result
        except Exception:
            con.rollback()
            raise


def max_drawdown(values: list[float]) -> float | None:
    if not values:
        return None
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return round(worst, 6)


def _replay_checkpoint_state(completed_sessions, state, coverage, series, benchmark_units,
                             benchmark_complete, buy_signals, filled_entries, exits,
                             cash_streak, longest_cash):
    """State only; caller must persist atomically and authenticate against source versions."""
    from copy import deepcopy
    return deepcopy({
        "completed_sessions": completed_sessions, "state": state, "coverage": coverage,
        "series": series, "benchmark_units": benchmark_units,
        "benchmark_complete": benchmark_complete, "buy_signals": buy_signals,
        "filled_entries": filled_entries, "exits": exits, "cash_streak": cash_streak,
        "longest_cash": longest_cash,
    })


def run_replay(
    *,
    requested_period: str,
    sessions: list[str],
    starting_capital: float,
    assumptions: ExecutionAssumptions,
    session_provider: Callable[[str, dict[str, Any]], dict[str, Any]],
    resume_checkpoint: dict[str, Any] | None = None,
    checkpoint_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    state: dict[str, Any] = {"cash": float(starting_capital), "positions": {}, "pending": [], "trades": [], "realized_pnl": 0.0}
    coverage: list[dict[str, Any]] = []
    series: list[dict[str, Any]] = []
    benchmark_units: float | None = None
    benchmark_complete = True
    buy_signals = filled_entries = exits = cash_streak = longest_cash = 0
    start_index = 0
    if resume_checkpoint is not None:
        ck = resume_checkpoint
        # Only resume at a complete session boundary and with an exact session prefix.
        completed = list(ck.get("completed_sessions", []))
        if not completed or completed != sessions[:len(completed)]:
            raise ValueError("REPLAY_CHECKPOINT_SESSION_PREFIX_MISMATCH")
        if len(completed) > len(sessions):
            raise ValueError("REPLAY_CHECKPOINT_OUT_OF_RANGE")
        state = ck["state"]
        coverage = ck["coverage"]
        series = ck["series"]
        benchmark_units = ck["benchmark_units"]
        benchmark_complete = ck["benchmark_complete"]
        buy_signals = ck["buy_signals"]
        filled_entries = ck["filled_entries"]
        exits = ck["exits"]
        cash_streak = ck["cash_streak"]
        longest_cash = ck["longest_cash"]
        start_index = len(completed)
    for session_index in range(start_index, len(sessions)):
        session = sessions[session_index]
        package = freeze_point_in_time_snapshot(session_provider(session, state))
        replayability = package.get("replayability") or "NOT_REPLAYABLE"
        coverage_row = {
            "date": session,
            "market_data_status": package.get("market_data_status", "MISSING"),
            "fundamental_pit_status": package.get("fundamental_pit_status", "MISSING"),
            "valuation_pit_status": package.get("valuation_pit_status", "MISSING"),
            "universe_status": package.get("universe_status", "CURRENT_UNIVERSE_SURVIVORSHIP_BIAS"),
            "live_decision_v1_run_status": package.get("live_decision_v1_run_status", "NOT_RUN"),
            "replayability": replayability,
        }
        coverage.append(coverage_row)
        if replayability not in PIT_VALID:
            if checkpoint_callback is not None:
                checkpoint_callback(_replay_checkpoint_state(
                    sessions[:session_index + 1], state, coverage, series, benchmark_units,
                    benchmark_complete, buy_signals, filled_entries, exits, cash_streak, longest_cash))
            continue
        opens = package.get("opens") or {}
        closes = package.get("closes") or {}
        remaining = []
        for order in state["pending"]:
            if order["signal_session"] >= session or _finite(opens.get(order["symbol"])) is None:
                remaining.append(order)
                continue
            terms = _fill_terms(float(opens[order["symbol"]]), order["side"], assumptions)
            if order["side"] == "BUY":
                qty = int(min(state["cash"], order["capital"]) // terms["net_price"])
                if qty <= 0:
                    continue
                total = round(qty * terms["net_price"], 2)
                state["cash"] -= total
                state["positions"][order["symbol"]] = {"symbol": order["symbol"], "qty": qty, "entry_price": terms["net_price"], "entry_session": session, "signal_session": order["signal_session"], "last_price": terms["net_price"]}
                filled_entries += 1
            else:
                pos = state["positions"].pop(order["symbol"], None)
                if pos:
                    proceeds = round(pos["qty"] * terms["net_price"], 2)
                    pnl = round(proceeds - pos["qty"] * pos["entry_price"], 2)
                    state["cash"] += proceeds
                    state["realized_pnl"] += pnl
                    state["trades"].append({**pos, "exit_session": session, "exit_price": terms["net_price"], "realized_pnl": pnl, "state": "CLOSED"})
                    exits += 1
        state["pending"] = remaining
        rows = package.get("rows") or []
        by_symbol = {str(r.get("symbol") or "").upper(): r for r in rows}
        pending_symbols = {o["symbol"] for o in state["pending"]}
        for symbol, pos in list(state["positions"].items()):
            mark = _finite(closes.get(symbol))
            if mark is not None:
                pos["last_price"] = mark
            action = str((by_symbol.get(symbol) or {}).get("monitoring_action") or "HOLD").upper()
            if action == "EXIT SIGNAL" and symbol not in pending_symbols:
                state["pending"].append({"symbol": symbol, "side": "SELL", "signal_session": session, "capital": 0})
                pending_symbols.add(symbol)
        plan = package.get("allocation_plan") or {"new_buys": []}
        allocations = {str(x.get("symbol") or "").upper(): x for x in plan.get("new_buys", [])}
        reserved = sum(float(o.get("capital") or 0) for o in state["pending"] if o["side"] == "BUY")
        available = max(0.0, state["cash"] - reserved)
        for row in rows:
            symbol = str(row.get("symbol") or "").upper()
            live = row.get("live_decision") or row
            action = str(live.get("final_action") or row.get("final_action") or "").upper()
            allocation = allocations.get(symbol)
            capital = _finite((allocation or {}).get("estimated_cost") or (allocation or {}).get("capital"))
            if action not in BUY_ACTIONS or live.get("executable", row.get("executable")) is not True or not capital:
                continue
            buy_signals += 1
            if symbol in state["positions"] or symbol in pending_symbols or capital > available + 0.005:
                continue
            state["pending"].append({"symbol": symbol, "side": "BUY", "signal_session": session, "capital": capital})
            pending_symbols.add(symbol)
            available -= capital
        invested = sum(p["qty"] * p["last_price"] for p in state["positions"].values())
        unrealized = sum(p["qty"] * (p["last_price"] - p["entry_price"]) for p in state["positions"].values())
        nav = round(state["cash"] + invested, 2)
        benchmark_close = _finite(package.get("benchmark_close"))
        if benchmark_close is None or benchmark_close <= 0:
            benchmark_complete = False
            benchmark_nav = None
        else:
            if benchmark_units is None:
                benchmark_units = starting_capital / benchmark_close
            benchmark_nav = round(benchmark_units * benchmark_close, 2)
        cash_streak = cash_streak + 1 if not state["positions"] else 0
        longest_cash = max(longest_cash, cash_streak)
        series.append({"date": session, "portfolio_nav": nav, "benchmark_nav": benchmark_nav, "cash": round(state["cash"], 2), "invested_value": round(invested, 2), "realized_pnl": round(state["realized_pnl"], 2), "unrealized_pnl": round(unrealized, 2), "exposure": round(invested / nav, 6) if nav else 0.0})
        if checkpoint_callback is not None:
            checkpoint_callback(_replay_checkpoint_state(
                sessions[:session_index + 1], state, coverage, series, benchmark_units,
                benchmark_complete, buy_signals, filled_entries, exits, cash_streak, longest_cash))
    portfolio_values = [x["portfolio_nav"] for x in series]
    benchmark_values = [x["benchmark_nav"] for x in series if x["benchmark_nav"] is not None]
    portfolio_return = round(portfolio_values[-1] / starting_capital - 1, 6) if portfolio_values else None
    benchmark_return = round(benchmark_values[-1] / starting_capital - 1, 6) if benchmark_complete and benchmark_values else None
    closed = state["trades"]
    wins = [x for x in closed if x["realized_pnl"] > 0]
    replayable_dates = [x["date"] for x in series]
    metrics = {
        "start_nav": starting_capital if series else None,
        "end_nav": portfolio_values[-1] if portfolio_values else None,
        "portfolio_return": portfolio_return,
        "benchmark_return": benchmark_return,
        "excess_return": round(portfolio_return - benchmark_return, 6) if portfolio_return is not None and benchmark_return is not None else None,
        "max_drawdown": max_drawdown(portfolio_values),
        "buy_signals": buy_signals,
        "filled_entries": filled_entries,
        "exits": exits,
        "closed_trades": len(closed),
        "realized_pnl": round(state["realized_pnl"], 2) if series else None,
        "unrealized_pnl": series[-1]["unrealized_pnl"] if series else None,
        "cash": series[-1]["cash"] if series else None,
        "exposure": series[-1]["exposure"] if series else None,
        "win_rate": round(len(wins) / len(closed), 6) if len(closed) >= 3 else None,
        "longest_cash_only_period": longest_cash if series else None,
        "buy_frequency": round(buy_signals / len(series), 6) if series else None,
    }
    return {
        "schema": "SRE_POINT_IN_TIME_HISTORICAL_REPLAY_V2",
        "label": "POINT-IN-TIME HISTORICAL SIMULATION",
        "requested_period": requested_period,
        "requested_range": {"start": sessions[0] if sessions else None, "end": sessions[-1] if sessions else None},
        "trustworthy_replayable_range": {"start": replayable_dates[0] if replayable_dates else None, "end": replayable_dates[-1] if replayable_dates else None},
        "sessions_replayed": len(series),
        "sessions_excluded": len(coverage) - len(series),
        "pit_completeness": "COMPLETE" if coverage and len(series) == len(coverage) else ("PARTIAL" if series else "NOT REPLAYABLE"),
        "survivorship_bias_warning": any(x["universe_status"] == "CURRENT_UNIVERSE_SURVIVORSHIP_BIAS" for x in coverage),
        "execution_assumptions": asdict(assumptions),
        "coverage": coverage,
        "series": series,
        "trades": closed,
        "metrics": metrics,
        "benchmark_status": "ACTUAL_NIFTY_50" if benchmark_complete and series else "NOT AVAILABLE — INCOMPLETE NIFTY 50 HISTORY",
    }


def persist_replay(db_path: Path, result: dict[str, Any], config: dict[str, Any]) -> str:
    replay_id = stable_id("SREVR2", config, result.get("coverage"))
    with _connect(db_path) as con:
        con.execute("begin immediate")
        try:
            con.execute("insert or replace into replay_v2_runs values(?,?,?,?)", (replay_id, _now(), _json(config), _json({**result, "replay_id": replay_id})))
            for row in result.get("coverage", []):
                session = next((x for x in result.get("series", []) if x["date"] == row["date"]), None)
                con.execute("insert or replace into replay_v2_sessions values(?,?,?,?,?)", (replay_id, row["date"], row["replayability"], _json(row), _json(session) if session else None))
            con.commit()
        except Exception:
            con.rollback()
            raise
    return replay_id
