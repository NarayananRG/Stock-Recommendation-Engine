from __future__ import annotations

import os
from pathlib import Path

root = Path(os.environ["SRE_ENGINE_ROOT"])
front = root / "modern_ui" / "frontend" / "app.js"
js = front.read_text(encoding="utf-8")

override = r'''
// 0.14.12 Validation V2 overrides
async function startPaperPortfolio(){
  const raw=prompt('Starting paper capital (Rs)','100000');
  if(raw===null)return;
  const capital=Number(raw);
  if(!Number.isFinite(capital)||capital<=0){toast('Enter a valid starting capital');return}
  busy(true,'Starting new V2 paper portfolio','Creating a new forward-only portfolio ID');
  try{
    await api('/api/validation/paper-portfolio/start?starting_capital='+encodeURIComponent(capital),{method:'POST'});
    renderValidationPaper(await api('/api/validation/paper-portfolio'));
    toast('New V2 paper portfolio started');
  }catch(e){validationError('Paper Portfolio V2 failed',e)}
  finally{busy(false)}
}
async function recordPaperToday(){
  busy(true,'Recording V2 paper session','Current LIVE_DECISION_V1 to next-open paper orders');
  try{
    await api('/api/validation/paper-portfolio/record-today',{method:'POST'});
    renderValidationPaper(await api('/api/validation/paper-portfolio'));
    toast('V2 paper session recorded');
  }catch(e){validationError('Paper Portfolio V2 failed',e)}
  finally{busy(false)}
}
function renderValidationPaper(p){
  const el=$('#validationPaperPanel');if(!el)return;p=p||{};
  const portfolios=p.portfolios||[];
  if(!p.active){
    el.innerHTML='<div class="card-label">PAPER PORTFOLIO V2 · FORWARD ONLY</div>'+
      '<h3>Start a clean prospective portfolio</h3>'+
      '<p>Legacy Phase 8.1 records remain read-only and are excluded from V2 performance.</p>'+
      '<button id="startPaperPortfolio" class="primary-btn">START NEW PAPER PORTFOLIO</button>';
    $('#startPaperPortfolio')?.addEventListener('click',startPaperPortfolio);return;
  }
  const pos=p.positions||[],orders=p.pending_orders||[],journal=p.journal||[];
  const pendingBuy=orders.filter(x=>x.side==='BUY').length,pendingExit=orders.filter(x=>x.side==='SELL').length;
  const invested=(p.nav||0)-(p.cash||0);
  const eventLabel=x=>({BUY_SIGNAL:'BUY SIGNAL',BUY_FILLED:'BUY FILLED',HOLD:'HOLD',WEAKENING:'WEAKENING',EXIT_SIGNAL:'EXIT SIGNAL',EXIT_FILLED:'EXIT FILLED'}[x]||x||'—');
  const cards=[
    ['Portfolio ID',p.portfolio_id||'—'],['Started',p.start_session||'—'],['Starting run',p.start_production_run_id||'—'],
    ['Engine',p.app_version||'—'],['Portfolio value',fmtINR(p.nav||p.starting_capital||0)],['Cash',fmtINR(p.cash||0)],
    ['Invested value',fmtINR(invested)],['Realized P&L',fmtINR(p.realized_pnl||0)],['Unrealized P&L',fmtINR(p.unrealized_pnl||0)],
    ['Current positions',pos.length],['Pending entries',pendingBuy],['Pending exits',pendingExit]
  ].map(x=>'<div><span>'+escapeHtml(x[0])+'</span><strong>'+escapeHtml(String(x[1]))+'</strong></div>').join('');
  const positions=pos.map(x=>'<tr><td>'+escapeHtml(x.symbol)+'</td><td>'+escapeHtml(x.state)+'</td><td>'+x.qty+
    '</td><td>'+fmtINR(x.entry_price||0)+'</td><td>'+(x.last_price?fmtINR(x.last_price):'STALE MARK')+
    '</td><td>'+fmtINR(x.unrealized_pnl||0)+'</td></tr>').join('');
  const pending=orders.map(x=>'<tr><td>'+escapeHtml(x.symbol)+'</td><td>'+escapeHtml(x.side)+'</td><td>'+escapeHtml(x.state)+
    '</td><td>'+escapeHtml(x.signal_session||'')+'</td><td>'+escapeHtml(x.production_run_id||'')+'</td></tr>').join('');
  const events=journal.map(x=>'<tr><td>'+escapeHtml(x.market_session||'')+'</td><td>'+escapeHtml(eventLabel(x.event_type))+
    '</td><td>'+escapeHtml(x.symbol||x.decision||x.reason||'')+'</td><td>'+escapeHtml(x.production_run_id||'')+'</td></tr>').join('');
  const old=portfolios.length?portfolios.map(x=>escapeHtml((x.start_session||'')+' · '+x.portfolio_id+' · '+x.status)).join('<br>'):'None';
  el.innerHTML='<div class="card-label">PAPER PORTFOLIO V2 · FORWARD ONLY</div>'+
    '<div class="daily-flow-grid success">'+cards+'</div>'+
    '<div class="validation-actions"><button id="recordPaperToday" class="primary-btn">RECORD CURRENT PRODUCTION SESSION</button>'+
    '<button id="startPaperPortfolio" class="secondary-btn">START NEW PORTFOLIO</button></div>'+
    '<p class="muted">Entries and exits execute only at the next official session open. Re-running the same session/run is idempotent. Legacy V1 journals are not rewritten.</p>'+
    '<h3>Current Positions</h3><div class="table-wrap"><table><thead><tr><th>Stock</th><th>State</th><th>Qty</th><th>Entry</th><th>Last mark</th><th>Unrealized P&L</th></tr></thead><tbody>'+
    (positions||'<tr><td colspan="6">No open positions</td></tr>')+'</tbody></table></div>'+
    '<h3>Pending Orders</h3><div class="table-wrap"><table><thead><tr><th>Stock</th><th>Side</th><th>State</th><th>Signal session</th><th>Run</th></tr></thead><tbody>'+
    (pending||'<tr><td colspan="5">No pending orders</td></tr>')+'</tbody></table></div>'+
    '<h3>Trade Journal</h3><div class="table-wrap"><table><thead><tr><th>Session</th><th>Event</th><th>Stock / decision</th><th>Production run</th></tr></thead><tbody>'+
    (events||'<tr><td colspan="4">No V2 journal events yet</td></tr>')+'</tbody></table></div>'+
    '<h3>Previous V2 Portfolios</h3><p>'+old+'</p>'+
    '<div class="warning-note">Legacy Validation V1 remains preserved read-only and is excluded from every V2 P&L/return metric.</div>';
  $('#recordPaperToday')?.addEventListener('click',recordPaperToday);
  $('#startPaperPortfolio')?.addEventListener('click',startPaperPortfolio);
}
function v2Metric(v,formatter){return v==null?'NOT AVAILABLE':formatter(v)}
function renderValidationReplayIdle(){
  const el=$('#validationReplayPanel');if(!el)return;
  el.innerHTML='<div class="card-label">POINT-IN-TIME HISTORICAL SIMULATION</div>'+
    '<div class="warning-note">Historical Replay does not run automatically. Choose a period and click RUN POINT-IN-TIME REPLAY when you want to start the heavier simulation.</div>'+
    '<div class="validation-controls"><label>Period<select id="validationPeriod"><option>1M</option><option>3M</option><option selected>6M</option><option>1Y</option></select></label>'+
    '<label>Starting capital<input id="validationCapital" type="number" value="100000"></label>'+
    '<label>Slippage bps<input id="validationSlippage" type="number" value="10"></label>'+
    '<label>Transaction cost bps<input id="validationCost" type="number" value="5"></label>'+
    '<button class="primary-btn" id="runHistoricalReplay">RUN POINT-IN-TIME REPLAY</button></div>'+
    '<div class="daily-flow-grid"><div><span>Status</span><strong>NOT RUN YET</strong></div></div>'+
    '<p class="muted">Paper Portfolio remains independent and usable while replay is idle.</p>';
  $('#runHistoricalReplay')?.addEventListener('click',runHistoricalReplay);
}
function renderValidationReplay(r){
  const el=$('#validationReplayPanel');if(!el)return;r=r||{};
  const m=r.metrics||{},range=r.trustworthy_replayable_range||{},pit=r.pit_completeness||{};
  const sessionRows=(r.sessions||[]).map(s=>'<tr><td>'+escapeHtml(s.session||'')+'</td><td>'+escapeHtml(s.pit_status||'')+
    '</td><td>'+(s.reconstructed_symbols||0)+'/'+(s.universe_size||0)+'</td><td>'+(s.executable_buy_count||0)+
    '</td><td>'+(s.allocated_buy_count||0)+'</td><td>'+(s.portfolio_nav==null?'—':fmtINR(s.portfolio_nav))+
    '</td><td>'+(s.benchmark_nav==null?'—':fmtINR(s.benchmark_nav))+'</td><td>'+escapeHtml(s.valuation_quality||'')+'</td></tr>').join('');
  const requested=(r.requested_range?.start||'—')+' → '+(r.requested_range?.end||'—');
  const trusted=range.start?(range.start+' → '+range.end):'NOT REPLAYABLE';
  const cards=[
    ['Status',r.status||'—'],['Requested',requested],['Trustworthy range',trusted],['Replayable sessions',pit.replayable_sessions??0],
    ['Excluded sessions',pit.excluded_sessions??0],['Portfolio return',v2Metric(m.portfolio_return,fmtPctFraction)],
    ['NIFTY return',v2Metric(m.benchmark_return,fmtPctFraction)],['Excess return',v2Metric(m.excess_return,fmtPctFraction)],
    ['Max drawdown',v2Metric(m.maximum_drawdown,fmtPctFraction)],['BUY signals',m.buy_signals??0],
    ['Filled entries',m.filled_entries??0],['Filled exits',m.filled_exits??0],['Win rate',v2Metric(m.win_rate,fmtPctFraction)]
  ].map(x=>'<div><span>'+escapeHtml(x[0])+'</span><strong>'+escapeHtml(String(x[1]))+'</strong></div>').join('');
  el.innerHTML='<div class="card-label">POINT-IN-TIME HISTORICAL SIMULATION</div>'+
    '<div class="warning-note">Historical membership is not yet available, so replay uses the current universe and is explicitly marked CURRENT_UNIVERSE_SURVIVORSHIP_BIAS. No future filing or future price may enter a historical decision.</div>'+
    '<div class="validation-controls"><label>Period<select id="validationPeriod"><option>1M</option><option>3M</option><option selected>6M</option><option>1Y</option></select></label>'+
    '<label>Starting capital<input id="validationCapital" type="number" value="100000"></label>'+
    '<label>Slippage bps<input id="validationSlippage" type="number" value="10"></label>'+
    '<label>Transaction cost bps<input id="validationCost" type="number" value="5"></label>'+
    '<button class="primary-btn" id="runHistoricalReplay">RUN POINT-IN-TIME REPLAY</button></div>'+
    '<div class="daily-flow-grid success">'+cards+'</div>'+
    '<p class="muted">Execution: next official open · whole shares · no broker execution. Benchmark uses actual NIFTY history, never a flat placeholder.</p>'+
    '<div class="table-wrap"><table><thead><tr><th>Date</th><th>PIT status</th><th>Reconstructed</th><th>BUY</th><th>Allocated</th><th>Portfolio NAV</th><th>NIFTY NAV</th><th>Mark quality</th></tr></thead><tbody>'+
    (sessionRows||'<tr><td colspan="8">No replay sessions</td></tr>')+'</tbody></table></div>';
  $('#runHistoricalReplay')?.addEventListener('click',runHistoricalReplay);
}
async function runHistoricalReplay(){
  const period=$('#validationPeriod')?.value||'6M';
  const capital=Number($('#validationCapital')?.value||100000);
  const slip=Number($('#validationSlippage')?.value||10);
  const cost=Number($('#validationCost')?.value||5);
  busy(true,'Running point-in-time replay','Reconstructing historical LIVE_DECISION_V1 sessions without future evidence');
  try{
    const url='/api/validation/historical-replay?period='+encodeURIComponent(period)+'&starting_capital='+capital+
      '&benchmark=NIFTY%2050&slippage_bps='+slip+'&transaction_cost_bps='+cost;
    const r=await api(url,{method:'POST'});
    renderValidationReplay(r);toast('Point-in-time replay complete');
  }catch(e){validationError('Historical Replay V2 failed',e)}
  finally{busy(false)}
}

async function loadValidation(){
  // VALIDATION_V2_LAZY_LOAD: Paper state is lightweight and must never wait for replay.
  bindValidationTabs();
  renderValidationReplayIdle();
  setValidationTab('paper');
  $('#validationError')?.classList.add('hidden');
  try{
    const p=await api('/api/validation/paper-portfolio');
    renderValidationPaper(p);
  }catch(e){
    validationError('Paper Portfolio V2 failed',e);
  }
}
'''
js += "\n" + override + "\n"
front.write_text(js, encoding="utf-8")

css = root / "modern_ui" / "frontend" / "styles.css"
ctext = css.read_text(encoding="utf-8")
if ".validation-actions" not in ctext:
    ctext += "\n.validation-actions{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}.warning-note{margin:12px 0;padding:12px;border-radius:12px;background:rgba(245,158,11,.10);border:1px solid rgba(245,158,11,.25);font-size:12px;line-height:1.5}.muted{opacity:.7;font-size:12px;line-height:1.5}\n"
css.write_text(ctext, encoding="utf-8")

assert "PAPER PORTFOLIO V2" in front.read_text(encoding="utf-8")
assert "POINT-IN-TIME HISTORICAL SIMULATION" in front.read_text(encoding="utf-8")
assert "VALIDATION_V2_LAZY_LOAD" in front.read_text(encoding="utf-8")
print("0.14.12 Validation V2 UI override applied")
