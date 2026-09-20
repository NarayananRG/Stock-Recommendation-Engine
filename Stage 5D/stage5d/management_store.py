from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping

from .ledger import OperationResult, Stage5DLedger, canonical_json, payload_sha256
from .management_policy import SUPPORTED_POLICIES, evaluate_completed_session
from .market_observation import MarketObservation
from .source_contract import canonical_date


STAGE5D3_SCHEMA_VERSION = "STAGE5D3_SCHEMA_V1"
STAGE5D3_TABLES = (
    "stage5d3_meta", "management_session_runs", "management_episodes",
    "daily_market_observations", "management_state_versions",
)


SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS stage5d3_meta(
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version TEXT NOT NULL,
        created_at_utc TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS management_episodes(
        episode_id TEXT PRIMARY KEY, recommendation_id TEXT NOT NULL UNIQUE REFERENCES recommendations(recommendation_id),
        signal_id TEXT NOT NULL, ticker TEXT NOT NULL, management_policy_id TEXT NOT NULL,
        management_policy_source TEXT NOT NULL, management_policy_max_sessions INTEGER NOT NULL,
        original_stop TEXT NOT NULL, original_target_1 TEXT, original_target_2 TEXT NOT NULL,
        first_effective_fill_date TEXT NOT NULL, entry_execution_context_status TEXT NOT NULL,
        created_at_utc TEXT NOT NULL, canonical_payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS daily_market_observations(
        observation_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, session_date TEXT NOT NULL,
        open TEXT NOT NULL, high TEXT NOT NULL, low TEXT NOT NULL, close TEXT NOT NULL,
        daily_supertrend TEXT, swing_low_10 TEXT, source_data_hash TEXT, source_name TEXT,
        canonical_payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL, persisted_at_utc TEXT NOT NULL,
        UNIQUE(ticker,session_date))""",
    """CREATE TABLE IF NOT EXISTS management_session_runs(
        session_run_id TEXT PRIMARY KEY, session_date TEXT NOT NULL UNIQUE,
        managed_episode_count INTEGER NOT NULL, closed_episode_count INTEGER NOT NULL,
        exit_trigger_count INTEGER NOT NULL, stop_revision_count INTEGER NOT NULL,
        hold_count INTEGER NOT NULL, reconciliation_required_count INTEGER NOT NULL,
        canonical_input_json TEXT NOT NULL, canonical_output_json TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL, persisted_at_utc TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS management_state_versions(
        management_state_id TEXT PRIMARY KEY, session_run_id TEXT NOT NULL REFERENCES management_session_runs(session_run_id),
        episode_id TEXT NOT NULL REFERENCES management_episodes(episode_id), recommendation_id TEXT NOT NULL,
        signal_id TEXT NOT NULL, ticker TEXT NOT NULL, session_date TEXT NOT NULL,
        management_policy_id TEXT NOT NULL, managed_quantity INTEGER NOT NULL, bars_held INTEGER NOT NULL,
        effective_stop TEXT NOT NULL, active_target TEXT NOT NULL,
        open TEXT, high TEXT, low TEXT, close TEXT, daily_supertrend TEXT, swing_low_10 TEXT,
        decision TEXT NOT NULL, reason TEXT NOT NULL, exit_triggered INTEGER NOT NULL,
        exit_reason TEXT, reference_trigger_price TEXT, proposed_stop_after_close TEXT,
        next_session_stop TEXT, next_session_effective_rule TEXT, episode_status TEXT NOT NULL,
        observation_id TEXT REFERENCES daily_market_observations(observation_id),
        canonical_payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL, persisted_at_utc TEXT NOT NULL,
        UNIQUE(episode_id,session_date))""",
    "CREATE INDEX IF NOT EXISTS idx_s5d3_states_episode_date ON management_state_versions(episode_id,session_date)",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _id(prefix: str, text: str) -> str:
    return prefix + payload_sha256(text)[:24]


class Stage5D3Manager:
    def __init__(self, ledger: Stage5DLedger):
        self.ledger = ledger
        self.connection = ledger.connection
        self._initialize_or_validate()

    def _initialize_or_validate(self) -> None:
        with self.connection:
            for statement in SCHEMA_STATEMENTS:
                self.connection.execute(statement)
            row = self.connection.execute("SELECT schema_version FROM stage5d3_meta WHERE singleton=1").fetchone()
            if row is None:
                self.connection.execute("INSERT INTO stage5d3_meta VALUES(1,?,?)", (STAGE5D3_SCHEMA_VERSION, _now()))
            elif row[0] != STAGE5D3_SCHEMA_VERSION:
                raise RuntimeError(f"Unsupported Stage 5D.3 schema {row[0]!r}")

    @property
    def schema_version(self) -> str:
        return str(self.connection.execute("SELECT schema_version FROM stage5d3_meta WHERE singleton=1").fetchone()[0])

    def _nonvoid_transactions(self) -> list[sqlite3.Row]:
        return list(self.connection.execute(
            """SELECT t.* FROM user_transactions t WHERE NOT EXISTS
               (SELECT 1 FROM transaction_voids v WHERE v.transaction_id=t.transaction_id)
               ORDER BY t.trade_date,t.transaction_sequence"""
        ))

    def _fill_evidence(self, recommendation_id: str) -> tuple[list[sqlite3.Row], bool]:
        valid: list[sqlite3.Row] = []
        bad = False
        seen: set[str] = set()
        for item in self.ledger._fill_event_lineage(recommendation_id):
            tx = item["transaction"]
            if tx is None:
                bad = True
                continue
            if item["voided"]:
                continue
            if tx["recommendation_id"] != recommendation_id or tx["side"] != "BUY":
                bad = True
                continue
            if tx["transaction_id"] not in seen:
                valid.append(tx); seen.add(tx["transaction_id"])
        return valid, bad

    def _sync_episodes(self) -> None:
        rows = self.connection.execute("SELECT canonical_payload_json FROM recommendations ORDER BY recommendation_id").fetchall()
        for row in rows:
            rec = json.loads(row[0])
            if rec.get("portfolio_action_status") != "ACTIONABLE_BUY" or rec.get("management_policy_id") not in SUPPORTED_POLICIES:
                continue
            fills, bad = self._fill_evidence(str(rec["recommendation_id"]))
            existing = self.connection.execute("SELECT canonical_payload_json,payload_sha256 FROM management_episodes WHERE recommendation_id=?", (rec["recommendation_id"],)).fetchone()
            if existing:
                # An episode's original clock remains immutable even when a later
                # transaction void changes current execution evidence.
                continue
            if bad and not fills:
                fills = list(self.connection.execute(
                    """SELECT t.* FROM user_transactions t WHERE t.recommendation_id=? AND t.side='BUY'
                       AND NOT EXISTS(SELECT 1 FROM transaction_voids v WHERE v.transaction_id=t.transaction_id)
                       ORDER BY t.trade_date,t.transaction_sequence""", (rec["recommendation_id"],)
                ))
            if not fills:
                continue
            first_date = min(str(tx["trade_date"]) for tx in fills)
            payload = {
                "episode_id": _id("S5D3_EP_", str(rec["recommendation_id"])),
                "recommendation_id": rec["recommendation_id"], "signal_id": rec["signal_id"], "ticker": rec["ticker"],
                "management_policy_id": rec["management_policy_id"],
                "management_policy_source": rec.get("management_policy_source") or "UNSPECIFIED",
                "management_policy_max_sessions": int(rec.get("management_policy_max_sessions") or SUPPORTED_POLICIES[rec["management_policy_id"]]),
                "original_stop": rec["stop"], "original_target_1": rec.get("target_1"), "original_target_2": rec["target_2"],
                "first_effective_fill_date": first_date,
                "entry_execution_context_status": "REAL_USER_FILL_ORDER_UNKNOWN",
            }
            canonical = canonical_json(payload); digest = payload_sha256(canonical)
            self.connection.execute(
                "INSERT INTO management_episodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (payload["episode_id"], payload["recommendation_id"], payload["signal_id"], payload["ticker"],
                 payload["management_policy_id"], payload["management_policy_source"], payload["management_policy_max_sessions"],
                 str(payload["original_stop"]), None if payload["original_target_1"] is None else str(payload["original_target_1"]),
                 str(payload["original_target_2"]), first_date, payload["entry_execution_context_status"], _now(), canonical, digest),
            )

    def _episode_quantity_and_issue(self, episode: sqlite3.Row) -> tuple[int, Decimal | None, str | None]:
        rec_id, ticker = str(episode["recommendation_id"]), str(episode["ticker"])
        fills, bad = self._fill_evidence(rec_id)
        if bad:
            return 0, None, "INCONSISTENT_FILL_LINEAGE"
        if not fills:
            return 0, None, "NO_EFFECTIVE_BUY_AFTER_EPISODE_CREATED"
        buys = sum(int(tx["quantity"]) for tx in fills)
        buy_value = sum(Decimal(tx["price_inr"]) * int(tx["quantity"]) for tx in fills)
        transactions = self._nonvoid_transactions()
        linked = [tx for tx in transactions if tx["recommendation_id"] == rec_id]
        if any(tx["ticker"] != ticker or tx["signal_id"] != episode["signal_id"] for tx in linked):
            return 0, None, "INCONSISTENT_TRANSACTION_LINEAGE"
        sells = sum(int(tx["quantity"]) for tx in linked if tx["side"] == "SELL")
        if sells > buys:
            return buys - sells, None, "LINKED_SELL_EXCEEDS_MANAGED_BUY"
        if self.connection.execute("SELECT 1 FROM opening_positions WHERE ticker=? LIMIT 1", (ticker,)).fetchone():
            return buys - sells, None, "OPENING_POSITION_OVERLAP"
        if any(tx["side"] == "SELL" and tx["recommendation_id"] is None and tx["ticker"] == ticker and tx["trade_date"] >= episode["first_effective_fill_date"] for tx in transactions):
            return buys - sells, None, "UNLINKED_SELL_AFTER_MANAGED_ENTRY"
        overlap = self.connection.execute(
            "SELECT COUNT(*) FROM management_episodes WHERE ticker=?", (ticker,)
        ).fetchone()[0]
        if overlap > 1:
            return buys - sells, None, "OVERLAPPING_MANAGED_EPISODES"
        return buys - sells, (buy_value / buys if buys else None), None

    def _persist_observation(self, observation: MarketObservation) -> OperationResult:
        canonical = observation.canonical_payload(); digest = payload_sha256(canonical)
        row = self.connection.execute(
            "SELECT observation_id,canonical_payload_json,payload_sha256 FROM daily_market_observations WHERE ticker=? AND session_date=?",
            (observation.ticker, observation.session_date),
        ).fetchone()
        if row:
            if row[1] != canonical or row[2] != digest:
                raise ValueError(f"Conflicting immutable market observation: {observation.ticker} {observation.session_date}")
            return OperationResult("IDEMPOTENT_SUCCESS", row[0])
        self.connection.execute(
            "INSERT INTO daily_market_observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (observation.observation_id, observation.ticker, observation.session_date,
             str(observation.open), str(observation.high), str(observation.low), str(observation.close),
             None if observation.daily_supertrend is None else str(observation.daily_supertrend),
             None if observation.swing_low_10 is None else str(observation.swing_low_10),
             observation.source_data_hash, observation.source_name, canonical, digest, _now()),
        )
        return OperationResult("CREATED", observation.observation_id)

    def process_completed_session(
        self, session_date: Any, observations: Iterable[Mapping[str, Any] | MarketObservation],
        *, execution_contexts: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        session = canonical_date(session_date, "session_date")
        context = dict(execution_contexts or {})
        parsed = [item if isinstance(item, MarketObservation) else MarketObservation.from_mapping(item) for item in observations]
        if any(item.session_date != session for item in parsed):
            raise ValueError("all observations must match the completed session date")
        by_ticker: dict[str, MarketObservation] = {}
        for item in parsed:
            if item.ticker in by_ticker:
                raise ValueError(f"duplicate observation for {item.ticker}")
            by_ticker[item.ticker] = item
        evidence = [dict(row) for row in self.connection.execute(
            """SELECT t.transaction_id,t.ticker,t.trade_date,t.side,t.quantity,t.price_inr,t.recommendation_id,t.signal_id,
                      EXISTS(SELECT 1 FROM transaction_voids v WHERE v.transaction_id=t.transaction_id) AS voided
               FROM user_transactions t ORDER BY t.transaction_sequence"""
        )]
        canonical_input = canonical_json({"session_date": session, "observations": [item.payload() for item in sorted(parsed, key=lambda x: x.ticker)], "execution_contexts": context, "ledger_evidence": evidence})
        existing = self.connection.execute("SELECT canonical_input_json,canonical_output_json FROM management_session_runs WHERE session_date=?", (session,)).fetchone()
        if existing:
            if existing[0] != canonical_input:
                raise ValueError(f"Conflicting immutable management session run: {session}")
            return json.loads(existing[1]) | {"status": "IDEMPOTENT_SUCCESS"}

        run_id = _id("S5D3_RUN_", session)
        states: list[dict[str, Any]] = []
        with self.connection:
            self._sync_episodes()
            for observation in parsed:
                self._persist_observation(observation)
            episodes = self.connection.execute("SELECT * FROM management_episodes ORDER BY episode_id").fetchall()
            # Reserve the run so state foreign keys remain immediate and atomic.
            self.connection.execute(
                "INSERT INTO management_session_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, session, 0, 0, 0, 0, 0, 0, canonical_input, "{}", "PENDING", _now()),
            )
            for episode in episodes:
                if session < episode["first_effective_fill_date"]:
                    continue
                latest = self.connection.execute("SELECT * FROM management_state_versions WHERE episode_id=? ORDER BY session_date DESC LIMIT 1", (episode["episode_id"],)).fetchone()
                if latest and session < latest["session_date"]:
                    raise ValueError(f"Earlier-session backfill prohibited for episode {episode['episode_id']}")
                quantity, avg_entry, issue = self._episode_quantity_and_issue(episode)
                stop = Decimal(latest["next_session_stop"] or latest["effective_stop"]) if latest else Decimal(episode["original_stop"])
                target = Decimal(episode["original_target_2"])
                bars = (int(latest["bars_held"]) + 1) if latest else 1
                observation = by_ticker.get(episode["ticker"])
                decision = "HOLD"; reason = "HOLD_NO_CHANGE"; exit_reason = None; ref = None; proposed = None; next_stop = None
                episode_status = "ACTIVE"; exit_triggered = 0
                if issue:
                    decision = episode_status = "RECONCILIATION_REQUIRED"; reason = issue
                elif avg_entry is None or Decimal(episode["original_stop"]) >= avg_entry or avg_entry >= target:
                    decision = episode_status = "INVALID_EXECUTION_CONTEXT"; reason = "INVALID_ENTRY_LEVEL_ECONOMICS"
                elif quantity == 0:
                    decision = episode_status = "CLOSED_RECORDED"; reason = "FULL_LINKED_SELL_RECORDED"
                elif latest and bool(latest["exit_triggered"]):
                    decision = "EXIT_OVERDUE_AWAITING_USER_ACTION"; reason = str(latest["exit_reason"]); exit_reason = str(latest["exit_reason"])
                    episode_status = "EXIT_TRIGGERED_AWAITING_USER_ACTION"; exit_triggered = 1; bars = int(latest["bars_held"]) + 1
                else:
                    if observation is None:
                        raise ValueError(f"Missing completed-session observation for managed ticker {episode['ticker']}")
                    prior_date = None if latest is None else str(latest["session_date"])
                    if prior_date is not None and session <= prior_date:
                        raise ValueError(f"Conflicting immutable management state: {episode['episode_id']} {session}")
                    policy = evaluate_completed_session(
                        str(episode["management_policy_id"]), bars, stop, target, observation,
                        is_entry_day=session == episode["first_effective_fill_date"],
                        entry_execution_context=context.get(str(episode["recommendation_id"]), str(episode["entry_execution_context_status"])),
                    )
                    decision, reason, exit_reason, ref = policy.decision, policy.reason, policy.exit_reason, policy.reference_trigger_price
                    proposed, next_stop = policy.proposed_stop_after_close, policy.next_session_stop
                    if exit_reason:
                        exit_triggered = 1; episode_status = "EXIT_TRIGGERED_AWAITING_USER_ACTION"
                state = {
                    "management_state_id": _id("S5D3_STATE_", f"{episode['episode_id']}|{session}"),
                    "episode_id": episode["episode_id"], "recommendation_id": episode["recommendation_id"],
                    "signal_id": episode["signal_id"], "ticker": episode["ticker"], "session_date": session,
                    "management_policy_id": episode["management_policy_id"], "managed_quantity": quantity,
                    "bars_held": bars, "effective_stop": stop, "active_target": target,
                    "open": None if observation is None else observation.open, "high": None if observation is None else observation.high,
                    "low": None if observation is None else observation.low, "close": None if observation is None else observation.close,
                    "daily_supertrend": None if observation is None else observation.daily_supertrend,
                    "swing_low_10": None if observation is None else observation.swing_low_10,
                    "decision": decision, "reason": reason, "exit_triggered": bool(exit_triggered), "exit_reason": exit_reason,
                    "reference_trigger_price": ref, "proposed_stop_after_close": proposed, "next_session_stop": next_stop,
                    "next_session_effective_rule": "NEXT_AVAILABLE_PROCESSED_MARKET_SESSION" if next_stop is not None else None,
                    "episode_status": episode_status,
                    "observation_id": None if observation is None else observation.observation_id,
                }
                canonical = canonical_json(state); digest = payload_sha256(canonical)
                values = [state[key] for key in (
                    "management_state_id","episode_id","recommendation_id","signal_id","ticker","session_date","management_policy_id",
                    "managed_quantity","bars_held","effective_stop","active_target","open","high","low","close","daily_supertrend","swing_low_10",
                    "decision","reason","exit_triggered","exit_reason","reference_trigger_price","proposed_stop_after_close","next_session_stop",
                    "next_session_effective_rule","episode_status","observation_id")]
                values = [str(v) if isinstance(v, Decimal) else int(v) if isinstance(v, bool) else v for v in values]
                columns = (
                    "management_state_id,episode_id,recommendation_id,signal_id,ticker,session_date,management_policy_id,"
                    "managed_quantity,bars_held,effective_stop,active_target,open,high,low,close,daily_supertrend,swing_low_10,"
                    "decision,reason,exit_triggered,exit_reason,reference_trigger_price,proposed_stop_after_close,next_session_stop,"
                    "next_session_effective_rule,episode_status,observation_id,canonical_payload_json,payload_sha256,persisted_at_utc,session_run_id"
                )
                self.connection.execute(
                    f"INSERT INTO management_state_versions({columns}) VALUES(" + ",".join("?" for _ in range(31)) + ")",
                    (*values, canonical, digest, _now(), run_id),
                )
                states.append(state)
            episode_tickers = {str(episode["ticker"]) for episode in episodes}
            unmanaged_positions = [
                {"ticker": position.ticker, "quantity": position.quantity, "status": "UNMANAGED_POSITION"}
                for position in self.ledger.derive_positions(session)
                if position.ticker not in episode_tickers
            ]
            summary = {
                "session_run_id": run_id, "session_date": session, "managed_episode_count": len(states),
                "closed_episode_count": sum(s["decision"] == "CLOSED_RECORDED" for s in states),
                "exit_trigger_count": sum(bool(s["exit_triggered"]) and s["decision"] != "EXIT_OVERDUE_AWAITING_USER_ACTION" for s in states),
                "stop_revision_count": sum(s["decision"] == "RAISE_STOP_NEXT_SESSION" for s in states),
                "hold_count": sum(s["decision"] in {"HOLD", "ENTRY_BAR_EXECUTION_ORDER_UNRESOLVED"} for s in states),
                "reconciliation_required_count": sum(s["decision"] == "RECONCILIATION_REQUIRED" for s in states),
                "states": states, "unmanaged_positions": unmanaged_positions,
            }
            output = canonical_json(summary); digest = payload_sha256(canonical_json({"input": json.loads(canonical_input), "output": summary}))
            self.connection.execute(
                """UPDATE management_session_runs SET managed_episode_count=?,closed_episode_count=?,exit_trigger_count=?,
                   stop_revision_count=?,hold_count=?,reconciliation_required_count=?,canonical_output_json=?,payload_sha256=? WHERE session_run_id=?""",
                (summary["managed_episode_count"], summary["closed_episode_count"], summary["exit_trigger_count"], summary["stop_revision_count"],
                 summary["hold_count"], summary["reconciliation_required_count"], output, digest, run_id),
            )
        return summary | {"status": "CREATED"}

    def states(self, recommendation_id: str | None = None) -> tuple[dict[str, Any], ...]:
        sql = "SELECT canonical_payload_json FROM management_state_versions"
        params: tuple[Any, ...] = ()
        if recommendation_id is not None:
            sql += " WHERE recommendation_id=?"; params = (recommendation_id,)
        sql += " ORDER BY session_date,management_state_id"
        return tuple(json.loads(row[0]) for row in self.connection.execute(sql, params))

    def integrity_check(self, *, parity_artifact: str | Path | None = None) -> dict[str, Any]:
        checks: dict[str, bool] = {}
        checks["sqlite_integrity"] = self.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        checks["foreign_keys"] = not bool(self.connection.execute("PRAGMA foreign_key_check").fetchall())
        for table in ("management_episodes", "daily_market_observations", "management_state_versions"):
            checks[f"{table}_hashes"] = all(payload_sha256(row[0]) == row[1] for row in self.connection.execute(f"SELECT canonical_payload_json,payload_sha256 FROM {table}"))
        run_rows = self.connection.execute("SELECT * FROM management_session_runs").fetchall()
        checks["management_session_run_hashes"] = all(
            row["payload_sha256"] == payload_sha256(canonical_json({"input": json.loads(row["canonical_input_json"]), "output": json.loads(row["canonical_output_json"])}))
            for row in run_rows
        )
        checks["management_session_run_typed_binding"] = all(
            int(row["managed_episode_count"]) == int(json.loads(row["canonical_output_json"])["managed_episode_count"])
            and int(row["closed_episode_count"]) == int(json.loads(row["canonical_output_json"])["closed_episode_count"])
            and int(row["exit_trigger_count"]) == int(json.loads(row["canonical_output_json"])["exit_trigger_count"])
            and int(row["stop_revision_count"]) == int(json.loads(row["canonical_output_json"])["stop_revision_count"])
            and int(row["hold_count"]) == int(json.loads(row["canonical_output_json"])["hold_count"])
            and int(row["reconciliation_required_count"]) == int(json.loads(row["canonical_output_json"])["reconciliation_required_count"])
            for row in run_rows
        )
        typed = True
        for row in self.connection.execute("SELECT * FROM management_episodes"):
            payload = json.loads(row["canonical_payload_json"])
            typed = typed and all(str(row[key]) == str(payload[key]) for key in (
                "episode_id","recommendation_id","signal_id","ticker","management_policy_id","management_policy_source",
                "management_policy_max_sessions","original_stop","original_target_2","first_effective_fill_date","entry_execution_context_status"))
        for row in self.connection.execute("SELECT * FROM daily_market_observations"):
            payload = json.loads(row["canonical_payload_json"])
            typed = typed and all((row[key] is None and payload[key] is None) or str(row[key]) == str(payload[key]) for key in (
                "ticker","session_date","open","high","low","close","daily_supertrend","swing_low_10","source_data_hash","source_name"))
        for row in self.connection.execute("SELECT * FROM management_state_versions"):
            payload = json.loads(row["canonical_payload_json"])
            typed = typed and all((row[key] is None and payload[key] is None) or str(row[key]) == str(payload[key]) for key in (
                "management_state_id","episode_id","recommendation_id","signal_id","ticker","session_date","management_policy_id",
                "managed_quantity","bars_held","effective_stop","active_target","open","high","low","close","daily_supertrend","swing_low_10",
                "decision","reason","exit_reason","reference_trigger_price","proposed_stop_after_close","next_session_stop",
                "next_session_effective_rule","episode_status","observation_id"))
            typed = typed and int(row["exit_triggered"]) == int(bool(payload["exit_triggered"]))
        checks["typed_column_payload_binding"] = typed
        episodes = {row["episode_id"]: row for row in self.connection.execute("SELECT * FROM management_episodes")}
        checks["episode_recommendation_lineage"] = all(
            self.connection.execute("SELECT 1 FROM recommendations WHERE recommendation_id=? AND signal_id=? AND ticker=? AND management_policy_id=?", (e["recommendation_id"],e["signal_id"],e["ticker"],e["management_policy_id"])).fetchone()
            for e in episodes.values()
        )
        chronology = bars = stops = targets = sticky = linkage = True
        for episode_id, episode in episodes.items():
            rows = self.connection.execute("SELECT * FROM management_state_versions WHERE episode_id=? ORDER BY session_date", (episode_id,)).fetchall()
            for index, row in enumerate(rows):
                if index and not (rows[index-1]["session_date"] < row["session_date"]): chronology = False
                if index and int(row["bars_held"]) != int(rows[index-1]["bars_held"]) + 1: bars = False
                if episode["management_policy_id"] == "STATIC_T2_20D" and Decimal(row["effective_stop"]) != Decimal(episode["original_stop"]): stops = False
                if index and episode["management_policy_id"] == "D1_TRAIL_ONLY_63D" and Decimal(row["effective_stop"]) < Decimal(rows[index-1]["effective_stop"]): stops = False
                if Decimal(row["active_target"]) != Decimal(episode["original_target_2"]): targets = False
                if index and rows[index-1]["exit_triggered"] and row["decision"] not in {"EXIT_OVERDUE_AWAITING_USER_ACTION","CLOSED_RECORDED","RECONCILIATION_REQUIRED"}: sticky = False
                if row["observation_id"] and not self.connection.execute("SELECT 1 FROM daily_market_observations WHERE observation_id=? AND ticker=? AND session_date=?", (row["observation_id"],row["ticker"],row["session_date"])).fetchone(): linkage = False
        checks.update({"session_chronology": chronology,"bars_held_monotonic": bars,"policy_stop_rules": stops,"target_original_t2": targets,"sticky_exit": sticky,"state_observation_linkage": linkage})
        quantity_reconciliation = True
        for episode_id, episode in episodes.items():
            latest = self.connection.execute("SELECT * FROM management_state_versions WHERE episode_id=? ORDER BY session_date DESC LIMIT 1", (episode_id,)).fetchone()
            if latest is None:
                continue
            quantity, _, issue = self._episode_quantity_and_issue(episode)
            quantity_reconciliation = quantity_reconciliation and int(latest["managed_quantity"]) == quantity
            if issue:
                quantity_reconciliation = quantity_reconciliation and latest["decision"] == "RECONCILIATION_REQUIRED"
        checks["management_episode_quantity_reconciliation"] = quantity_reconciliation
        checks["source_parity_artifact_available"] = parity_artifact is None or Path(parity_artifact).is_file()
        return {"ok": all(checks.values()), "checks": checks}
