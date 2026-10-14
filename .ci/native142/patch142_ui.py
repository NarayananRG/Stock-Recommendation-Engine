from pathlib import Path
import os
import re

front = Path(os.environ["SRE_ENGINE_ROOT"]) / "modern_ui/frontend"


def must_replace(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"{label}: missing patch point {old[:140]!r}")
    return text.replace(old, new, 1)


app = front / "app.js"
s = app.read_text(encoding="utf-8")

s = must_replace(
    s,
    '    ${liveEvidenceHtml(item.live_decision||item)}\\n    <div class="opp-metric"><span>Expected</span>',
    '    <div class="opp-metric"><span>Expected</span>',
    "remove long overview evidence",
)

old = '''function opportunityTopReason(x){
  const live=x.live_decision||x;return (live.reason_codes||[])[0]||live.thesis||'No active blocker';
}
'''
new = r'''const LIVE_REASON_LABELS={
  BUSINESS_EARNINGS_OR_EVENT_EVIDENCE_INSUFFICIENT:'Business / earnings evidence is incomplete',
  MOMENTUM_CONFIRMATION_INCOMPLETE:'Momentum confirmation is incomplete',
  BALANCE_SHEET_NOT_ACCEPTABLE_OR_UNAVAILABLE:'Balance-sheet evidence is missing or insufficient',
  CASH_FLOW_NOT_SUPPORTIVE_OR_UNAVAILABLE:'Cash-flow evidence is missing or not supportive',
  PIT_RELATIVE_VALUATION_UNAVAILABLE:'Historical PIT valuation comparison is unavailable',
  FINANCIAL_DOMAIN_PIT_SAFETY_INCOMPLETE:'Financial-sector PIT safety metrics are incomplete',
  DOWNSIDE_UNCONTROLLED_OR_UNAVAILABLE:'Downside-risk evidence is insufficient',
  FUNDAMENTALS_UNAVAILABLE:'Fundamental evidence is unavailable',
  FUNDAMENTAL_DETERIORATION:'Fundamental deterioration detected',
  VALUE_TRAP_RISK:'Value-trap risk detected'
};
function humanReason(code){
  const key=String(code||'').trim();
  if(!key)return 'No active blocker';
  if(LIVE_REASON_LABELS[key])return LIVE_REASON_LABELS[key];
  if(!/^[A-Z0-9_ -]+$/.test(key))return key;
  return key.toLowerCase().replaceAll('_',' ').replace(/\\b\\w/g,c=>c.toUpperCase());
}
function shortText(value,max=150){
  const text=String(value||'').replace(/\\s+/g,' ').trim();
  return text.length>max?text.slice(0,max-1).trim()+'...':text;
}
function opportunityTopReason(x){
  const live=x.live_decision||x;
  const code=(live.reason_codes||[])[0];
  return code?humanReason(code):shortText(live.thesis||'No active blocker',120);
}
'''
s = must_replace(s, old, new, "human-readable opportunity reasons")

start = s.find("function openOpportunityDetails(symbol){")
end = s.find("\\nfunction filteredOpportunityRows(){", start)
if start < 0 or end < 0:
    raise RuntimeError("opportunity drawer function boundaries missing")
drawer = r'''function openOpportunityDetails(symbol){
  const i=state.opportunityItems.find(x=>x.symbol===symbol);if(!i)return;const x=i.live_decision||i;
  const reasonCodes=[...(x.reason_codes||[])];
  const reasons=reasonCodes.slice(0,4).map(humanReason);
  const missing=[...(x.missing_evidence||[])];
  const evidence=[
    ['Business',x.business_health],['Earnings',x.earnings_direction],
    ['Cash flow',x.cash_flow_state],['Balance sheet',x.balance_sheet_state],
    ['Valuation',x.valuation_state],['Technical',x.technical_state],
    ['Events',x.fundamental_event_state],['Data quality',x.fundamental_data_quality]
  ];
  const why=reasons.length?reasons:[shortText(x.fundamental_narrative||x.thesis||'No additional explanation is available.',180)];
  const missingHtml=missing.length?`<ul class="clean-list">${missing.slice(0,8).map(v=>`<li>${escapeHtml(humanReason(v))}</li>`).join('')}</ul>`:'<p class="muted-copy">No missing evidence recorded.</p>';
  const rawCodes=reasonCodes.length?`<ul class="audit-codes">${reasonCodes.map(v=>`<li><code>${escapeHtml(v)}</code></li>`).join('')}</ul>`:'<p>No raw blocker codes.</p>';
  modalOpen(`${symbol} - ${x.final_action||i.opportunity_status}`,'LIVE DECISION',`
    <div class="opportunity-detail-v2">
      <div class="decision-summary-grid">
        <div><span>Decision</span><strong>${escapeHtml(x.final_action||i.opportunity_status||'-')}</strong></div>
        <div><span>Strategy</span><strong>${escapeHtml(x.strategy_style||x.primary_style||'NONE')}</strong></div>
        <div><span>Confidence</span><strong>${escapeHtml(x.confidence||'LOW')}</strong></div>
        <div><span>Priority</span><strong>${escapeHtml(x.priority||'LOW')}</strong></div>
        <div><span>Executable</span><strong>${x.executable===true?'YES':'NO'}</strong></div>
      </div>
      <div class="detail-theses clean-theses">
        <section><h4>Momentum thesis - ${escapeHtml(x.momentum_thesis||'-')}</h4><p>${escapeHtml(shortText(x.momentum_reason||'No momentum explanation available.',190))}</p></section>
        <section><h4>Recovery thesis - ${escapeHtml(x.recovery_thesis||'-')}</h4><p>${escapeHtml(shortText(x.recovery_reason||'No recovery explanation available.',190))}</p></section>
      </div>
      <h4>Evidence snapshot</h4>
      <div class="evidence-grid-v2">${evidence.map(([k,v])=>`<div><span>${escapeHtml(k)}</span><strong>${escapeHtml(v||'UNAVAILABLE')}</strong></div>`).join('')}</div>
      <h4>Why this decision?</h4>
      <ul class="clean-list">${why.map(v=>`<li>${escapeHtml(v)}</li>`).join('')}</ul>
      <h4>What is missing?</h4>${missingHtml}
      <h4>What would change the decision?</h4>
      <p>${escapeHtml(shortText(x.invalidation||'A material change in the supporting evidence requires a fresh review.',260))}</p>
      <div class="drawer-actions"><button class="primary-btn" data-open-stock-intelligence="${escapeHtml(symbol)}">Open Stock Intelligence</button></div>
      <details class="diagnostic-details"><summary>Diagnostics / audit</summary>
        <h5>Raw reason codes</h5>${rawCodes}
        <h5>Raw evidence</h5><pre>${escapeHtml(JSON.stringify(x.evidence||{},null,2))}</pre>
      </details>
    </div>`);
}
'''
s = s[:start] + drawer + s[end:]

old = "async function loadPage(name){if(name==='portfolio')return loadPortfolio();if(name==='capital')return loadCapitalDefaults();if(name==='today')return loadToday();if(name==='history')return loadHistory();if(name==='system')return loadSystem();if(name==='help')return loadGlossary($('#glossarySearch')?.value||'');if(name==='opportunities'){const d=await api('/api/opportunities?limit=200');state.opportunityItems=d.items||[];state.oppPage=1;if(d.run)syncRunInputs(d.run);applyOpportunityFilter();}}"
new = '''async function loadPage(name){await refreshUiSessionTruth();if(name==='portfolio')return loadPortfolio();if(name==='capital')return loadCapitalDefaults();if(name==='today')return loadToday();if(name==='history')return loadHistory();if(name==='system')return loadSystem();if(name==='help')return loadGlossary($('#glossarySearch')?.value||'');if(name==='opportunities'){const d=await api('/api/opportunities?limit=200');state.opportunityItems=d.items||[];state.uiSessionTruth=d.ui_state||state.uiSessionTruth;state.oppPage=1;if(d.run)syncRunInputs(d.run);applyOpportunityFilter();repairOverviewUx();}}'''
s = must_replace(s, old, new, "canonical page load")

prefix = "function renderCapitalPlan(d){const s=d.capital_summary||{},buys=d.new_buys||[],lc=s.live_lane_counts||{},blockers=s.top_blockers||{};"
if prefix not in s:
    raise RuntimeError("capital blocker UX patch point missing")
replacement = '''function renderCapitalPlan(d){const s=d.capital_summary||{},buys=d.new_buys||[],lc=s.live_lane_counts||{},blockers=s.top_blockers||{},universe=+s.live_universe_size||200;if($('#capitalLiveSummary')){const top=Object.entries(blockers).slice(0,5);$('#capitalLiveSummary').innerHTML=`<div class="capital-live-header"><strong>LIVE_DECISION_V1</strong><span>Momentum BUY ${lc.momentum_buy||0}</span><span>Recovery BUY ${lc.recovery_buy||0}</span><span>Both ${lc.both||0}</span><span>Watch ${lc.watch||0}</span><span>Avoid ${lc.avoid||0}</span><span>No opportunity ${lc.no_opportunity||0}</span></div><div class="capital-zero-note">${buys.length?'Qualified BUY opportunities are available.':'No stocks currently satisfy LIVE_DECISION_V1 BUY requirements. Capital remains in cash rather than forcing a trade.'}</div>${top.length?`<div class="blocker-summary"><b>Why no capital was deployed</b><small>Stocks affected; one stock may appear under more than one reason.</small><div class="blocker-row blocker-head"><span>Blocking reason</span><span>Stocks affected</span><span>Universe</span></div>${top.map(([code,count])=>`<div class="blocker-row"><span>${escapeHtml(humanReason(code))}</span><strong>${count}</strong><span>${universe?((100*count/universe).toFixed(1)+'%'):'-'}</span></div>`).join('')}</div>`:''}`;}'''
s = s.replace(prefix, replacement, 1)

runtime = r'''
async function refreshUiSessionTruth(){
  try{
    state.uiSessionTruth=await api('/api/ui-consistency');
    repairOverviewUx();
    return state.uiSessionTruth;
  }catch(_){return state.uiSessionTruth||null}
}
function leafTextNodes(match){
  return Array.from(document.querySelectorAll('span,strong,p,div,h2,h3')).filter(el=>el.children.length===0&&match(el.textContent.trim()));
}
function repairOverviewUx(){
  const truth=state.uiSessionTruth;if(!truth)return;
  const labels=leafTextNodes(t=>t.toUpperCase()==='LATEST OFFICIAL SESSION');
  labels.forEach(label=>{
    const box=label.parentElement;if(!box)return;
    const date=Array.from(box.querySelectorAll('strong,b,span,div')).find(el=>/^\\d{4}-\\d{2}-\\d{2}$/.test(el.textContent.trim()));
    if(date&&truth.latest_official_session)date.textContent=truth.latest_official_session;
  });
  if(truth.analysis_complete){
    leafTextNodes(t=>t==='NO RESULT').forEach(el=>el.textContent='ANALYSIS COMPLETE');
  }
  const lc=truth.lane_counts||{},watch=+lc.watch||0,buy=(+lc.momentum_buy||0)+(+lc.recovery_buy||0)+(+lc.both||0);
  leafTextNodes(t=>t.includes('No executable BUY or WATCH candidate')).forEach(el=>{
    el.textContent=buy===0?(watch?`No executable BUY opportunity today. ${watch} stocks remain on WATCH.`:'No executable BUY opportunity in the active run.'):'Executable BUY opportunities are available.';
  });
  leafTextN÷ž<r«²ÚîÆ­y