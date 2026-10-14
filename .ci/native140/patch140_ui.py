from pathlib import Path
import os

root = Path(os.environ['SRE_ENGINE_ROOT']) / 'modern_ui/frontend'
p = root / 'app.js'
s = p.read_text(encoding='utf-8')

def replace(old, new):
    global s
    if old not in s: raise RuntimeError('UI patch point missing: ' + old[:70])
    s = s.replace(old,new,1)

replace('  const hero=actionable||watch;', '  const hero=actionable;')
replace("  const heroKind=actionable?'TOP OPPORTUNITY':watch?'TOP WATCH CANDIDATE':'NO ACTIONABLE OPPORTUNITY';", "  const heroKind=actionable?'TOP LIVE OPPORTUNITY':'NO ACTIONABLE OPPORTUNITY';")
replace('function evidenceStatus(item){', '''function evidenceStatus(item){
  if(item.live_decision){const x=item.live_decision;return {decision:x.final_action,production_basis:'LIVE_DECISION_V1',technical:x.technical_state,fundamental:x.business_health,combined:'DIAGNOSTIC ONLY'};}''')
replace("  if(f==='buy')", "  if(f==='momentum') rows=rows.filter(x=>x.live_decision?.momentum_thesis==='VALID');\n  if(f==='recovery') rows=rows.filter(x=>x.live_decision?.recovery_thesis==='VALID');\n  if(f==='avoid') rows=rows.filter(x=>String(x.opportunity_status).startsWith('AVOID'));\n  if(f==='buy')")
# The overview cards and Opportunities use the same evidence presentation.
replace('    <div class="opp-metric"><span>Expected</span>', '    ${liveEvidenceHtml(item.live_decision||item)}\n    <div class="opp-metric"><span>Expected</span>')
start=s.index('function renderOpportunityTable(items){')
end=s.index('\nasync function openStock',start)
s=s[:start]+'''function liveEvidenceHtml(x){
  if(!x||!x.final_action)return '<p>Live decision not available.</p>';
  const fields=[['Business health',x.business_health],['Earnings',x.earnings_direction],['Cash flow',x.cash_flow_state],['Balance sheet',x.balance_sheet_state],['Valuation',x.valuation_state],['Technical state',x.technical_state],['Fundamental events',x.fundamental_event_state],['Data quality',x.fundamental_data_quality],['Priority',x.priority],['Confidence',x.confidence]];
  return `<div class="evidence-split">${fields.map(([k,v])=>`<span>${escapeHtml(k)}: <strong>${escapeHtml(v||'UNAVAILABLE')}</strong></span>`).join('')}</div><p>${escapeHtml(x.thesis||'')}</p><small>Invalidation: ${escapeHtml(x.invalidation||'Evidence review required')}</small>`;
}
function renderOpportunityTable(items){
  const t=$('#opportunityTable');if(!t)return;
  t.innerHTML=(items||[]).map(i=>`<article class="panel-card" data-symbol="${escapeHtml(i.symbol)}"><h3>#${i.rank} ${escapeHtml(i.symbol)}</h3><strong>${escapeHtml(i.final_action||i.opportunity_status)}</strong><p>${escapeHtml(i.execution_status||'NOT EXECUTABLE')}</p>${liveEvidenceHtml(i.live_decision||i)}</article>`).join('')||'<p>No opportunities in this filter.</p>';
}
function renderLiveThesis(x){
  const el=$('#liveThesisPanel');if(!el)return;
  el.innerHTML='<h3>LIVE INVESTMENT THESIS</h3>'+(x?`<strong>${escapeHtml(x.final_action)}</strong><div class="technical-v2-grid"><section><h4>Momentum Thesis: ${escapeHtml(x.momentum_thesis)}</h4><p>${escapeHtml(x.momentum_reason)}</p></section><section><h4>Recovery Thesis: ${escapeHtml(x.recovery_thesis)}</h4><p>${escapeHtml(x.recovery_reason)}</p></section></div>${liveEvidenceHtml(x)}`:'<p>Run the daily analysis to create a live investment thesis.</p>');
}
''' +s[end:]
replace('renderPerformance(d.performance||{});', 'renderLiveThesis(d.live_decision); renderPerformance(d.performance||{});')
replace("$('#decisionReason').textContent=`Frozen engine confidence:", "$('#decisionReason').textContent=pred.live_decision?.thesis||`Legacy evidence confidence:")
replace("escapeHtml(b.reason_text||'')", "escapeHtml((b.thesis||b.reason_text||'')+' · Confidence '+(b.confidence||'UNAVAILABLE')+' · Risk '+(b.technical_state||'UNAVAILABLE'))")
s=s.replace('Official data freshness → frozen production run → shadow evidence → validation snapshot','Official data freshness → live Momentum and Recovery theses → validation snapshot')
s=s.replace('Using the same persisted combined recommendation run and frozen allocation policy','Allocating qualified live Momentum and Recovery opportunities within portfolio limits')
for field in ('technical_score', 'fundamental_score', 'combined_score'):
    s=s.replace(f'Number.isFinite(+x.{field})?', f'x.{field}!=null&&Number.isFinite(+x.{field})?')
s=s.replace('Math.min(100,Math.max(8,(+item.profit_probability||.45)*100))', 'item.profit_probability==null?0:Math.min(100,Math.max(0,+item.profit_probability*100))')
s=s.replace("String(c['HOLD-WEAKENING']||0)", "String((c.WEAKENING||0)+(c['HOLD-WEAKENING']||0))")
s=s.replace('escapeHtml(x.symbol)}</strong><span><em class="status-badge', 'escapeHtml(x.symbol)}<small>${escapeHtml((x.simulated?"Paper · ":"")+(x.strategy_style||"Legacy position"))}</small></strong><span><em class="status-badge')
p.write_text(s,encoding='utf-8')
p=root/'index.html';s=p.read_text(encoding='utf-8')
s=s.replace('<article id="technicalV2Panel"','<article id="liveThesisPanel" class="panel-card"></article>\n        <article id="technicalV2Panel"',1)
s=s.replace('data-opp-filter="buy">Buy candidates</button>','data-opp-filter="momentum">Momentum</button><button class="filter-pill" data-opp-filter="recovery">Recovery</button><button class="filter-pill" data-opp-filter="avoid">Avoid</button>',1)
p.write_text(s,encoding='utf-8')
print('0.14.0 thesis UI applied')
