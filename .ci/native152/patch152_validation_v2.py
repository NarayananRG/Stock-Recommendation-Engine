from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path


root = Path(os.environ["SRE_ENGINE_ROOT"])
source = Path(__file__).with_name("validation_v2.py")
target = root / "stock_app" / "validation_v2.py"
router = root / "stock_app" / "live_decision_v1.py"
router_before = hashlib.sha256(router.read_bytes()).hexdigest()
shutil.copy2(source, target)

api_path = root / "modern_ui" / "api.py"
api = api_path.read_text(encoding="utf-8")
api = api.replace('APP_VERSION = "0.14.10-recommendation-presentation-status-repair"', 'APP_VERSION = "0.14.12-validation-v2"', 1)
api = api.replace(
    '        return {**AUTHORITY, "backend_version": APP_VERSION}',
    '        return {**AUTHORITY, "backend_version": APP_VERSION, "validation_version": "V2", "production_rank_authority_changed": False, "production_action_authority_changed": False}',
    1,
)

start = api.index("    def phase81_historical_replay(")
end = api.index("    def latest_prediction_rows(", start)
methods = r'''    def _validation_router_sha(self) -> str:
        import hashlib
        return hashlib.sha256((self.code_root / "stock_app" / "live_decision_v1.py").read_bytes()).hexdigest()

    def _validation_pit_session(self, session: str, state: dict[str, Any], assumptions) -> dict[str, Any]:
        from statistics import median
        from stock_app.allocation import AllocationRequest, Holding
        from stock_app.live_decision_v1 import BUY_ACTIONS, monitor, rank_candidates, route
        from stock_app.validation_v2 import pit_price_bars

        source = self.data_source_status()
        members = [str(x["symbol"]).upper().replace(".NS", "") for x in (source.get("active") or {}).get("members", [])]
        universe = sorted(set(members or self.historical._load_histories()))
        universe_status = "CURRENT_UNIVERSE_SURVIVORSHIP_BIAS"
        index_bars = []
        for index_symbol in ("INDEX_NSEI", "NSEI", "^NSEI", "NIFTY"):
            index_bars = pit_price_bars(self.prices.history(index_symbol, limit=5000), session)
            if index_bars:
                break
        index_bar = index_bars[-1] if index_bars and str(index_bars[-1].get("date"))[:10] == session else None
        benchmark_close = _finite(index_bar.get("close")) if index_bar else None
        rows = []
        exact_market = unsafe_fundamental = safe_fundamental = valuation_ready = 0
        for symbol in universe:
            bars = pit_price_bars(self.prices.history(symbol, limit=5000), session)
            exact = bool(bars and str(bars[-1].get("date"))[:10] == session)
            if exact:
                exact_market += 1
            price = _finite(bars[-1].get("close")) if exact else None
            technical = self.technical_v2_context(symbol, bars, 20)
            fundamental = self.fundamental_v3_context(symbol, price, session)
            if fundamental.get("available") and not fundamental.get("point_in_time_safe"):
                unsafe_fundamental += 1
                continue
            if fundamental.get("point_in_time_safe"):
                safe_fundamental += 1
            pe_history, pb_history = [], []
            for prior in bars[-253:-21:21]:
                prior_session = str(prior.get("date"))[:10]
                past = self.fundamental_v3_context(symbol, _finite(prior.get("close")), prior_session)
                if not past.get("point_in_time_safe"):
                    continue
                pe = _finite((past.get("valuation") or {}).get("implied_pe_from_ttm_eps"))
                pb = _finite((past.get("valuation") or {}).get("implied_pb"))
                if pe is not None and pe > 0:
                    pe_history.append({"session": prior_session, "pe": pe})
                if pb is not None and pb > 0:
                    pb_history.append({"session": prior_session, "pb": pb})
            financial = fundamental.get("sector_profile") == "FINANCIAL_DOMAIN_CONSERVATIVE"
            observations = pb_history if financial else pe_history
            comparison = median([x["pb" if financial else "pe"] for x in observations]) if len(observations) >= 4 else None
            valuation = dict(fundamental.get("valuation") or {})
            valuation.update(
                pit_comparison_available=comparison is not None,
                pit_historical_pe_reference=None if financial else comparison,
                pit_historical_pb_reference=comparison if financial else None,
                pit_comparison_observations=observations,
            )
            fundamental["valuation"] = valuation
            if comparison is not None:
                valuation_ready += 1
            history = bars[-126:]
            highs = [x for x in (_finite(b.get("high")) for b in history) if x is not None and x > 0]
            lows = [x for x in (_finite(b.get("low")) for b in bars[-21:-1]) if x is not None and x > 0]
            context = {
                "drawdown_from_126_high_pct": (price / max(highs) - 1) * 100 if price and len(history) >= 126 and highs else None,
                "prior_support": min(lows) if len(lows) == 20 else None,
            }
            live = route(symbol, session, technical, fundamental, price_context=context, official_current=exact, legacy={"symbol": symbol})
            row = {
                "symbol": symbol, "market_session": session, "latest_close": price,
                "live_decision": live, "final_action": live["final_action"],
                "opportunity_status": live["final_action"], "confidence_label": live["confidence"],
                "strategy_style": live["strategy_style"], "executable": live["executable"],
            }
            held = state.get("positions", {}).get(symbol)
            if held:
                monitor_state, reason = monitor({**held, "sessions_held": 0}, live)
                row["monitoring_action"] = "EXIT SIGNAL" if "EXIT" in monitor_state else ("WEAKENING" if "WEAK" in monitor_state else "HOLD")
                row["monitoring_reason"] = reason
            rows.append(row)
        rows = rank_candidates(rows)
        market_ratio = exact_market / len(universe) if universe else 0.0
        market_status = "PASS" if benchmark_close is not None and market_ratio >= 0.95 else "INCOMPLETE"
        fundamental_status = "UNSAFE_FUTURE_EVIDENCE" if unsafe_fundamental else ("PASS" if safe_fundamental else "MISSING")
        valuation_status = "PASS" if valuation_ready else "MISSING_OPTIONAL"
        if market_status != "PASS" or unsafe_fundamental or not safe_fundamental:
            replayability = "NOT_REPLAYABLE"
        elif valuation_status == "PASS" and safe_fundamental == len(rows):
            replayability = "FULL_PIT_VALID"
        else:
            replayability = "PIT_VALID_WITH_OPTIONAL_GAPS"
        closes = {r["symbol"]: r["latest_close"] for r in rows if r.get("latest_close") is not None}
        opens = {}
        for symbol in set(closes) | {x.get("symbol") for x in state.get("pending", [])}:
            bars = pit_price_bars(self.prices.history(symbol, limit=5000), session)
            if bars and str(bars[-1].get("date"))[:10] == session and _finite(bars[-1].get("open")) is not None:
                opens[symbol] = float(bars[-1]["open"])
        held_symbols = set(state.get("positions", {}))
        pending_symbols = {x.get("symbol") for x in state.get("pending", [])}
        reserved = sum(float(x.get("capital") or 0) for x in state.get("pending", []) if x.get("side") == "BUY")
        candidates = self.allocator.candidates_from_latest_run({"candidates": rows})
        candidates = [x for x in candidates if x.opportunity_status in BUY_ACTIONS and x.symbol not in held_symbols | pending_symbols]
        holdings = [Holding(symbol, int(p["qty"]), float(p.get("last_price") or p["entry_price"]), self.allocator.sectors.get(symbol, {}).get("sector", "UNKNOWN")) for symbol, p in state.get("positions", {}).items()]
        capital = max(0.0, float(state.get("cash") or 0) - reserved)
        plan = self.allocator.allocate(AllocationRequest(capital, 20, None), candidates, holdings) if capital > 0 else {"new_buys": [], "excluded": []}
        return {
            "replayability": replayability, "market_data_status": market_status,
            "fundamental_pit_status": fundamental_status, "valuation_pit_status": valuation_status,
            "universe_status": universe_status, "live_decision_v1_run_status": "PASS" if replayability in {"FULL_PIT_VALID", "PIT_VALID_WITH_OPTIONAL_GAPS"} else "NOT_RUN",
            "rows": rows, "opens": opens, "closes": closes, "benchmark_close": benchmark_close,
            "allocation_plan": plan,
        }

    def phase81_historical_replay(self, period: str = "6M", starting_capital: float = 100000.0, benchmark: str = "NIFTY 50", start_date: str | None = None, end_date: str | None = None, slippage_bps: float = 10.0, transaction_cost_bps: float = 5.0) -> dict[str, Any]:
        from stock_app.validation_v2 import ExecutionAssumptions, persist_replay, run_replay
        from stock_app.phase81_validation import period_start, trading_sessions_for_range
        gate = self._daily_data_gate()
        latest = str(end_date or gate.get("latest_official_session") or gate.get("target_session") or "")
        if not latest:
            raise RuntimeError("NO_ACCEPTED_OFFICIAL_SESSION_FOR_REPLAY")
        start = period_start(latest, period, start_date)
        sessions = trading_sessions_for_range(self._phase81_available_sessions(), start, latest)
        assumptions = ExecutionAssumptions(starting_capital=float(starting_capital), slippage_bps=float(slippage_bps), transaction_cost_bps=float(transaction_cost_bps))
        result = run_replay(requested_period=period, sessions=sessions, starting_capital=float(starting_capital), assumptions=assumptions, session_provider=lambda session, state: self._validation_pit_session(session, state, assumptions))
        result["authority"] = {**self.phase81_authority_trace(), "production_router_sha256": self._validation_router_sha()}
        result["automatic_yfinance_fallback"] = False
        result["broker_execution"] = False
        config = {"period": period, "start": start, "end": latest, "starting_capital": starting_capital, "benchmark": benchmark, "slippage_bps": slippage_bps, "transaction_cost_bps": transaction_cost_bps}
        result["replay_id"] = persist_replay(self._phase81_db_path(), result, config)
        return result

    def phase81_paper_status(self, portfolio_id: str | None = None) -> dict[str, Any]:
        from stock_app.validation_v2 import load_portfolio
        return {**load_portfolio(self._phase81_db_path(), portfolio_id), "label": "PAPER PORTFOLIO V2 — FORWARD ONLY", "authority": self.phase81_authority_trace()}

    def phase81_start_paper(self, starting_capital: float = 100000.0) -> dict[str, Any]:
        from stock_app.validation_v2 import create_portfolio
        gate = self._daily_data_gate()
        run = self.ui_run_input() or {}
        session = str(gate.get("target_session") or "")
        if not gate.get("ready") or str(gate.get("latest_official_session") or session) != session:
            raise RuntimeError("OFFICIAL_DATA_NOT_READY")
        if str(run.get("market_session") or "") != session or not run.get("run_id"):
            raise RuntimeError("CURRENT_ACCEPTED_PRODUCTION_RUN_REQUIRED")
        return create_portfolio(self._phase81_db_path(), starting_session=session, starting_run_id=str(run["run_id"]), starting_capital=float(starting_capital), app_version=APP_VERSION, production_model_version=str(run.get("model_version") or "LIVE_DECISION_V1"), evidence_pipeline_version=APP_VERSION, router_sha256=self._validation_router_sha())

    def phase81_record_today(self) -> dict[str, Any]:
        from stock_app.live_decision_v1 import monitor
        from stock_app.validation_v2 import ExecutionAssumptions, process_paper_session
        status = self.phase81_paper_status()
        if not status.get("active"):
            return {"active": False, "status": "PAPER_PORTFOLIO_INACTIVE", "recorded": False}
        gate = self._daily_data_gate()
        session = str(gate.get("target_session") or "")
        latest = str(gate.get("latest_official_session") or "")
        run = self.ui_run_input() or {}
        rows = self.latest_prediction_rows(limit=200) if str(run.get("market_session") or "") == session else []
        symbols = {x.get("symbol") for x in rows} | {x.get("symbol") for x in status.get("positions", [])} | {x.get("symbol") for x in status.get("pending_orders", [])}
        opens, closes = {}, {}
        for symbol in {str(x) for x in symbols if x}:
            bars = [x for x in self.prices.history(symbol, limit=5000) if str(x.get("date"))[:10] <= session]
            if bars and str(bars[-1].get("date"))[:10] == session:
                if _finite(bars[-1].get("open")) is not None: opens[symbol] = float(bars[-1]["open"])
                if _finite(bars[-1].get("close")) is not None: closes[symbol] = float(bars[-1]["close"])
        row_map = {x["symbol"]: x for x in rows}
        monitoring = {}
        for position in status.get("positions", []):
            if position.get("state") == "CLOSED" or position.get("symbol") not in row_map:
                continue
            live = row_map[position["symbol"]].get("live_decision") or {}
            action, reason = monitor(position, live)
            monitoring[position["symbol"]] = {"state": "EXIT SIGNAL" if "EXIT" in action else ("WEAKENING" if "WEAK" in action else "HOLD"), "reason": reason}
        paper_plan = self._paper_capital_plan(status, run) if rows else {"new_buys": [], "excluded": []}
        return process_paper_session(self._phase81_db_path(), portfolio_id=status["portfolio_id"], expected_session=session, latest_official_session=latest, official_freshness="PASS" if gate.get("ready") else "FAIL", production_session=str(run.get("market_session") or ""), production_run_id=str(run.get("run_id") or ""), app_version=APP_VERSION, production_model_version=str(run.get("model_version") or "LIVE_DECISION_V1"), evidence_pipeline_version=APP_VERSION, candidates=rows, allocation_plan=paper_plan, official_opens=opens, official_closes=closes, monitoring=monitoring, assumptions=ExecutionAssumptions())

'''
api = api[:start] + methods + api[end:]

old_routes_start = api.index('    @app.post("/api/validation/historical-replay")')
old_routes_end = api.index('    @app.get("/api/today")', old_routes_start)
routes = r'''    @app.post("/api/validation/historical-replay")
    def validation_historical_replay(period: str = "6M", starting_capital: float = 100000.0, benchmark: str = "NIFTY 50", start_date: str | None = None, end_date: str | None = None, slippage_bps: float = 10.0, transaction_cost_bps: float = 5.0) -> dict[str, Any]:
        return ctx.phase81_historical_replay(period=period, starting_capital=starting_capital, benchmark=benchmark, start_date=start_date, end_date=end_date, slippage_bps=slippage_bps, transaction_cost_bps=transaction_cost_bps)

    @app.get("/api/validation/paper-portfolio")
    def validation_paper_status(portfolio_id: str | None = None) -> dict[str, Any]:
        return ctx.phase81_paper_status(portfolio_id)

    @app.post("/api/validation/paper-portfolio/start")
    def validation_paper_start(starting_capital: float = 100000.0) -> dict[str, Any]:
        return ctx.phase81_start_paper(starting_capital=starting_capital)

    @app.post("/api/validation/paper-portfolio/record-today")
    def validation_paper_record_today() -> dict[str, Any]:
        return ctx.phase81_record_today()

'''
api = api[:old_routes_start] + routes + api[old_routes_end:]
api_path.write_text(api, encoding="utf-8")

js_path = root / "modern_ui" / "frontend" / "app.js"
js = js_path.read_text(encoding="utf-8")
ui_start = js.index("function setValidationTab(")
ui_end = js.index("function phase81SetValidationRoute(", ui_start)
ui = r'''function setValidationTab(tab){
  const replay=tab==='replay';
  $('#validationReplayPanel')?.classList.toggle('hidden',!replay); $('#validationPaperPanel')?.classList.toggle('hidden',replay);
  $('#validationReplayTab')?.classList.toggle('active',replay); $('#validationPaperTab')?.classList.toggle('active',!replay);
}
function bindValidationTabs(){
  $('#validationReplayTab')?.addEventListener('click',()=>setValidationTab('replay'));
  $('#validationPaperTab')?.addEventListener('click',()=>setValidationTab('paper'));
}
function fmtINR(value){const n=Number(value);return Number.isFinite(n)?new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:2}).format(n):'NOT AVAILABLE'}
function metric(value,formatter){return value===null||value===undefined?'NOT AVAILABLE':(formatter?formatter(value):String(value))}
function navChart(series){
  const valid=(series||[]).filter(x=>Number.isFinite(Number(x.portfolio_nav))&&Number.isFinite(Number(x.benchmark_nav))); if(valid.length<2)return '<p>NOT AVAILABLE — insufficient actual NAV observations.</p>';
  const values=valid.flatMap(x=>[Number(x.portfolio_nav),Number(x.benchmark_nav)]), lo=Math.min(...values), hi=Math.max(...values), span=Math.max(1,hi-lo);
  const points=k=>valid.map((x,i)=>`${10+i*580/(valid.length-1)},${150-(Number(x[k])-lo)*130/span}`).join(' ');
  return `<div class="validation-chart"><svg viewBox="0 0 600 170" role="img" aria-label="Portfolio versus NIFTY 50 NAV"><polyline class="portfolio-line" points="${points('portfolio_nav')}"/><polyline class="benchmark-line" points="${points('benchmark_nav')}"/></svg><small>Portfolio NAV · NIFTY 50 NAV (actual sessions only)</small></div>`;
}
async function runHistoricalReplay(){
  const period=$('#validationPeriod')?.value||'6M', capital=Number($('#validationCapital')?.value||100000), slip=Number($('#validationSlippage')?.value||10), cost=Number($('#validationCost')?.value||5);
  busy(true,'Running point-in-time replay','Reconstructing evidence at each historical cutoff');
  try{const r=await api(`/api/validation/historical-replay?period=${encodeURIComponent(period)}&starting_capital=${capital}&benchmark=NIFTY%2050&slippage_bps=${slip}&transaction_cost_bps=${cost}`,{method:'POST'});renderValidationReplay(r)}catch(e){validationError('Historical replay failed',e)}finally{busy(false)}
}
function renderValidationReplay(r){
  const el=$('#validationReplayPanel');if(!el)return;r=r||{};const m=r.metrics||{}, range=r.trustworthy_replayable_range||{};
  const coverage=(r.coverage||[]).map(x=>`<tr><td>${escapeHtml(x.date||'')}</td><td>${escapeHtml(x.market_data_status||'')}</td><td>${escapeHtml(x.fundamental_pit_status||'')}</td><td>${escapeHtml(x.valuation_pit_status||'')}</td><td>${escapeHtml(x.universe_status||'')}</td><td>${escapeHtml(x.live_decision_v1_run_status||'')}</td><td>${escapeHtml(x.replayability||'')}</td></tr>`).join('');
  el.innerHTML=`<div class="card-label">POINT-IN-TIME HISTORICAL SIMULATION</div><h3>Historical Replay V2</h3><div class="validation-controls"><label>Requested period<select id="validationPeriod"><option>1M</option><option>3M</option><option selected>6M</option></select></label><label>Starting capital<input id="validationCapital" type="number" value="100000"></label><label>Slippage bps<input id="validationSlippage" type="number" value="10"></label><label>Transaction cost bps<input id="validationCost" type="number" value="5"></label><button id="runHistoricalReplay" class="primary-btn">RUN PIT REPLAY</button></div>
  <div class="validation-disclosure"><strong>Requested: ${escapeHtml(r.requested_period||'—')}</strong><span>Trustworthy replayable range: ${escapeHtml(range.start||'NOT REPLAYABLE')} → ${escapeHtml(range.end||'NOT REPLAYABLE')}</span><span>PIT completeness: ${escapeHtml(r.pit_completeness||'—')}</span>${r.survivorship_bias_warning?'<span class="warning">CURRENT_UNIVERSE_SURVIVORSHIP_BIAS</span>':''}<span>Whole shares · next official open entry/exit · no broker execution</span></div>
  <div class="daily-flow-grid">${[['Start NAV',metric(m.start_nav,fmtINR)],['End NAV',metric(m.end_nav,fmtINR)],['Portfolio return',metric(m.portfolio_return,fmtPctFraction)],['Benchmark return',metric(m.benchmark_return,fmtPctFraction)],['Excess return',metric(m.excess_return,fmtPctFraction)],['Max drawdown',metric(m.max_drawdown,fmtPctFraction)],['BUY signals',metric(m.buy_signals)],['Filled entries',metric(m.filled_entries)],['Exits',metric(m.exits)],['Closed trades',metric(m.closed_trades)],['Realized P&L',metric(m.realized_pnl,fmtINR)],['Unrealized P&L',metric(m.unrealized_pnl,fmtINR)],['Cash',metric(m.cash,fmtINR)],['Exposure',metric(m.exposure,fmtPctFraction)],['Win rate',metric(m.win_rate,fmtPctFraction)],['Longest cash-only period',metric(m.longest_cash_only_period)],['BUY frequency',metric(m.buy_frequency,fmtPctFraction)]].map(([k,v])=>`<div><span>${k}</span><strong>${escapeHtml(v)}</strong></div>`).join('')}</div>${navChart(r.series)}<h3>Session Coverage</h3><div class="table-wrap"><table><thead><tr><th>Date</th><th>Market</th><th>Fundamental PIT</th><th>Valuation PIT</th><th>Universe</th><th>LIVE_DECISION_V1</th><th>Replayability</th></tr></thead><tbody>${coverage||'<tr><td colspan="7">No sessions available</td></tr>'}</tbody></table></div>`;
  $('#runHistoricalReplay')?.addEventListener('click',runHistoricalReplay);
}
async function startPaperPortfolio(){
  const capital=Number($('#paperStartingCapital')?.value||100000); if(!window.confirm('Start a new forward-only paper portfolio from the current accepted production run? The previous portfolio remains read-only.'))return;
  busy(true,'Starting new paper portfolio','Binding to the current accepted production run');
  try{await api(`/api/validation/paper-portfolio/start?starting_capital=${capital}`,{method:'POST'});renderValidationPaper(await api('/api/validation/paper-portfolio'));toast('New Paper Portfolio V2 started')}catch(e){validationError('Paper portfolio failed',e)}finally{busy(false)}
}
async function selectPaperPortfolio(id){renderValidationPaper(await api(`/api/validation/paper-portfolio?portfolio_id=${encodeURIComponent(id)}`))}
function renderValidationPaper(p){
  const el=$('#validationPaperPanel');if(!el)return;p=p||{};const portfolioOptions=(p.portfolios||[]).map(x=>`<option value="${escapeHtml(x.portfolio_id)}" ${x.portfolio_id===p.portfolio_id?'selected':''}>${escapeHtml(x.status+' · '+x.starting_session+' · '+x.portfolio_id.slice(-8))}</option>`).join('');
  if(!p.active&&!p.portfolio_id){el.innerHTML=`<div class="card-label">PAPER PORTFOLIO V2</div><h3>Start New Paper Portfolio</h3><p>Forward-only from the current accepted production run. Existing Validation V1 ledgers remain read-only.</p><label>Starting capital<input id="paperStartingCapital" type="number" value="100000"></label><button id="startPaperPortfolio" class="primary-btn">START NEW PAPER PORTFOLIO FROM CURRENT RUN</button>${(p.legacy_portfolios||[]).length?`<p>${p.legacy_portfolios.length} Legacy / Previous Portfolio record(s) preserved.</p>`:''}`;$('#startPaperPortfolio')?.addEventListener('click',startPaperPortfolio);return}
  const pos=p.positions||[], orders=p.pending_orders||[], journal=p.journal||[];
  el.innerHTML=`<div class="paper-toolbar"><label>Portfolio<select id="paperPortfolioSelect">${portfolioOptions}</select></label><label>Starting capital<input id="paperStartingCapital" type="number" value="100000"></label><button id="startPaperPortfolio" class="primary-btn">START NEW PORTFOLIO</button></div><div class="validation-disclosure"><strong>${p.read_only?'Legacy / Previous Portfolio':'Active Portfolio'}</strong><span>Portfolio ID: ${escapeHtml(p.portfolio_id)}</span><span>Started: ${escapeHtml(p.starting_session||'—')}</span><span>Starting run: ${escapeHtml(p.starting_run_id||'—')}</span><span>Engine: ${escapeHtml(p.app_version||'—')}</span></div><div class="daily-flow-grid">${[['Portfolio value',fmtINR(p.nav)],['Cash',fmtINR(p.cash)],['Invested value',fmtINR(p.invested_value)],['Exposure',metric(p.exposure,fmtPctFraction)],['Realized P&L',fmtINR(p.realized_pnl)],['Unrealized P&L',fmtINR(p.unrealized_pnl)],['Pending capital',fmtINR(p.pending_capital)],['Pending entries',orders.filter(x=>x.side==='BUY').length],['Pending exits',orders.filter(x=>x.side==='SELL').length],['Mark quality',p.valuation_quality||'—']].map(([k,v])=>`<div><span>${k}</span><strong>${escapeHtml(String(v))}</strong></div>`).join('')}</div><h3>Current Positions</h3><div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Qty</th><th>Entry signal</th><th>Entry fill</th><th>Entry price</th><th>Mark session</th><th>Mark</th><th>State</th><th>Thesis health</th><th>Unrealized P&L</th></tr></thead><tbody>${pos.filter(x=>x.state!=='CLOSED').map(x=>`<tr><td>${escapeHtml(x.symbol)}</td><td>${x.qty}</td><td>${x.entry_signal_session}</td><td>${x.entry_fill_session}</td><td>${fmtINR(x.entry_price)}</td><td>${escapeHtml(x.current_mark_session||'STALE MARK')}</td><td>${fmtINR(x.current_mark_price)}</td><td>${escapeHtml(x.current_state||x.state)}</td><td>${escapeHtml(x.current_thesis_health||'—')}</td><td>${fmtINR(x.unrealized_pnl)}</td></tr>`).join('')||'<tr><td colspan="10">No current positions</td></tr>'}</tbody></table></div><h3>Pending Orders</h3><div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Side</th><th>State</th><th>Signal session</th><th>Reserved capital</th></tr></thead><tbody>${orders.map(x=>`<tr><td>${escapeHtml(x.symbol)}</td><td>${x.side}</td><td>${x.state}</td><td>${x.signal_session}</td><td>${fmtINR(x.reserved_capital)}</td></tr>`).join('')||'<tr><td colspan="5">No pending orders</td></tr>'}</tbody></table></div><h3>Trade Journal</h3><div class="table-wrap"><table><thead><tr><th>Session</th><th>Event</th><th>Symbol</th><th>Reason</th></tr></thead><tbody>${journal.map(x=>`<tr><td>${x.market_session}</td><td>${escapeHtml(x.event_type)}</td><td>${escapeHtml(x.symbol||'')}</td><td>${escapeHtml(x.reason||x.action||'')}</td></tr>`).join('')||'<tr><td colspan="4">No journal events yet</td></tr>'}</tbody></table></div>${(p.legacy_portfolios||[]).length?`<p>${p.legacy_portfolios.length} LEGACY_VALIDATION_V1 portfolio(s) preserved read-only and excluded from V2 performance.</p>`:''}`;
  $('#startPaperPortfolio')?.addEventListener('click',startPaperPortfolio); $('#paperPortfolioSelect')?.addEventListener('change',e=>selectPaperPortfolio(e.target.value));
}
async function loadValidation(){bindValidationTabs();setValidationTab('paper');try{renderValidationPaper(await api('/api/validation/paper-portfolio'))}catch(e){validationError('Paper portfolio failed',e)}try{renderValidationReplay({requested_period:'6M',metrics:{},coverage:[],series:[],pit_completeness:'RUN REQUIRED'})}catch(e){}}

'''
js = js[:ui_start] + ui + js[ui_end:]
js_path.write_text(js, encoding="utf-8")

html_path = root / "modern_ui" / "frontend" / "index.html"
html = html_path.read_text(encoding="utf-8")
html = html.replace("Historical replay and forward-only paper tracking for the frozen production model.", "Trustworthy forward-only paper trading and point-in-time historical simulation. Metrics exist only when their evidence exists.")
html_path.write_text(html, encoding="utf-8")

css_path = root / "modern_ui" / "frontend" / "styles.css"
css = css_path.read_text(encoding="utf-8") + r'''

/* Validation V2 */
.validation-disclosure,.paper-toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:12px 0;padding:12px;border:1px solid var(--line);border-radius:10px;background:var(--surface-soft)}
.validation-disclosure span,.validation-disclosure strong{font-size:12px}.validation-disclosure .warning{color:#b45309;font-weight:700}.paper-toolbar label{display:grid;gap:4px}.validation-chart{margin:16px 0;padding:12px;border:1px solid var(--line);border-radius:10px}.validation-chart svg{width:100%;height:190px;background:var(--surface-soft)}.validation-chart polyline{fill:none;stroke-width:3}.validation-chart .portfolio-line{stroke:#0f766e}.validation-chart .benchmark-line{stroke:#6366f1}
'''
css_path.write_text(css, encoding="utf-8")

router_after = hashlib.sha256(router.read_bytes()).hexdigest()
if router_before != router_after:
    raise RuntimeError("LIVE_DECISION_V1 router changed")
(root / "validation_v2_router_sha256.txt").write_text(router_before + "\n", encoding="utf-8")
print(f"0.14.12 Validation V2 applied; router SHA unchanged: {router_before}")
