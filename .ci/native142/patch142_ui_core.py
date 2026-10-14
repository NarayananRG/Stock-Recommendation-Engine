from pathlib import Path
import os

front=Path(os.environ['SRE_ENGINE_ROOT'])/'modern_ui/frontend'
app=front/'app.js'
s=app.read_text(encoding='utf-8')

old='    ${liveEvidenceHtml(item.live_decision||item)}\n    <div class="opp-metric"><span>Expected</span>'
if old not in s: raise RuntimeError('overview evidence patch point missing')
s=s.replace(old,'    <div class="opp-metric"><span>Expected</span>',1)

old="""function opportunityTopReason(x){
  const live=x.live_decision||x;return (live.reason_codes||[])[0]||live.thesis||'No active blocker';
}
"""
new=r"""const LIVE_REASON_LABELS={BUSINESS_EARNINGS_OR_EVENT_EVIDENCE_INSUFFICIENT:'Business / earnings evidence is incomplete',MOMENTUM_CONFIRMATION_INCOMPLETE:'Momentum confirmation is incomplete',BALANCE_SHEET_NOT_ACCEPTABLE_OR_UNAVAILABLE:'Balance-sheet evidence is missing or insufficient',CASH_FLOW_NOT_SUPPORTIVE_OR_UNAVAILABLE:'Cash-flow evidence is missing or not supportive',PIT_RELATIVE_VALUATION_UNAVAILABLE:'Historical PIT valuation comparison is unavailable',FINANCIAL_DOMAIN_PIT_SAFETY_INCOMPLETE:'Financial-sector PIT safety metrics are incomplete',DOWNSIDE_UNCONTROLLED_OR_UNAVAILABLE:'Downside-risk evidence is insufficient',FUNDAMENTALS_UNAVAILABLE:'Fundamental evidence is unavailable'};
function humanReason(code){const k=String(code||'').trim();if(!k)return 'No active blocker';if(LIVE_REASON_LABELS[k])return LIVE_REASON_LABELS[k];if(!/^[A-Z0-9_ -]+$/.test(k))return k;return k.toLowerCase().replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase())}
function shortText(v,n=160){const t=String(v||'').replace(/\s+/g,' ').trim();return t.length>n?t.slice(0,n-3)+'...':t}
function opportunityTopReason(x){const y=x.live_decision||x,c=(y.reason_codes||[])[0];return c?humanReason(c):shortText(y.thesis||'No active blocker',120)}
"""
if old not in s: raise RuntimeError('reason mapper patch point missing')
s=s.replace(old,new,1)

start=s.find('function openOpportunityDetails(symbol){')
end=s.find('\nfunction filteredOpportunityRows(){',start)
if start<0 or end<0: raise RuntimeError('drawer boundaries missing')
drawer=r"""function openOpportunityDetails(symbol){
 const i=state.opportunityItems.find(x=>x.symbol===symbol);if(!i)return;const x=i.live_decision||i,codes=x.reason_codes||[],miss=x.missing_evidence||[];
 const ev=[['Business',x.business_health],['Earnings',x.earnings_direction],['Cash flow',x.cash_flow_state],['Balance sheet',x.balance_sheet_state],['Valuation',x.valuation_state],['Technical',x.technical_state],['Events',x.fundamental_event_state],['Data quality',x.fundamental_data_quality]];
 modalOpen(symbol+' - '+(x.final_action||i.opportunity_status),'LIVE DECISION',`<div class="opportunity-detail-v2"><div class="decision-summary-grid"><div><span>Decision</span><strong>${escapeHtml(x.final_action||'-')}</strong></div><div><span>Strategy</span><strong>${escapeHtml(x.strategy_style||'NONE')}</strong></div><div><span>Confidence</span><strong>${escapeHtml(x.confidence||'LOW')}</strong></div><div><span>Priority</span><strong>${escapeHtml(x.priority||'LOW')}</strong></div><div><span>Executable</span><strong>${x.executable===true?'YES':'NO'}</strong></div></div><div class="detail-theses clean-theses"><section><h4>Momentum thesis - ${escapeHtml(x.momentum_thesis||'-')}</h4><p>${escapeHtml(shortText(x.momentum_reason,180))}</p></section><section><h4>Recovery thesis - ${escapeHtml(x.recovery_thesis||'-')}</h4><p>${escapeHtml(shortText(x.recovery_reason,180))}</p></section></div><h4>Evidence snapshot</h4><div class="evidence-grid-v2">${ev.map(([k,v])=>`<div><span>${k}</span><strong>${escapeHtml(v||'UNAVAILABLE')}</strong></div>`).join('')}</div><h4>Why this decision?</h4><ul class="clean-list">${(codes.slice(0,4).map(humanReason)).map(v=>`<li>${escapeHtml(v)}</li>`).join('')||'<li>No active blocker</li>'}</ul><h4>What is missing?</h4>${miss.length?`<ul class="clean-list">${miss.slice(0,8).map(v=>`<li>${escapeHtml(humanReason(v))}</li>`).join('')}</ul>`:'<p>No missing evidence recorded.</p>'}<h4>What would change the decision?</h4><p>${escapeHtml(shortText(x.invalidation||'A material change in supporting evidence requires review.',240))}</p><button class="primary-btn" data-open-stock-intelligence="${escapeHtml(symbol)}">Open Stock Intelligence</button><details class="diagnostic-details"><summary>Diagnostics / audit</summary><pre>${escapeHtml(codes.join('\n')||'No raw codes')}</pre><pre>${escapeHtml(JSON.stringify(x.evidence||{},null,2))}</pre></details></div>`)
}
"""
s=s[:start]+drawer+s[end:]
app.write_text(s,encoding='utf-8')
print('0.14.2 UI core repair applied')
