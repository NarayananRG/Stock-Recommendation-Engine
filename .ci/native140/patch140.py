from pathlib import Path
import os
import shutil

root = Path(os.environ['SRE_ENGINE_ROOT'])
here = Path(__file__).parent
shutil.copyfile(here / 'live_decision_v1.py', root / 'stock_app/live_decision_v1.py')

def edit(relative, old, new):
    path = root / relative
    text = path.read_text(encoding='utf-8-sig')
    if old not in text:
        raise RuntimeError(f'{relative}: missing patch point {old[:100]}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')

edit('modern_ui/api.py', 'APP_VERSION = "0.13.5-phase8-paper-journal-hotfix"', 'APP_VERSION = "0.14.0-live-dual-strategy-v1"')
for file, authority in [('technical_v2.py','LIVE_EVIDENCE'), ('fundamental_v3.py','LIVE_EVIDENCE'), ('combined_prediction_v2.py','DIAGNOSTIC_ONLY')]:
    edit('stock_app/' + file, 'AUTHORITY = "SHADOW_ONLY"', f'AUTHORITY = "{authority}"')
edit('stock_app/fundamental_v3.py', 'def _read_rows(path: Path | None) -> list[dict[str, Any]]:', '''from functools import lru_cache

def _read_rows(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    stat = path.stat()
    return _cached_read_rows(path, stat.st_mtime_ns, stat.st_size)

@lru_cache(maxsize=16)
def _cached_read_rows(path: Path, modified: int, size: int) -> list[dict[str, Any]]:''')
edit('stock_app/allocation.py', 'EXECUTABLE_DECISIONS = ("STRONG CANDIDATE", "MODERATE CANDIDATE", "BUY CANDIDATE")', 'EXECUTABLE_DECISIONS = ("MOMENTUM BUY", "RECOVERY BUY", "MOMENTUM + RECOVERY BUY")')
edit('stock_app/allocation.py', '    return any(token in text for token in EXECUTABLE_DECISIONS)', '    return text in EXECUTABLE_DECISIONS')
edit('stock_app/allocation.py', 'effective_decision = str(combined.get("combined_decision") or row.get("opportunity_status") or "")', 'effective_decision = str((row.get("live_decision") or {}).get("final_action") or row.get("opportunity_status") or "")')
edit('stock_app/allocation.py', 'effective_confidence = str(combined.get("evidence_confidence") or row.get("confidence_label") or "")', 'effective_confidence = str((row.get("live_decision") or {}).get("confidence") or row.get("confidence_label") or "")')
edit('stock_app/allocation.py', '        for row in rows:\n            symbol = normalize_symbol(row.get("symbol", ""))', '        seen = set()\n        for row in rows:\n            symbol = normalize_symbol(row.get("symbol", ""))\n            if not symbol or symbol in seen:\n                continue\n            seen.add(symbol)')

methods = '''    def _live_file(self, run_id: str) -> Path:
        import hashlib
        return self.config.app_data_dir / "live_decision_v1" / (hashlib.sha256(run_id.encode()).hexdigest() + ".json")

    def _persist_position_thesis(self, position_id: int, symbol: str) -> None:
        row = next((r for r in self.latest_prediction_rows(200) if r["symbol"] == symbol.upper().replace(".NS", "")), {})
        live = row.get("live_decision")
        if not live or not row.get("executable"):
            return
        with self.db.connect() as con:
            con.execute("create table if not exists live_position_theses (position_id integer primary key, thesis_json text not null)")
            con.execute("insert or ignore into live_position_theses values (?,?)", (position_id, json.dumps(live)))

    def live_today_summary(self) -> dict:
        from stock_app.live_decision_v1 import monitor
        from collections import Counter
        summary = self.monitoring.summary()
        decisions = {r["symbol"]: r.get("live_decision") for r in self.latest_prediction_rows(200)}
        with self.db.connect() as con:
            con.execute("create table if not exists live_position_theses (position_id integer primary key, thesis_json text not null)")
            entry = {r[0]: json.loads(r[1]) for r in con.execute("select position_id,thesis_json from live_position_theses")}
        actions = []
        existing = {a.get("position_id"): a for a in summary.get("actions", [])}
        for pos in self.portfolio.list_positions():
            if str(pos.get("position_status") or "OPEN") == "CLOSED": continue
            original = entry.get(pos.get("id"))
            if not original: continue
            current = decisions.get(pos["symbol"])
            bars = self.prices.history(pos["symbol"], limit=5000)
            original = {**original, "sessions_held": sum(str(b["date"])[:10] > str(pos["buy_date"]) for b in bars)}
            action, reason = monitor(original, current) if current else ("WEAKENING", "Current thesis evidence unavailable; review required.")
            actions.append({**existing.get(pos["id"], {}), "position_id": pos["id"], "symbol": pos["symbol"], "action": action,
                            "strategy_style": original["strategy_style"], "explanation": reason, "reason_codes": [reason],
                            "thesis_health": action, "entry_thesis": original})
        live_ids = {a["position_id"] for a in actions}
        actions += [a for a in summary.get("actions", []) if a.get("position_id") not in live_ids]
        paper = self.phase81_paper_status()
        for pos in paper.get("positions", []):
            if pos.get("state") == "CLOSED": continue
            current = decisions.get(pos["symbol"])
            pos = {**pos, "sessions_held": sum(str(b["date"])[:10] > str(pos["entry_fill_date"]) for b in self.prices.history(pos["symbol"], limit=5000))}
            action, reason = monitor(pos, current) if current else ("WEAKENING", "Current thesis evidence unavailable; review required.")
            actions.append({"symbol":pos["symbol"], "action":action, "thesis_health":action,
                            "strategy_style":pos.get("strategy_style"), "explanation":reason, "reason_codes":[reason], "simulated":True})
        return {**summary, "actions":actions, "action_counts":dict(Counter(a["action"] for a in actions))}

    def _paper_capital_plan(self, state: dict, run: dict) -> dict:
        from stock_app.allocation import Holding
        active = self.active_prediction_run() or {"candidates": []}
        reserved = sum(float((o.get("allocation") or {}).get("capital") or 0) for o in state.get("pending_orders", []) if o.get("side") == "BUY")
        capital = max(0, float(state["cash"]) - reserved)
        if capital <= 0: return {"new_buys": [], "excluded": []}
        held = [p for p in state.get("positions", []) if p.get("state") != "CLOSED"]
        excluded_symbols = {p["symbol"] for p in held} | {p["symbol"] for p in state.get("pending_orders", [])}
        candidates = self.allocator.candidates_from_latest_run(active)
        candidates = [c for c in candidates if is_executable_decision(c.opportunity_status) and c.symbol not in excluded_symbols]
        holdings = [Holding(p["symbol"], int(p["qty"]), float(p.get("last_price") or p["entry_price"]), self.allocator.sectors.get(p["symbol"], {}).get("sector", "UNKNOWN")) for p in held]
        return self.allocator.allocate(AllocationRequest(capital, int(run.get("horizon_sessions") or 20), None), candidates, holdings)

    def _materialize_live_run(self, data: dict) -> dict:
        from stock_app.live_decision_v1 import route, lane_counts, rank_candidates
        import os
        run = data["run"]
        path = self._live_file(str(run["run_id"]))
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        session = str(run["market_session"])
        gate = self._daily_data_gate()
        current = bool(gate.get("ready") and str(gate.get("target_session")) == session)
        rows = []
        for row in data["candidates"]:
            symbol = str(row["symbol"]).upper().replace(".NS", "")
            bars = [b for b in self.prices.history(symbol, limit=5000) if str(b.get("date"))[:10] <= session]
            technical = self.technical_v2_context(symbol, bars)
            price = _finite(bars[-1].get("close")) if bars else None
            fundamental = self.fundamental_v3_context(symbol, price, session)
            # Every comparison re-evaluates filings at that historical cutoff.
            # Never reuse today's EPS for a past valuation observation.
            from statistics import median
            pe_history = []
            for prior in bars[-253:-21:21]:
                past = self.fundamental_v3_context(symbol, _finite(prior.get("close")), str(prior["date"])[:10])
                pe = _finite((past.get("valuation") or {}).get("implied_pe_from_ttm_eps"))
                if past.get("point_in_time_safe") and past.get("filing_freshness") == "CURRENT_FOR_DECISION_TIME" and pe is not None and pe > 0:
                    pe_history.append({"session": prior["date"], "pe": pe, "availability_ts": past.get("effective_availability_ts")})
            fundamental["valuation"] = {**(fundamental.get("valuation") or {}),
                                       "pit_comparison_available": len(pe_history) >= 4,
                                       "pit_historical_pe_reference": median([p["pe"] for p in pe_history]) if len(pe_history) >= 4 else None,
                                       "pit_comparison_observations": pe_history}
            history = bars[-126:]
            highs = [_finite(b.get("high")) for b in history]
            lows = [_finite(b.get("low")) for b in bars[-21:-1]]
            highs = [v for v in highs if v is not None and v > 0]
            lows = [v for v in lows if v is not None and v > 0]
            context = {"drawdown_from_126_high_pct": (price / max(highs) - 1) * 100 if price and highs and len(history) >= 126 else None,
                       "prior_support": min(lows) if len(lows) == 20 else None}
            live = route(symbol, session, technical, fundamental, price_context=context,
                         official_current=current and bool(bars) and str(bars[-1].get("date"))[:10] == session, legacy=dict(row))
            rows.append({**row, "legacy_opportunity_status": row.get("opportunity_status"), "live_decision": live,
                         "opportunity_status": live["final_action"], "confidence_label": live["confidence"],
                         "final_action": live["final_action"], "strategy_style": live["strategy_style"],
                         "latest_close": price, "target_used_in_score": False})
        rows = rank_candidates(rows)
        result = {"run": {**run, "production_authority": "LIVE_DECISION_V1", "model_version": APP_VERSION,
                            "lane_counts": lane_counts([r["live_decision"] for r in rows])}, "candidates": rows}
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation preserves the original decision across duplicate runs.
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            json.dump(result, handle, indent=2)
            temporary = Path(handle.name)
        try:
            os.rename(temporary, path)
        except FileExistsError:
            return json.loads(path.read_text(encoding="utf-8"))
        finally:
            temporary.unlink(missing_ok=True)
        return json.loads(path.read_text(encoding="utf-8"))

'''
edit('modern_ui/api.py', '    def active_prediction_run(self) -> dict[str, Any] | None:', methods + '    def active_prediction_run(self) -> dict[str, Any] | None:')
edit('modern_ui/api.py', '        return self._prediction_run_by_id(self._saved_active_run_id())', '''        run_id = self._saved_active_run_id()
        if run_id and self._live_file(run_id).exists():
            return json.loads(self._live_file(run_id).read_text(encoding="utf-8"))
        return self._prediction_run_by_id(run_id)''')
edit('modern_ui/api.py', '            return match, True', '            return self._materialize_live_run(match), True')
edit('modern_ui/api.py', '        return data, False', '        return self._materialize_live_run(data), False')
edit('modern_ui/api.py', '            item = dict(row)\n            item["run_id"]', '            item = dict(row)\n            live = item.get("live_decision") or {}\n            item.update({key: value for key, value in live.items() if key != "evidence"})\n            item["run_id"]')
# Budget suitability is separate from the BUY thesis; both are needed to execute.
edit('modern_ui/api.py', '"executable": bool(execution.get("executable")),', '"executable": bool(execution.get("executable")) and live.get("executable") is True and bool(self._daily_data_gate().get("ready")) and str(self._daily_data_gate().get("target_session")) == str(run["market_session"]),')
edit('modern_ui/api.py', '        all_inputs = self.allocator.candidates_from_latest_run(active_run)\n        inputs =', '''        gate = self._daily_data_gate()
        if not gate.get("ready") or str(gate.get("target_session")) != str(active_run["run"]["market_session"]):
            active_run = {**active_run, "candidates": []}
        all_inputs = self.allocator.candidates_from_latest_run(active_run)
        inputs =''')
edit('modern_ui/api.py', '        result["source_run"] = dict(active_run.get("run") or {})', '''        live_by_symbol = {row["symbol"]: row.get("live_decision") or {} for row in active_run.get("candidates", [])}
        for row in result.get("rows", []) + result.get("new_buys", []):
            live = live_by_symbol.get(row.get("symbol"), {})
            row.update({key: live.get(key) for key in ("strategy_style", "primary_style", "secondary_style", "momentum_thesis", "recovery_thesis", "business_health", "technical_state", "confidence", "thesis", "final_action")})
        result["source_run"] = dict(active_run.get("run") or {})''')
edit('modern_ui/api.py', 'capital_plan={"new_buys": [], "excluded": []})', 'capital_plan=self.build_capital_plan(float(status.get("cash") or status.get("starting_capital") or 100000), int(run.get("horizon_sessions") or 20), None))')
edit('modern_ui/api.py', '        run = self.ui_run_input() or {}\n        return record_daily_observation', '''        if not gate.get("ready"):
            return {"active": True, "status": "BLOCKED_OFFICIAL_DATA", "recorded": False}
        from stock_app.phase81_validation import apply_open_fills, mark_daily_hold_exit
        from stock_app.live_decision_v1 import next_official_open
        session = str(gate["target_session"])
        next_opens = {}
        index_bars = []
        for index_symbol in ("INDEX_NSEI", "NSEI", "^NSEI", "NIFTY"):
            index_bars = self.prices.history(index_symbol, limit=5000)
            if index_bars: break
        for order in status.get("pending_orders", []):
            quote = next_official_open(self.prices.history(order["symbol"], limit=5000), index_bars, str(order["signal_session"]), session)
            if quote:
                next_opens.setdefault(quote[0], {})[order["symbol"]] = quote[1]
        for fill_session, prices in sorted(next_opens.items()):
            apply_open_fills(self._phase81_db_path(), portfolio_id=status["portfolio_id"], fill_session=fill_session, open_prices=prices)
        status = self.phase81_paper_status()
        run = self.ui_run_input() or {}
        if str(run.get("market_session")) != session:
            return {"active": True, "status": "BLOCKED_ANALYSIS_SESSION", "recorded": False}
        rows = self.latest_prediction_rows(limit=200)
        positions = {p["symbol"]: p for p in status.get("positions", []) if p.get("state") != "CLOSED"}
        for row in rows:
            pos = positions.get(row["symbol"])
            if pos:
                row["holding_sessions"] = sum(str(pos["entry_fill_date"]) < str(b["date"])[:10] <= session for b in index_bars)
        mark_daily_hold_exit(self._phase81_db_path(), portfolio_id=status["portfolio_id"], market_session=session,
                             production_run_id=run.get("run_id"), recommendations=rows)
        return record_daily_observation''')
edit('modern_ui/api.py', 'capital_plan=self.build_capital_plan(float(status.get("cash") or status.get("starting_capital") or 100000), int(run.get("horizon_sessions") or 20), None))', 'capital_plan=self._paper_capital_plan(status, run))')
edit('modern_ui/api.py', '            "technical_v2": self.technical_v2_context(symbol, bars),', '            "live_decision": (prediction or {}).get("live_decision"),\n            "technical_v2": self.technical_v2_context(symbol, bars),')
edit('modern_ui/api.py', '        prediction = dict(pred) if pred else None', '''        prediction = next((r for r in self.latest_prediction_rows(limit=200) if r.get("symbol") == symbol), None)''')
edit('modern_ui/api.py', '        return {"ok": True, "position_id": position_id, **ctx.portfolio_summary()}', '        ctx._persist_position_thesis(position_id, req.symbol)\n        return {"ok": True, "position_id": position_id, **ctx.portfolio_summary()}')
api_path = root / 'modern_ui/api.py'
api_text = api_path.read_text(encoding='utf-8').replace('ctx.monitoring.summary()', 'ctx.live_today_summary()')
api_text = api_text.replace('"authority": "FROZEN_PRODUCTION_RECOMMENDATIONS_UNCHANGED"', '"authority": "LIVE_DECISION_V1"')
api_text = api_text.replace('Technical V2/Fundamental V3/Combined V2 remain SHADOW_ONLY', 'Technical V2 and Fundamental V3: LIVE_EVIDENCE; Combined V2: DIAGNOSTIC_ONLY')
api_text = api_text.replace('"decision_authority": "UNCHANGED_EXISTING_ENGINE"', '"decision_authority": "LIVE_DECISION_V1"')
api_text = api_text.replace('"authority": "SHADOW_ONLY"', '"authority": "DIAGNOSTIC_ONLY"')
# NO_DATA is still a Technical V2 evidence response.
api_text = api_text.replace('"authority": "DIAGNOSTIC_ONLY",\n                "status": "NO_DATA"', '"authority": "LIVE_EVIDENCE",\n                "status": "NO_DATA"')
api_text = api_text.replace('Frozen production snapshot available for accepted active run.', 'Live decision snapshot available for accepted active run.')
api_path.write_text(api_text, encoding='utf-8')

# Persist strategy evidence with orders and filled positions, preserving old journals.
edit('stock_app/phase81_validation.py', '"production_recommendation_authority": "FROZEN_PRODUCTION_MODEL"', '"production_recommendation_authority": "LIVE_DECISION_V1"')
edit('stock_app/phase81_validation.py', '"production_rank_authority_changed": False', '"production_rank_authority_changed": True')
edit('stock_app/phase81_validation.py', '"production_action_authority_changed": False', '"production_action_authority_changed": True')
edit('stock_app/phase81_validation.py', '    return bool(row.get("executable")) and "BUY" in decision and "WATCH" not in decision', '    from .live_decision_v1 import BUY_ACTIONS\n    return bool(row.get("executable")) and decision in BUY_ACTIONS')
for field, authority in [('technical_v2','LIVE_EVIDENCE'), ('fundamental_v3','LIVE_EVIDENCE'), ('combined_v2','DIAGNOSTIC_ONLY')]:
    edit('stock_app/phase81_validation.py', f'"{field}_authority": "SHADOW_ONLY"', f'"{field}_authority": "{authority}"')
edit('stock_app/phase81_validation.py', '                orders.append(order)', '''                allocation = order["allocation"]
                already_held = con.execute("select 1 from paper_positions where portfolio_id=? and symbol=? and state!='CLOSED'", (portfolio_id, symbol)).fetchone()
                already_pending = con.execute("select 1 from paper_orders where portfolio_id=? and symbol=? and state like 'PENDING%'", (portfolio_id, symbol)).fetchone()
                if already_held or already_pending:
                    continue
                if not allocation or float(allocation.get("estimated_cost") or 0) <= 0:
                    continue
                order["allocation"]["capital"] = allocation["estimated_cost"]
                order["authority"] = "LIVE_DECISION_V1"
                order["entry_thesis"] = row.get("live_decision") or {}
                order.update({key: row.get(key) for key in ("strategy_style", "primary_style", "momentum_thesis", "recovery_thesis", "business_health", "technical_state")})
                order["fundamental_state"] = row.get("business_health")
                orders.append(order)''')
edit('stock_app/phase81_validation.py', '                con.execute("insert or replace into paper_positions', '''                position.update({key: order.get(key) for key in ("strategy_style", "primary_style", "momentum_thesis", "recovery_thesis", "fundamental_state", "technical_state", "entry_thesis")})
                con.execute("insert or replace into paper_positions''')
edit('stock_app/phase81_validation.py', '            if "EXIT" in decision or "SELL" in decision:', '''            if row.get("live_decision"):
                from .live_decision_v1 import monitor
                held[symbol]["sessions_held"] = row.get("holding_sessions")
                decision, thesis_reason = monitor(held[symbol], row["live_decision"])
                row = {**row, "monitoring_reason": thesis_reason}
            if "EXIT" in decision or "SELL" in decision:''')
edit('stock_app/phase81_validation.py', '            decision = str(row.get("opportunity_status") or row.get("decision") or "").upper()\n            if row.get("live_decision"):', '''            price = row.get("latest_close")
            if price is not None and math.isfinite(float(price)) and float(price) > 0 and str(row.get("market_session") or market_session) == market_session:
                held[symbol].update(last_price=float(price), last_valuation_session=market_session,
                                    unrealized_pnl=round(int(held[symbol]["qty"]) * (float(price) - float(held[symbol]["entry_price"])), 2))
                con.execute("update paper_positions set state_json=? where position_id=?", (json.dumps(held[symbol], sort_keys=True), held[symbol]["position_id"]))
            decision = str(row.get("opportunity_status") or row.get("decision") or "").upper()
            if row.get("live_decision"):''')
edit('stock_app/phase81_validation.py', '    return events\n', '''        state["nav"] = round(float(state["cash"]) + sum(int(p["qty"]) * float(p.get("last_price") or p["entry_price"]) for p in held.values()), 2)
        state["valuation_quality"] = "CURRENT_OFFICIAL_MARKS" if all(p.get("last_valuation_session") == market_session for p in held.values()) else "PARTIAL_OR_STALE_MARKS"
        _save_state(con, state)
    return events
''')
edit('stock_app/phase81_validation.py', '"model_identity": "FROZEN_PRODUCTION_MODEL"', '"model_identity": "0.14.0-live-dual-strategy-v1"')
paper_path = root / 'stock_app/phase81_validation.py'
paper_text = paper_path.read_text(encoding='utf-8')
for event_type in ('EXIT_SIGNAL_GENERATED', 'WEAKENING', 'HELD'):
    paper_text = paper_text.replace('"event_type": "' + event_type + '",', '"event_type": "' + event_type + '", "reason": row.get("monitoring_reason") or decision, "entry_thesis": held[symbol].get("entry_thesis"),')
paper_path.write_text(paper_text, encoding='utf-8')
edit('stock_app/phase81_validation.py', 'def connect(db_path: Path) -> sqlite3.Connection:', '''class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()

def connect(db_path: Path) -> sqlite3.Connection:''')
edit('stock_app/phase81_validation.py', '    con = sqlite3.connect(db_path)', '    con = sqlite3.connect(db_path, factory=_ClosingConnection)')
edit('stock_app/phase81_validation.py', '        "watch_count": len(watch),', '''        "watch_count": len(watch),
        "momentum_buy_count": sum(r.get("final_action") == "MOMENTUM BUY" for r in rows),
        "recovery_buy_count": sum(r.get("final_action") == "RECOVERY BUY" for r in rows),
        "both_buy_count": sum(r.get("final_action") == "MOMENTUM + RECOVERY BUY" for r in rows),
        "avoid_count": sum(str(r.get("final_action") or "").startswith("AVOID") for r in rows),''')
print('0.14.0 LIVE_DECISION_V1 integration applied')
