from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

root = Path(os.environ["SRE_ENGINE_ROOT"])


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(label + " patch point missing")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Install V2 module; leave legacy Phase 8.1 implementation intact/read-only.
# SRE_ENGINE_ROOT is the reconstructed engine, while this overlay lives in the
# checked-out repository. Resolve the sibling source from this script, not from
# the reconstructed engine root.
v2_source = Path(__file__).resolve().with_name("validation_v2.py")
if not v2_source.exists():
    raise RuntimeError("Validation V2 source module missing: " + str(v2_source))
shutil.copy2(v2_source, root / "stock_app" / "validation_v2.py")

api = root / "modern_ui" / "api.py"
replace_once(
    api,
    'APP_VERSION = "0.14.11-missing-evidence-coverage-repair"',
    'APP_VERSION = "0.14.12-validation-v2"',
    "release identity",
)

# Keep the accepted 0.14.11 Fundamental V3 implementation byte-for-byte unchanged.
# Replay performance optimizations are deferred until Validation V2 is fully green;
# correctness and PIT semantics take priority over speculative caching.

atext = api.read_text(encoding="utf-8")
anchor = "    def latest_prediction_rows"
if anchor not in atext:
    raise RuntimeError("ApiContext V2 insertion point missing")

methods = r'''    def _validation_v2_db_path(self) -> Path:
        return self.config.app_data_dir / "validation_v2.sqlite3"

    def _validation_v2_index_bars(self) -> list[dict[str, Any]]:
        for symbol in ("INDEX_NSEI", "NSEI", "^NSEI", "NIFTY"):
            try:
                bars = self.prices.history(symbol, limit=5000)
            except Exception:
                bars = []
            if bars:
                return bars
        return []

    def _validation_v2_current_universe(self) -> list[str]:
        source = self.data_source_status()
        members = [str(m.get("symbol") or "").upper().replace(".NS", "") for m in (source.get("active") or {}).get("members", [])]
        members = [x for x in members if x]
        if members:
            return sorted(set(members))
        try:
            return sorted(set(str(x).upper().replace(".NS", "") for x in self.historical._load_histories()))
        except Exception:
            return sorted(set(r.get("symbol") for r in self.latest_prediction_rows(limit=200) if r.get("symbol")))

    def validation_v2_paper_status(self, portfolio_id: str | None = None) -> dict[str, Any]:
        from stock_app.validation_v2 import load_portfolio, list_portfolios
        state = load_portfolio(self._validation_v2_db_path(), portfolio_id)
        state["portfolios"] = list_portfolios(self._validation_v2_db_path())
        state["label"] = "PAPER PORTFOLIO V2 — FORWARD ONLY"
        state["legacy_validation_v1"] = {
            "status": "LEGACY_VALIDATION_V1",
            "read_only": True,
            "excluded_from_v2_performance": True,
        }
        return state

    def validation_v2_start_paper(self, starting_capital: float = 100000.0) -> dict[str, Any]:
        from stock_app.validation_v2 import create_portfolio
        gate = self._daily_data_gate()
        run = self.ui_run_input() or {}
        session = str(gate.get("target_session") or gate.get("latest_official_session") or run.get("market_session") or "")
        if not session:
            raise RuntimeError("NO_ACCEPTED_SESSION_FOR_V2_PORTFOLIO")
        return create_portfolio(
            self._validation_v2_db_path(),
            start_session=session,
            starting_capital=float(starting_capital),
            start_production_run_id=run.get("run_id"),
            app_version=APP_VERSION,
            model_version=str(run.get("production_authority") or "LIVE_DECISION_V1"),
            evidence_version="0.14.11-missing-evidence-coverage-repair",
        )

    def _validation_v2_capital_plan(self, state: dict[str, Any], rows: list[dict[str, Any]], horizon: int) -> dict[str, Any]:
        from stock_app.allocation import AllocationRequest, Holding
        from stock_app.live_decision_v1 import BUY_ACTIONS
        reserved = sum(float(o.get("reserved_capital") or 0.0) for o in state.get("pending_orders", []) if o.get("side") == "BUY")
        capital = max(0.0, float(state.get("cash") or 0.0) - reserved)
        if capital <= 0:
            return {"new_buys": [], "excluded": [], "capital_summary": {"deployable_capital": 0.0}}
        held = [p for p in state.get("positions", []) if p.get("state") != "CLOSED"]
        blocked = {p["symbol"] for p in held} | {o["symbol"] for o in state.get("pending_orders", [])}
        active = {"run": {"horizon_sessions": int(horizon), "production_authority": "LIVE_DECISION_V1"}, "candidates": rows}
        candidates = self.allocator.candidates_from_latest_run(active)
        candidates = [c for c in candidates if str(c.opportunity_status).upper() in BUY_ACTIONS and c.symbol not in blocked]
        holdings = [
            Holding(
                p["symbol"], int(p["qty"]), float(p.get("last_price") or p.get("entry_price") or 0.0),
                self.allocator.sectors.get(p["symbol"], {}).get("sector", "UNKNOWN"),
            )
            for p in held
        ]
        return self.allocator.allocate(AllocationRequest(capital, int(horizon), None), candidates, holdings)

    def _validation_v2_fill_pending_through(self, state: dict[str, Any], observed_session: str) -> list[dict[str, Any]]:
        from stock_app.validation_v2 import apply_next_open_fills, ExecutionAssumptions
        sessions = sorted({
            str(b.get("date"))[:10] for b in self._validation_v2_index_bars()
            if str(b.get("date") or "")[:10] <= observed_session
        })
        events = []
        for order in list(state.get("pending_orders", [])):
            signal = str(order.get("signal_session") or "")
            future = [s for s in sessions if s > signal]
            if not future:
                continue
            fill_session = future[0]
            symbol = order["symbol"]
            bar = next((b for b in self.prices.history(symbol, limit=5000) if str(b.get("date"))[:10] == fill_session), None)
            price = _finite((bar or {}).get("open"))
            if price is None or price <= 0:
                continue
            events.extend(apply_next_open_fills(
                self._validation_v2_db_path(), portfolio_id=state["portfolio_id"],
                fill_session=fill_session, official_open_prices={symbol: price},
                assumptions=ExecutionAssumptions()
            ))
        return events

    def validation_v2_record_today(self) -> dict[str, Any]:
        from stock_app.live_decision_v1 import monitor
        from stock_app.validation_v2 import (
            load_portfolio, mark_to_market, queue_exit, record_monitoring_event, record_signal_session
        )
        state = load_portfolio(self._validation_v2_db_path())
        if not state.get("active"):
            return {"active": False, "status": "NO_ACTIVE_V2_PORTFOLIO", "recorded": False}
        gate = self._daily_data_gate()
        session = str(gate.get("target_session") or gate.get("latest_official_session") or "")
        run = self.ui_run_input() or {}
        run_id = str(run.get("run_id") or "")
        current = bool(gate.get("ready") and session and str(run.get("market_session") or "") == session)

        if session:
            self._validation_v2_fill_pending_through(state, session)
        state = load_portfolio(self._validation_v2_db_path(), state["portfolio_id"])

        if not current:
            return record_signal_session(
                self._validation_v2_db_path(), portfolio_id=state["portfolio_id"],
                market_session=session or "UNKNOWN", production_run_id=run_id or "NO_CURRENT_RUN",
                app_version=APP_VERSION, model_version="LIVE_DECISION_V1",
                evidence_version="0.14.11-missing-evidence-coverage-repair",
                recommendations=[], capital_plan={"new_buys": []},
                official_data_ready=bool(gate.get("ready")), analysis_session_current=False,
            )

        rows = self.latest_prediction_rows(limit=200)
        live_by_symbol = {r["symbol"]: (r.get("live_decision") or {}) for r in rows}
        index_sessions = [str(b.get("date"))[:10] for b in self._validation_v2_index_bars() if str(b.get("date"))[:10] <= session]
        for pos in state.get("positions", []):
            decision = live_by_symbol.get(pos["symbol"])
            if not decision:
                record_monitoring_event(
                    self._validation_v2_db_path(), portfolio_id=state["portfolio_id"],
                    market_session=session, production_run_id=run_id, symbol=pos["symbol"],
                    action="WEAKENING", reason="Current LIVE_DECISION_V1 evidence unavailable."
                )
                continue
            held = dict(pos)
            held["sessions_held"] = sum(str(pos.get("entry_fill_session") or "") < s <= session for s in index_sessions)
            action, reason = monitor(held, decision)
            if str(action).upper().startswith("EXIT"):
                queue_exit(
                    self._validation_v2_db_path(), portfolio_id=state["portfolio_id"], symbol=pos["symbol"],
                    market_session=session, production_run_id=run_id, reason=reason
                )
            else:
                record_monitoring_event(
                    self._validation_v2_db_path(), portfolio_id=state["portfolio_id"],
                    market_session=session, production_run_id=run_id, symbol=pos["symbol"],
                    action="WEAKENING" if "WEAK" in str(action).upper() else "HOLD", reason=reason
                )

        state = load_portfolio(self._validation_v2_db_path(), state["portfolio_id"])
        closes = {}
        for pos in state.get("positions", []):
            bar = next((b for b in reversed(self.prices.history(pos["symbol"], limit=5000)) if str(b.get("date"))[:10] == session), None)
            price = _finite((bar or {}).get("close"))
            if price is not None and price > 0:
                closes[pos["symbol"]] = price
        benchmark_bar = next((b for b in reversed(self._validation_v2_index_bars()) if str(b.get("date"))[:10] == session), None)
        benchmark_close = _finite((benchmark_bar or {}).get("close"))
        mark_to_market(
            self._validation_v2_db_path(), portfolio_id=state["portfolio_id"], market_session=session,
            official_close_prices=closes, benchmark_value=benchmark_close
        )

        state = load_portfolio(self._validation_v2_db_path(), state["portfolio_id"])
        plan = self._validation_v2_capital_plan(state, rows, int(run.get("horizon_sessions") or 20))
        signal = record_signal_session(
            self._validation_v2_db_path(), portfolio_id=state["portfolio_id"],
            market_session=session, production_run_id=run_id,
            app_version=APP_VERSION, model_version="LIVE_DECISION_V1",
            evidence_version="0.14.11-missing-evidence-coverage-repair",
            recommendations=rows, capital_plan=plan, official_data_ready=True, analysis_session_current=True,
        )
        return {
            "status": "RECORDED",
            "signal": signal,
            "portfolio": load_portfolio(self._validation_v2_db_path(), state["portfolio_id"]),
        }

    def _validation_v2_replay_sessions(self, period: str, start_date: str | None, end_date: str | None) -> tuple[list[str], str, str]:
        from datetime import date, timedelta
        sessions = sorted({str(b.get("date"))[:10] for b in self._validation_v2_index_bars() if b.get("date")})
        if not sessions:
            return [], "", ""
        end = end_date or sessions[-1]
        if start_date:
            start = start_date
        else:
            days = {"1M": 35, "3M": 100, "6M": 200, "1Y": 380}.get(str(period).upper(), 200)
            start = (date.fromisoformat(end) - timedelta(days=days)).isoformat()
        return [s for s in sessions if start <= s <= end], start, end

    def validation_v2_historical_replay(
        self, period: str = "6M", starting_capital: float = 100000.0, benchmark: str = "NIFTY 50",
        start_date: str | None = None, end_date: str | None = None,
        slippage_bps: float = 10.0, transaction_cost_bps: float = 5.0,
    ) -> dict[str, Any]:
        import pandas as pd
        import tempfile
        from statistics import median
        from stock_app.live_decision_v1 import route, rank_candidates, monitor
        from stock_app.technical_v2 import compute_features
        from stock_app.validation_v2 import (
            ExecutionAssumptions, apply_next_open_fills, benchmark_nav_series, classify_replay_session,
            create_portfolio, load_portfolio, mark_to_market, queue_exit, record_signal_session,
            replay_metrics, technical_snapshot_from_features, historical_price_context,
        )

        sessions, requested_start, end = self._validation_v2_replay_sessions(period, start_date, end_date)
        if not sessions:
            return {"schema": "SRE_VALIDATION_V2_HISTORICAL_REPLAY", "status": "NOT_REPLAYABLE",
                    "reason": "OFFICIAL_NIFTY_HISTORY_UNAVAILABLE", "sessions": [], "metrics": {}}

        index_all = [b for b in self._validation_v2_index_bars() if str(b.get("date"))[:10] <= end]
        benchmark_df = pd.DataFrame(index_all)
        universe = self._validation_v2_current_universe()
        feature_cache, bar_cache, fundamental_cache = {}, {}, {}

        for symbol in universe:
            bars = [b for b in self.prices.history(symbol, limit=5000) if str(b.get("date"))[:10] <= end]
            bar_cache[symbol] = bars
            try:
                feature_cache[symbol] = compute_features(pd.DataFrame(bars), benchmark_df) if bars else None
            except Exception:
                feature_cache[symbol] = None

        def fundamental_at(symbol: str, session: str, price: float | None) -> dict[str, Any]:
            key = (symbol, session, None if price is None else round(float(price), 6))
            if key not in fundamental_cache:
                fundamental_cache[key] = self.fundamental_v3_context(symbol, price, session)
            return json.loads(json.dumps(fundamental_cache[key]))

        assumptions = ExecutionAssumptions(float(slippage_bps), float(transaction_cost_bps), True, False)
        with tempfile.TemporaryDirectory(prefix="sre-v2-replay-") as td:
            db = Path(td) / "replay.sqlite3"
            state = create_portfolio(
                db, start_session=sessions[0], starting_capital=float(starting_capital),
                start_production_run_id="HISTORICAL_REPLAY_V2", app_version=APP_VERSION,
                model_version="LIVE_DECISION_V1", evidence_version="0.14.11-missing-evidence-coverage-repair"
            )
            pid = state["portfolio_id"]
            summaries, closed_trade_pnls = [], []
            buy_signal_count = filled_entries = filled_exits = 0

            bench_closes = []
            for b in index_all:
                s = str(b.get("date"))[:10]
                close = _finite(b.get("close"))
                if s in sessions and close is not None and close > 0:
                    bench_closes.append((s, close))
            bench_series = benchmark_nav_series(float(starting_capital), bench_closes)
            bench_nav = {x["session"]: x["benchmark_nav"] for x in bench_series}

            for session_index, session in enumerate(sessions):
                state = load_portfolio(db, pid)
                opens = {}
                for order in state.get("pending_orders", []):
                    bar = next((b for b in bar_cache.get(order["symbol"], []) if str(b.get("date"))[:10] == session), None)
                    value = _finite((bar or {}).get("open"))
                    if value is not None and value > 0:
                        opens[order["symbol"]] = value
                fills = apply_next_open_fills(db, portfolio_id=pid, fill_session=session, official_open_prices=opens, assumptions=assumptions)
                filled_entries += sum(1 for e in fills if e.get("event_type") == "BUY_FILLED")
                filled_exits += sum(1 for e in fills if e.get("event_type") == "EXIT_FILLED")
                closed_trade_pnls.extend(float(e.get("realized_pnl") or 0.0) for e in fills if e.get("event_type") == "EXIT_FILLED")

                rows = []
                reconstructed = 0
                for symbol in universe:
                    bars = bar_cache.get(symbol, [])
                    bar = next((b for b in reversed(bars) if str(b.get("date"))[:10] == session), None)
                    price = _finite((bar or {}).get("close"))
                    if bar is None or price is None:
                        continue
                    technical = technical_snapshot_from_features(feature_cache.get(symbol), session)
                    fundamental = fundamental_at(symbol, session, price)

                    hist = [b for b in bars if str(b.get("date"))[:10] <= session]
                    current_index = len(hist) - 1
                    begin = max(0, current_index - 253)
                    stop = max(begin, current_index - 21)
                    observations = []
                    for prior in hist[begin:stop:21]:
                        prior_session = str(prior.get("date"))[:10]
                        prior_price = _finite(prior.get("close"))
                        past = fundamental_at(symbol, prior_session, prior_price)
                        pe = _finite((past.get("valuation") or {}).get("implied_pe_from_ttm_eps"))
                        if (past.get("point_in_time_safe") is True and
                            past.get("filing_freshness") == "CURRENT_FOR_DECISION_TIME" and
                            pe is not None and pe > 0):
                            observations.append({"session": prior_session, "pe": pe, "availability_ts": past.get("effective_availability_ts")})
                    fundamental["valuation"] = {
                        **(fundamental.get("valuation") or {}),
                        "pit_comparison_available": len(observations) >= 4,
                        "pit_historical_pe_reference": median([x["pe"] for x in observations]) if len(observations) >= 4 else None,
                        "pit_comparison_observations": observations,
                    }
                    live = route(
                        symbol, session, technical, fundamental,
                        price_context=historical_price_context(bars, session),
                        official_current=True, legacy={"validation_replay_v2": True},
                    )
                    rows.append({
                        "symbol": symbol, "rank": 0, "expected_return": None, "profit_probability": None,
                        "confidence_label": live.get("confidence"), "opportunity_status": live["final_action"],
                        "final_action": live["final_action"], "strategy_style": live.get("strategy_style"),
                        "latest_close": price, "executable": live.get("executable"), "live_decision": live,
                    })
                    reconstructed += 1
                rows = rank_candidates(rows)

                market_ready = any(str(b.get("date"))[:10] == session for b in index_all)
                replay_status = classify_replay_session(
                    market_data_ready=market_ready, fundamental_pit_ready=bool(rows),
                    valuation_pit_ready=bool(rows), production_reconstruction_ready=bool(rows),
                    optional_gaps=(reconstructed < len(universe)),
                )

                state = load_portfolio(db, pid)
                live_by_symbol = {r["symbol"]: r["live_decision"] for r in rows}
                for pos in state.get("positions", []):
                    decision = live_by_symbol.get(pos["symbol"])
                    if not decision:
                        continue
                    held = dict(pos)
                    held["sessions_held"] = sum(str(pos.get("entry_fill_session") or "") < s <= session for s in sessions[:session_index + 1])
                    action, reason = monitor(held, decision)
                    if str(action).upper().startswith("EXIT"):
                        queue_exit(db, portfolio_id=pid, symbol=pos["symbol"], market_session=session,
                                   production_run_id="REPLAY-" + session, reason=reason)

                state = load_portfolio(db, pid)
                closes = {}
                for pos in state.get("positions", []):
                    bar = next((b for b in reversed(bar_cache.get(pos["symbol"], [])) if str(b.get("date"))[:10] == session), None)
                    value = _finite((bar or {}).get("close"))
                    if value is not None and value > 0:
                        closes[pos["symbol"]] = value
                mark = mark_to_market(db, portfolio_id=pid, market_session=session,
                                      official_close_prices=closes, benchmark_value=bench_nav.get(session))

                state = load_portfolio(db, pid)
                plan = self._validation_v2_capital_plan(state, rows, 20)
                signal = record_signal_session(
                    db, portfolio_id=pid, market_session=session, production_run_id="REPLAY-" + session,
                    app_version=APP_VERSION, model_version="LIVE_DECISION_V1",
                    evidence_version="0.14.11-missing-evidence-coverage-repair",
                    recommendations=rows, capital_plan=plan,
                    official_data_ready=(replay_status != "NOT_REPLAYABLE"),
                    analysis_session_current=(replay_status != "NOT_REPLAYABLE"),
                )
                buy_signal_count += int(signal.get("allocated_buy_count") or 0)
                summaries.append({
                    "session": session, "pit_status": replay_status, "universe_size": len(universe),
                    "reconstructed_symbols": reconstructed,
                    "executable_buy_count": sum(1 for r in rows if (r.get("live_decision") or {}).get("executable") is True),
                    "allocated_buy_count": int(signal.get("allocated_buy_count") or 0),
                    "portfolio_nav": mark.get("nav"), "cash": mark.get("cash"),
                    "benchmark_nav": bench_nav.get(session), "valuation_quality": mark.get("valuation_quality"),
                })

            final_state = load_portfolio(db, pid)
            nav_series = [x for x in final_state.get("nav_history", []) if x.get("session") in sessions]
            metrics = replay_metrics(
                starting_capital=float(starting_capital), nav_series=nav_series,
                benchmark_series=bench_series, filled_entries=filled_entries, filled_exits=filled_exits,
                closed_trade_pnls=closed_trade_pnls,
            )
            metrics.update({"buy_signals": buy_signal_count, "sessions_evaluated": len(summaries),
                            "replayable_sessions": sum(1 for x in summaries if x["pit_status"] != "NOT_REPLAYABLE")})

        replayable = [x["session"] for x in summaries if x["pit_status"] != "NOT_REPLAYABLE"]
        return {
            "schema": "SRE_VALIDATION_V2_HISTORICAL_REPLAY",
            "label": "POINT-IN-TIME HISTORICAL SIMULATION",
            "status": "COMPLETED" if replayable else "NOT_REPLAYABLE",
            "requested_period": period,
            "requested_range": {"start": requested_start, "end": end},
            "trustworthy_replayable_range": {"start": replayable[0] if replayable else None, "end": replayable[-1] if replayable else None},
            "pit_completeness": {"replayable_sessions": len(replayable), "excluded_sessions": len(summaries) - len(replayable)},
            "universe_policy": "CURRENT_UNIVERSE_SURVIVORSHIP_BIAS",
            "survivorship_bias_warning": True,
            "execution_assumptions": {
                "starting_capital": float(starting_capital), "whole_shares": True,
                "slippage_bps": float(slippage_bps), "transaction_cost_bps": float(transaction_cost_bps),
                "entry": "NEXT_OFFICIAL_OPEN", "exit": "NEXT_OFFICIAL_OPEN", "broker_execution": False,
            },
            "benchmark": {"name": benchmark, "source": "OFFICIAL_INDEX_HISTORY", "flat_placeholder": False},
            "sessions": summaries, "metrics": metrics,
            "portfolio_nav_series": [{"session": x.get("session"), "nav": x.get("portfolio_nav")} for x in summaries if x.get("portfolio_nav") is not None],
            "benchmark_nav_series": bench_series, "automatic_yfinance_fallback": False,
        }

'''
atext = atext.replace(anchor, methods + anchor, 1)
api.write_text(atext, encoding="utf-8")

atext = api.read_text(encoding="utf-8")
pattern = r'''    @app\.post\("/api/validation/historical-replay"\)\n    def validation_historical_replay\(.*?\n        return ctx\.phase81_historical_replay\(.*?\)\n'''
replacement = '''    @app.post("/api/validation/historical-replay")
    def validation_historical_replay(period: str = "6M", starting_capital: float = 100000.0, benchmark: str = "NIFTY 50", start_date: str | None = None, end_date: str | None = None, slippage_bps: float = 10.0, transaction_cost_bps: float = 5.0) -> dict[str, Any]:
        return ctx.validation_v2_historical_replay(period=period, starting_capital=starting_capital, benchmark=benchmark, start_date=start_date, end_date=end_date, slippage_bps=slippage_bps, transaction_cost_bps=transaction_cost_bps)
'''
new_text, count = re.subn(pattern, replacement, atext, count=1, flags=re.S)
if count != 1:
    raise RuntimeError("historical replay route replacement failed")
atext = new_text
replace_pairs = [
('''    @app.get("/api/validation/paper-portfolio")
    def validation_paper_status() -> dict[str, Any]:
        return ctx.phase81_paper_status()
''',
'''    @app.get("/api/validation/paper-portfolio")
    def validation_paper_status(portfolio_id: str | None = None) -> dict[str, Any]:
        return ctx.validation_v2_paper_status(portfolio_id)
'''),
('''    @app.post("/api/validation/paper-portfolio/start")
    def validation_paper_start(starting_capital: float = 100000.0) -> dict[str, Any]:
        return ctx.phase81_start_paper(starting_capital=starting_capital)
''',
'''    @app.post("/api/validation/paper-portfolio/start")
    def validation_paper_start(starting_capital: float = 100000.0) -> dict[str, Any]:
        return ctx.validation_v2_start_paper(starting_capital=starting_capital)
'''),
('''    @app.post("/api/validation/paper-portfolio/record-today")
    def validation_paper_record_today() -> dict[str, Any]:
        return ctx.phase81_record_today()
''',
'''    @app.post("/api/validation/paper-portfolio/record-today")
    def validation_paper_record_today() -> dict[str, Any]:
        return ctx.validation_v2_record_today()

    @app.get("/api/validation/paper-portfolios")
    def validation_paper_portfolios() -> dict[str, Any]:
        from stock_app.validation_v2 import list_portfolios
        items = list_portfolios(ctx._validation_v2_db_path())
        return {"schema": "SRE_VALIDATION_V2_PORTFOLIOS", "items": items, "count": len(items)}

    @app.get("/api/validation/legacy/paper-portfolio")
    def validation_legacy_paper_status() -> dict[str, Any]:
        legacy = ctx.phase81_paper_status()
        return {**legacy, "status": "LEGACY_VALIDATION_V1", "read_only": True, "excluded_from_v2_performance": True}
'''),
]
for old, new in replace_pairs:
    if old not in atext:
        raise RuntimeError("Validation V2 route anchor missing")
    atext = atext.replace(old, new, 1)

legacy_block = '''        try:
            paper_status = self.phase81_paper_status()
            if paper_status.get("active"):
                result["paper_portfolio_observation"] = self.phase81_record_today()
        except Exception as exc:
            result["paper_portfolio_observation"] = {"status": "ERROR", "reason": str(exc)}
'''
v2_block = '''        try:
            paper_status = self.validation_v2_paper_status()
            if paper_status.get("active"):
                result["paper_portfolio_v2_observation"] = self.validation_v2_record_today()
        except Exception as exc:
            result["paper_portfolio_v2_observation"] = {"status": "ERROR", "reason": str(exc)}
'''
if legacy_block in atext:
    atext = atext.replace(legacy_block, v2_block, 1)

api.write_text(atext, encoding="utf-8")

policy = root / "phase8" / "validation_v2_policy.json"
policy.write_text(json.dumps({
    "schema": "SRE_VALIDATION_V2_POLICY",
    "release": "0.14.12-validation-v2",
    "paper": {"forward_only": True, "entry_execution": "NEXT_OFFICIAL_OPEN", "exit_execution": "NEXT_OFFICIAL_OPEN",
              "legacy_v1_read_only": True, "legacy_v1_excluded_from_performance": True, "idempotent_session_run": True},
    "historical_replay": {"point_in_time_required": True, "future_price_allowed": False, "future_filing_allowed": False,
                          "benchmark": "OFFICIAL_NIFTY_HISTORY", "flat_benchmark_placeholder_allowed": False,
                          "universe_policy": "CURRENT_UNIVERSE_SURVIVORSHIP_BIAS_UNTIL_HISTORICAL_MEMBERSHIP_EXISTS"},
    "live_decision_router_changed": False, "thresholds_changed": False, "provider_policy_changed": False,
    "automatic_yfinance_fallback": False,
}, indent=2), encoding="utf-8")

assert 'APP_VERSION = "0.14.12-validation-v2"' in api.read_text(encoding="utf-8")
assert "validation_v2_historical_replay" in api.read_text(encoding="utf-8")
assert "stock_app.validation_v2" in api.read_text(encoding="utf-8")
print("0.14.12 Validation V2 backend integration applied")
