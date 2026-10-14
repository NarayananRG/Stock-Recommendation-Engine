from pathlib import Path
import os

front = Path(os.environ["SRE_ENGINE_ROOT"]) / "modern_ui" / "frontend"
app = front / "app.js"
s = app.read_text(encoding="utf-8")

helper_marker = "function renderOpportunityTable(items){"
if helper_marker not in s:
    raise RuntimeError("opportunity table marker missing")

if "function decisionEvidenceSummary(" not in s:
    helper = r'''function decisionEvidenceSummary(x){
  const fields=[['Business',x.business_health],['Earnings',x.earnings_direction],['Cash flow',x.cash_flow_state],['Balance sheet',x.balance_sheet_state],['Valuation',x.valuation_state],['Events',x.fundamental_event_state]];
  const unavailable=v=>{const z=String(v||'').trim().toUpperCase();return !z||z.includes('UNAVAILABLE')||z.includes('UNKNOWN')||z.includes('MISSING')||z.includes('INSUFFICIENT_COVERAGE')};
  const available=fields.filter(([,v])=>!unavailable(v)).length;
  return {label:`${available}/6 domains reported`,detail:fields.map(([k,v])=>`${k}: ${v||'UNAVAILABLE'}`).join(' · ')};
}
function decisionBasisText(x){
  const a=String(x.final_action||'').toUpperCase();
  if(a.includes('BUY'))return 'Qualified by live BUY rules';
  if(a.startsWith('WATCH'))return 'Thesis present; qualification incomplete';
  if(a.startsWith('AVOID'))return 'Risk or evidence gate failed';
  if(a==='NO OPPORTUNITY')return 'No live strategy qualified';
  return 'Live decision evidence';
}
'''
    s = s.replace(helper_marker, helper + helper_marker, 1)

start = s.find("function renderOpportunityTable(items){")
end = s.find("\nfunction openOpportunityDetails(symbol){", start)
if start < 0 or end < 0:
    raise RuntimeError("opportunity table boundaries missing")

render = r'''function renderOpportunityTable(items){
  const t=$('#opportunityTable');if(!t)return;
  const head=`<div class="opportunity-row opportunity-head"><span>Rank</span><span>Stock</span><span>Final action</span><span>Style</span><span>Evidence</span><span>Technical</span><span>Confidence</span><span>Executable</span><span>Why</span><span></span></div>`;
  const body=(items||[]).map(i=>{const x=i.live_decision||i,e=decisionEvidenceSummary(x);return `<div class="opportunity-row"><span>#${i.rank??'—'}</span><button class="stock-link" data-symbol="${escapeHtml(i.symbol)}">${escapeHtml(i.symbol)}</button><strong>${escapeHtml(x.final_action||i.opportunity_status||'—')}</strong><span>${escapeHtml(x.strategy_style||x.primary_style||'—')}</span><span class="evidence-cell" title="${escapeHtml(e.detail)}"><b>${escapeHtml(e.label)}</b><small>${escapeHtml(decisionBasisText(x))}</small></span><span>${escapeHtml(x.technical_state||'UNAVAILABLE')}</span><span>${escapeHtml(x.confidence||'LOW')}</span><span>${x.executable===true&&(+i.executable_qty||0)>0?'YES':'NO'}</span><span class="reason-cell" title="${escapeHtml(opportunityTopReason(i))}">${escapeHtml(opportunityTopReason(i))}</span><button class="mini-btn" data-opportunity-details="${escapeHtml(i.symbol)}">Details</button></div>`}).join('');
  t.innerHTML=head+(body||'<div class="opportunity-empty">No opportunities in this filter.</div>');
}
'''
s = s[:start] + render + s[end:]

detail_anchor = '</div><div class="detail-theses clean-theses">'
if detail_anchor not in s:
    raise RuntimeError("decision detail insertion point missing")
detail_note = '</div><div class="decision-contract-note"><strong>Decision contract</strong><span>LIVE_DECISION_V1 determines BUY / WATCH / AVOID from the evidence gates. Desired return is planning context only; it cannot upgrade a stock. Technical READY alone is not a BUY.</span></div><div class="detail-theses clean-theses">'
s = s.replace(detail_anchor, detail_note, 1)

capital_old = "Qualified BUY opportunities are available."
capital_new = "Qualified BUY opportunities are available. Position count is qualification-driven; the engine does not force five stocks or deploy cash merely because budget is available."
if capital_old not in s:
    raise RuntimeError("capital qualification wording missing")
s = s.replace(capital_old, capital_new, 1)

if "function installDecisionGuide()" not in s:
    guide = r'''
function installDecisionGuide(){
  const table=$('#opportunityTable');if(!table||$('#decisionGuide'))return;
  const box=document.createElement('details');box.id='decisionGuide';box.className='decision-guide';
  box.innerHTML=`<summary>How to read LIVE_DECISION_V1</summary><div class="decision-guide-grid"><section><strong>BUY vs WATCH</strong><p>BUY means the live strategy requirements are satisfied. WATCH means a thesis exists but one or more qualification requirements remain incomplete.</p></section><section><strong>Technical vs fundamentals</strong><p>Technical READY alone is not a BUY. Fundamental coverage shows which business, earnings, cash-flow, balance-sheet, valuation and event domains are actually reported.</p></section><section><strong>Analogue counts</strong><p>Historical analogue pool means all eligible past comparison cases. Matched analogues are the smaller subset selected because they resemble the current setup.</p></section><section><strong>Capital plan</strong><p>Budget does not force a stock count. Even for ₹1,00,000 the engine will not manufacture five recommendations if fewer stocks qualify.</p></section><section><strong>Target return</strong><p>Your desired return affects planning context only. It is not used to turn a WATCH or AVOID into a BUY.</p></section><section><strong>Missing evidence</strong><p>Missing or unavailable evidence stays visible and conservative; the app does not fabricate a fundamental signal to complete the screen.</p></section></div>`;
  table.parentElement.insertBefore(box,table);
}
document.addEventListener('DOMContentLoaded',()=>setTimeout(installDecisionGuide,450));
document.addEventListener('click',e=>{if(e.target.closest?.('.nav-item'))setTimeout(installDecisionGuide,120)},true);
'''
    s += "\n" + guide + "\n"

app.write_text(s, encoding="utf-8")

styles = front / "styles.css"
css = styles.read_text(encoding="utf-8")
css += r'''
/* 0.14.3 decision clarity UX */
.opportunity-row{grid-template-columns:48px 82px minmax(145px,1.1fr) 105px minmax(155px,1.15fr) 92px 78px 72px minmax(210px,1.55fr) 58px;min-width:1120px}
.evidence-cell{display:flex;flex-direction:column;gap:2px;min-width:0}.evidence-cell b{font-size:9.5px}.evidence-cell small{font-size:8.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.decision-contract-note{display:flex;flex-direction:column;gap:4px;margin:0 0 14px;padding:11px 12px;border:1px solid var(--line2);border-radius:10px;background:#f7f8fc}.decision-contract-note span{color:var(--muted)}
.decision-guide{margin:8px 0 14px;border:1px solid var(--line2);border-radius:12px;background:#fbfbfd;padding:0 12px}.decision-guide summary{cursor:pointer;padding:11px 0;font-size:10px;font-weight:800}.decision-guide-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;padding:0 0 12px}.decision-guide-grid section{border:1px solid var(--line2);border-radius:9px;background:white;padding:10px}.decision-guide-grid strong{font-size:9.5px}.decision-guide-grid p{margin:4px 0 0;font-size:9px;line-height:1.45;color:var(--muted)}
@media(max-width:900px){.decision-guide-grid{grid-template-columns:1fr}}
'''
styles.write_text(css, encoding="utf-8")
print("0.14.3 decision clarity UX applied")
