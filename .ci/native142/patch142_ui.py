# -*- coding: utf-8 -*-
from pathlib import Path
import os

front = Path(os.environ["SRE_ENGINE_ROOT"]) / "modern_ui/frontend"
app = front / "app.js"
s = app.read_text(encoding="utf-8")


def must_replace(old: str, new: str, label: str) -> None:
    global s
    if old not in s:
        raise RuntimeError(f"{label}: missing patch point {old[:120]!r}")
    s = s.replace(old, new, 1)


must_replace(
    '    ${liveEvidenceHtml(item.live_decision||item)}\n    <div class="opp-metric"><span>Expected</span>',
    '    <div class="opp-metric"><span>Expected</span>',
    "remove long overview evidence",
)

old_reason = """function opportunityTopReason(x){
  const live=x.live_decision||x;return (live.reason_codes||[])[0]||live.thesis||'No active blocker';
}
"""
new_reason = r"""const LIVE_REASON_LABELS={
  BUSINESS_EARNINGS_OR_EVENT_EVIDENCE_INSUFFICIENT:'Business / earnings evidence is incomplete',
  MOMENTUM_CONFIRMATION_INCOMPLETE:'Momentum confirmation is incomplete',
  BALANCE_SHEET_NOT_ACCEPTABLE_OR_UNAVAILABLE:'Balance-sheet evidence is missing or insufficient',
  CASH_FLOW_NOT_SUPPORTIVE_OR_UNAVAILABLE:'Cash-flow evidence is missing or not supportive',
  PIT_RELATIVE_VALUATION_UNAVAILABLE:'Historical PIT valuation comparison is unavailable',
  FINANCIAL_DOMAIN_PIT_SAFETY_INCOMPLETE:'Financial-sector PIT safety metrics are incomplete',
  DOWNSIDE_UNCONTROLLED_OR_UNAVAILABLE:'Downside-risk evidence is insufficient',
  FUNDAMENTALS_UNAVAILABLE:'Fundamental evidence is unavailable'
};
function humanReason(code){
  const key=String(code||'').trim();
  if(!key)return 'No active blocker';
  if(LIVE_REASON_LABELS[key])return LIVE_REASON_LABELS[key];
  if(!/^[A-Z0-9_ -]+$/.test(key))return key;
  return key.toLowerCase().replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());
}
function shortText(value,max=150){
  const text=String(value||'').replace(/\s+/g,' ').trim();
  return text.length>max?text.slice(0,max-3).trim()+'...':text;
}
function opportunityTopReason(x){
  const live=x.live_decision||x,code=(live.reason_codes||[])[0];
  return code?humanReason(code):shortText(live.thesis||'No active blocker',120);
}
"""
must_replace(old_reason, new_reason, "human-readable reasons")

start = s.find("function openOpportunityDetails(symbol){")
end = s.find("\nfunction filteredOpportunityRows(){", start)
if start < 0 or end < 0:
    raise RuntimeError("opportunity detail boundaries missing")
drawer = r"""function openOpportunityDetails(symbol){
  const i=state.opportunityItems.find(x=>x.symbol===symbol);if(!i)return;const x=i.live_decision||i;
  const codes=[...(x.reason_codes||[])], missing=[...(x.missing_evidence||[])];
  const evidence=[['Business',x.business_health],['Earnings',x.earnings_direction],['Cash flow',x.cash_flow_state],['Balance sheet',x.balance_sheet_state],['Valuation',x.valuation_state],['Technical',x.technical_state],['Events',x.fundamental_event_state],['Data quality',x.fundamental_data_quality]];
  const why=(codes.length?codes.slice(0,4).map(humanReason):[shortText(x.thesis||'No additional explanation available.',180)]);
  modalOpen(symbol+' - '+(x.final_action||i.opportunity_status),'LIVE DECISION',`
    <div class="opportunity-detail-v2">
      <div class="decision-summary-grid">
        <div><span>Decision</span><strong>${escapeHtml(x.final_action||i.opportunity_status||'-')}</strong></div>
        <div><span>Strategy</span><strong>${escapeHtml(x.strategy_style||x.primary_style||'NONE')}</strong></div>
        <div><span>Confidence</span><strong>${escapeHtml(x.confidence||'LOW')}</strong></div>
        <div><span>Priority</span><strong>${escapeHtml(x.priority||'LOW')}</strong></div>
        <div><span>Executable</span><strong>${x.executable===true?'YES':'NO'}</strong></div>
      </div>
      <div class="detail-theses clean-theses">
        <section><h4>Momentum thesis - ${escapeHtml(x.momentum_thesis||'-')}</h4><p>${escapeHtml(shortText(x.momentum_reason||'No momentum explanation available.',180))}</p></section>
        <section><h4>Recovery thesis - ${escapeHtml(x.recovery_thesis||'-')}</h4><p>${escapeHtml(shortText(x.recovery_reason||'No recovery explanation available.',180))}</p></section>
      </div>
      <h4>Evidence snapshot</h4>
      <div class="evidence-grid-v2">${evidence.map(([k,v])=>`<div><span>${escapeHtml(k)}</span><strong>${escapeHtml(v||'UNAVAILABLE')}</strong></div>`).join('')}</div>
      <h4>Why this decision?</h4><ul class="clean-list">${why.map(v=>`<li>${escapeHtml(v)}</li>`).join('')}</ul>
      <h4>What is missing?</h4>${missing.length?`<ul class="clean-list">${missing.slice(0,8).map(v=>`<li>${escapeHtml(humanReason(v))}</li>`).join('')}</ul>`:'<p>No missing evidence recorded.</p>'}
      <h4>What would change the decision?</h4><p>${escapeHtml(shortText(x.invalidation||'A material change in supporting evidence requires a fresh review.',240))}</p>
      <button class="primary-btn" data-open-stock-intelligence="${escapeHtml(symbol)}">Open Stock Intelligence</button>
      <details class="diagnostic-details"><summary>Diagnostics / audit</summary>
        <h5>Raw reason codes</h5><pre>${escapeHtml(codes.join('\n')||'None')}</pre>
        <h5>Raw evidence</h5><pre>${escapeHtml(JSON.stringify(x.evidence||{},null,2))}</pre>
      </details>
    </div>`);
}
"""
s = s[:start] + drawer + s[end:]

prefix = "function renderCapitalPlan(d){const s=d.capital_summary||{},buys=d.new_buys||[],lc=s.live_lane_counts||{},blockers=s.top_blockers||{};"
pos = s.find(prefix)
if pos < 0:
    raise RuntimeError("capital summary patch point missing")
cut = s.find(";", pos + len(prefix))
old_cap = s[pos:cut+1]
new_cap = r"""function renderCapitalPlan(d){const s=d.capital_summary||{},buys=d.new_buys||[],lc=s.live_lane_counts||{},blockers=s.top_blockers||{},universe=+s.live_universe_size||200;if($('#capitalLiveSummary')){const top=Object.entries(blockers).slice(0,5);$('#apitalLiveSummary').innerHTML=`<div class="capital-live-header"><strong>LIVE_DECISION_V1</strong><span>Momentum BUY ${lc.momentum_buy||0}</span><span>Recovery BUY ${lc.recovery_buy||0}</span><span>Both ${lc.both||0}</span><span>Watch ${lc.watch||0}</span><span>Avoid ${lc.avoid||0}</span><span>No opportunity ${lc.no_opportunity||0}</span></div><div class="capital-zero-note">${buys.length?'Qualified BUY opportunities are available.':'No stocks currently satisfy LIVE_DECISION_V1 BUY requirements. Capital remains in cash rather than forcing a trade.'}</div>${top.length?`<div class="blocker-summary"><b>Why no capital was deployed</b><small>Stocks affected; one stock may appear under more than one reason.</small><div class="blocker-row blocker-head"><span>Blocking reason</span><span>Stocks affected</span><span>Universe</span></div>${top.map(([code,count])=>`<div class="blocker-row"><span>${escapeHtml(humanReason(code))}</span><strong>${count}</strong><span>${universe?((100*count/universe).toFixed(1)+'%'):'-'}</span></div>`).join('')}</div>`:'}`;/}"""
s = s.replace(old_cap, new_cap, 1)

runtime = r"""
async function refreshUiSessionTruth(){
  try{state.uiSessionTruth=await api('/api/ui-consistency');repairOverviewUx();return state.uiSessionTruth}
  catch(_){return state.uiSessionTruth||null}
}
function leafTextN÷ž<r«²ÚîÆ­y