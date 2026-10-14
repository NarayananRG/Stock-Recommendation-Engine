from pathlib import Path
import os


front = Path(os.environ["SRE_ENGINE_ROOT"]) / "modern_ui/frontend"


def replace(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"{label}: missing patch point {old[:100]!r}")
    return text.replace(old, new, 1)


app = front / "app.js"
s = app.read_text(encoding="utf-8")
s = replace(s,
'''const state = { page:'dashboard', stock:null, symbols:[], dashboard:null, chart:null, previousPage:'dashboard', opportunityItems:[], oppFilter:'all', portfolio:null, capitalPlan:null, today:null, dataSource:null, activeRun:null };''',
'''const state = { page:'dashboard', stock:null, symbols:[], dashboard:null, chart:null, previousPage:'dashboard', opportunityItems:[], oppFilter:'all', oppSearch:'', oppSort:'rank', oppSortDir:'asc', oppPage:1, oppPageSize:25, portfolio:null, capitalPlan:null, today:null, dataSource:null, activeRun:null };''', "state")
s = replace(s, '  const opps=data.opportunities||[]; state.opportunityItems=opps;',
            "  const opps=data.opportunities||[]; if(state.page!=='opportunities'&&!state.opportunityItems.length)state.opportunityItems=opps;",
            "dashboard summary isolation")

start = s.index("function liveEvidenceHtml(x){")
end = s.index("\nfunction renderLiveThesis", start)
opportunity_ui = r'''function liveEvidenceHtml(x){
  if(!x||!x.final_action)return '<p>Live decision not available.</p>';
  const fields=[['Business Health',x.business_health],['Earnings Direction',x.earnings_direction],['Cash Flow',x.cash_flow_state],['Balance Sheet',x.balance_sheet_state],['Valuation',x.valuation_state],['Technical State',x.technical_state],['Fundamental Event State',x.fundamental_event_state],['Data Quality',x.fundamental_data_quality],['Priority',x.priority],['Confidence',x.confidence]];
  return `<div class="evidence-split">${fields.map(([k,v])=>`<span>${escapeHtml(k)}: <strong>${escapeHtml(v||'UNAVAILABLE')}</strong></span>`).join('')}</div><p>${escapeHtml(x.thesis||'')}</p><small>Invalidation: ${escapeHtml(x.invalidation||'Evidence review required')}</small>`;
}
function opportunityCategory(x){
  const a=String(x.final_action||x.opportunity_status||'').toUpperCase();
  if(a==='MOMENTUM BUY')return 'momentum';if(a==='RECOVERY BUY')return 'recovery';if(a==='MOMENTUM + RECOVERY BUY')return 'both';
  if(a.startsWith('WATCH'))return 'watch';if(a.startsWith('AVOID'))return 'avoid';if(a==='NO OPPORTUNITY')return 'no-opportunity';return 'other';
}
function opportunityCounts(rows){
  const c={all:rows.length,momentum:0,recovery:0,both:0,watch:0,avoid:0,'no-opportunity':0,executable:0};
  rows.forEach(x=>{const k=opportunityCategory(x);if(k in c)c[k]++;if(x.executable===true&&(+x.executable_qty||0)>0)c.executable++;});return c;
}
function renderOpportunityFilters(){
  const c=opportunityCounts(state.opportunityItems);$$('[data-opp-filter]').forEach(b=>{const label=b.dataset.label||b.textContent.replace(/\s+\d+$/,'').trim();b.dataset.label=label;b.textContent=`${label} ${c[b.dataset.oppFilter]||0}`;});
}
function opportunityTopReason(x){
  const live=x.live_decision||x;return (live.reason_codes||[])[0]||live.thesis||'No active blocker';
}
function renderOpportunityTable(items){
  const t=$('#opportunityTable');if(!t)return;
  const head=`<div class="opportunity-row opportunity-head"><span>Rank</span><span>Stock</span><span>Final action</span><span>Style</span><span>Business</span><span>Earnings</span><span>Valuation</span><span>Technical</span><span>Confidence</span><span>Executable</span><span>Top reason</span><span></span></div>`;
  const body=(items||[]).map(i=>{const x=i.live_decision||i;return `<div class="opportunity-row"><span>#${i.rank??'—'}</span><button class="stock-link" data-symbol="${escapeHtml(i.symbol)}">${escapeHtml(i.symbol)}</button><strong>${escapeHtml(x.final_action||i.opportunity_status||'—')}</strong><span>${escapeHtml(x.strategy_style||x.primary_style||'—')}</span><span>${escapeHtml(x.business_health||'UNAVAILABLE')}</span><span>${escapeHtml(x.earnings_direction||'UNAVAILABLE')}</span><span>${escapeHtml(x.valuation_state||'UNAVAILABLE')}</span><span>${escapeHtml(x.technical_state||'UNAVAILABLE')}</span><span>${escapeHtml(x.confidence||'LOW')}</span><span>${x.executable===true&&(+i.executable_qty||0)>0?'YES':'NO'}</span><span class="reason-cell" title="${escapeHtml(opportunityTopReason(i))}">${escapeHtml(opportunityTopReason(i))}</span><button class="mini-btn" data-opportunity-details="${escapeHtml(i.symbol)}">Details</button></div>`}).join('');
  t.innerHTML=head+(body||'<div class="opportunity-empty">No opportunities in this filter.</div>');
}
function openOpportunityDetails(symbol){
  const i=state.opportunityItems.find(x=>x.symbol===symbol);if(!i)return;const x=i.live_decision||i;
  const missing=(x.missing_evidence||[]).length?`<ul>${x.missing_evidence.map(v=>`<li>${escapeHtml(v)}</li>`).join('')}</ul>`:'<p>No missing evidence recorded.</p>';
  const reasons=(x.reason_codes||[]).length?`<ul>${x.reason_codes.map(v=>`<li>${escapeHtml(v)}</li>`).join('')}</ul>`:'<p>No blocker reason codes.</p>';
  modalOpen(`${symbol} · ${x.final_action||i.opportunity_status}`,'LIVE DECISION',`<div class="opportunity-detail"><div class="detail-theses"><section><h4>Momentum Thesis · ${escapeHtml(x.momentum_thesis||'—')}</h4><p>${escapeHtml(x.momentum_reason||'—')}</p></section><section><h4>Recovery Thesis · ${escapeHtml(x.recovery_thesis||'—')}</h4><p>${escapeHtml(x.recovery_reason||'—')}</p></section></div>${liveEvidenceHtml(x)}<h4>Why</h4><p>${escapeHtml(x.fundamental_narrative||x.thesis||'—')}</p><h4>Missing evidence</h4>${missing}<h4>Blockers</h4>${reasons}<h4>Invalidation</h4><p>${escapeHtml(x.invalidation||'—')}</p><details><summary>Raw evidence</summary><pre>${escapeHtml(JSON.stringify(x.evidence||{},null,2))}</pre></details></div>`);
}
'''
s = s[:start] + opportunity_ui + s[end:]

filter_start = s.index("function applyOpportunityFilter(){")
filter_end = s.index("\nasync function runOpportunityAnalysis", filter_start)
filter_code = r'''function filteredOpportunityRows(){
  let rows=[...state.opportunityItems],f=state.oppFilter;
  if(f!=='all'&&f!=='executable')rows=rows.filter(x=>opportunityCategory(x)===f);
  if(f==='executable')rows=rows.filter(x=>x.executable===true&&(+x.executable_qty||0)>0);
  const q=state.oppSearch.trim().toUpperCase();if(q)rows=rows.filter(x=>String(x.symbol||'').toUpperCase().includes(q));
  const field=state.oppSort,dir=state.oppSortDir==='desc'?-1:1;
  rows.sort((a,b)=>{const ax=a.live_decision||a,bx=b.live_decision||b;let av=field==='rank'?+a.rank||9999:field==='symbol'?a.symbol:field==='action'?ax.final_action:field==='confidence'?({HIGH:3,MEDIUM:2,LOW:1}[ax.confidence]||0):'';let bv=field==='rank'?+b.rank||9999:field==='symbol'?b.symbol:field==='action'?bx.final_action:field==='confidence'?({HIGH:3,MEDIUM:2,LOW:1}[bx.confidence]||0):'';return (typeof av==='number'?av-bv:String(av||'').localeCompare(String(bv||'')))*dir;});
  return rows;
}
function applyOpportunityFilter(){
  const rows=filteredOpportunityRows();renderOpportunityFilters();const size=state.oppPageSize==='all'?Math.max(1,rows.length):+state.oppPageSize;const pages=Math.max(1,Math.ceil(rows.length/size));state.oppPage=Math.min(Math.max(1,state.oppPage),pages);const pageRows=state.oppPageSize==='all'?rows:rows.slice((state.oppPage-1)*size,state.oppPage*size);renderOpportunityTable(pageRows);$('#opportunityCount').textContent=`${rows.length} rows · page ${state.oppPage}/${pages}`;$('#oppPrev').disabled=state.oppPage<=1;$('#oppNext').disabled=state.oppPage>=pages;$('#oppPageLabel').textContent=`Page ${state.oppPage} of ${pages}`;
}
'''
s = s[:filter_start] + filter_code + s[filter_end:]

s = replace(s,
"async function loadPage(name){if(name==='portfolio')return loadPortfolio();if(name==='capital')return loadCapitalDefaults();if(name==='today')return loadToday();if(name==='history')return loadHistory();if(name==='system')return loadSystem();if(name==='help')return loadGlossary($('#glossarySearch')?.value||'');if(name==='opportunities'){applyOpportunityFilter();const d=await api('/api/opportunities');if(d.run)syncRunInputs(d.run)}}",
"async function loadPage(name){if(name==='portfolio')return loadPortfolio();if(name==='capital')return loadCapitalDefaults();if(name==='today')return loadToday();if(name==='history')return loadHistory();if(name==='system')return loadSystem();if(name==='help')return loadGlossary($('#glossarySearch')?.value||'');if(name==='opportunities'){const d=await api('/api/opportunities?limit=200');state.opportunityItems=d.items||[];state.oppPage=1;if(d.run)syncRunInputs(d.run);applyOpportunityFilter();}}", "load opportunities")

s = replace(s,
"  $$('[data-opp-filter]').forEach(b=>b.addEventListener('click',()=>{state.oppFilter=b.dataset.oppFilter;$$('[data-opp-filter]').forEach(x=>x.classList.toggle('active',x===b));applyOpportunityFilter()}));",
'''  $$('[data-opp-filter]').forEach(b=>b.addEventListener('click',()=>{state.oppFilter=b.dataset.oppFilter;state.oppPage=1;$$('[data-opp-filter]').forEach(x=>x.classList.toggle('active',x===b));applyOpportunityFilter()}));
  $('#oppSearch')?.addEventListener('input',e=>{state.oppSearch=e.target.value;state.oppPage=1;applyOpportunityFilter()});
  $('#oppSort')?.addEventListener('change',e=>{state.oppSort=e.target.value;state.oppPage=1;applyOpportunityFilter()});
  $('#oppSortDir')?.addEventListener('click',e=>{state.oppSortDir=state.oppSortDir==='asc'?'desc':'asc';e.currentTarget.textContent=state.oppSortDir==='asc'?'Ascending':'Descending';applyOpportunityFilter()});
  $('#oppPageSize')?.addEventListener('change',e=>{state.oppPageSize=e.target.value==='all'?'all':+e.target.value;state.oppPage=1;applyOpportunityFilter()});
  $('#oppPrev')?.addEventListener('click',()=>{state.oppPage--;applyOpportunityFilter()});$('#oppNext')?.addEventListener('click',()=>{state.oppPage++;applyOpportunityFilter()});
  document.addEventListener('click',e=>{const b=e.target.closest('[data-opportunity-details]');if(b){e.stopPropagation();openOpportunityDetails(b.dataset.opportunityDetails)}});''', "opportunity events")

# Capital Plan displays live lane counts and the actual blocker summary.
s = replace(s,
"function renderCapitalPlan(d){const s=d.capital_summary||{},buys=d.new_buys||[];",
"function renderCapitalPlan(d){const s=d.capital_summary||{},buys=d.new_buys||[],lc=s.live_lane_counts||{},blockers=s.top_blockers||{};if($('#capitalLiveSummary'))$('#capitalLiveSummary').innerHTML=`<strong>LIVE_DECISION_V1</strong><span>Momentum BUY: ${lc.momentum_buy||0}</span><span>Recovery BUY: ${lc.recovery_buy||0}</span><span>Both: ${lc.both||0}</span><span>Watch: ${lc.watch||0}</span><span>Avoid: ${lc.avoid||0}</span><div><b>Top blockers:</b> ${Object.entries(blockers).map(([k,v])=>escapeHtml(k)+' — '+v).join(' · ')||'None'}</div>`;", "capital summary")

app.write_text(s, encoding="utf-8")

index = front / "index.html"
h = index.read_text(encoding="utf-8")
old_filters = '''        <div class="filter-bar"><button class="filter-pill active" data-opp-filter="all">All</button><button class="filter-pill" data-opp-filter="momentum">Momentum</button><button class="filter-pill" data-opp-filter="recovery">Recovery</button><button class="filter-pill" data-opp-filter="avoid">Avoid</button><button class="filter-pill" data-opp-filter="watch">Watch</button><button class="filter-pill" data-opp-filter="cash-affordable">Cash affordable</button><button class="filter-pill" data-opp-filter="executable">Executable</button><span class="filter-spacer"></span><span id="opportunityCount" class="mini-copy">0 rows</span></div>
        <div id="opportunityTable" class="modern-table"></div>'''
new_filters = '''        <div class="filter-bar opportunity-filters"><button class="filter-pill active" data-opp-filter="all">All</button><button class="filter-pill" data-opp-filter="momentum">Momentum BUY</button><button class="filter-pill" data-opp-filter="recovery">Recovery BUY</button><button class="filter-pill" data-opp-filter="both">Both</button><button class="filter-pill" data-opp-filter="watch">Watch</button><button class="filter-pill" data-opp-filter="avoid">Avoid</button><button class="filter-pill" data-opp-filter="no-opportunity">No Opportunity</button><button class="filter-pill" data-opp-filter="executable">Executable</button></div>
        <div class="opportunity-toolbar"><input id="oppSearch" type="search" placeholder="Search all 200 stocks"><label>Sort <select id="oppSort"><option value="rank">Rank</option><option value="symbol">Stock</option><option value="action">Final action</option><option value="confidence">Confidence</option></select></label><button id="oppSortDir" class="ghost-btn">Ascending</button><span class="filter-spacer"></span><label>Rows <select id="oppPageSize"><option>25</option><option>50</option><option>100</option><option value="all">All</option></select></label><span id="opportunityCount" class="mini-copy">0 rows</span></div>
        <div id="opportunityTable" class="modern-table opportunity-table"></div>
        <div class="opportunity-pager"><button id="oppPrev" class="ghost-btn">Previous</button><span id="oppPageLabel">Page 1 of 1</span><button id="oppNext" class="ghost-btn">Next</button></div>'''
h = replace(h, old_filters, new_filters, "opportunity markup")
h = h.replace("Uses the same frozen combined engine as the original application. No authority change.", "LIVE_DECISION_V1 evaluates the complete active universe. Desired return affects planning context only.")
h = h.replace('<div id="capitalStatus" class="control-status">', '<div id="capitalLiveSummary" class="capital-live-summary"></div>\n          <div id="capitalStatus" class="control-status">', 1)
index.write_text(h, encoding="utf-8")

styles = front / "styles.css"
css = styles.read_text(encoding="utf-8")
css += r'''

/* 0.14.1 complete-universe Opportunities */
.opportunity-filters{flex-wrap:wrap}.opportunity-toolbar,.opportunity-pager{display:flex;align-items:center;gap:10px;margin:10px 0 14px}.opportunity-toolbar input{min-width:220px;border:1px solid var(--line);border-radius:10px;padding:8px 10px}.opportunity-toolbar select{border:1px solid var(--line);border-radius:8px;padding:7px;background:white}.opportunity-pager{justify-content:flex-end;font-size:10px;color:var(--muted)}
.opportunity-table{overflow:auto}.opportunity-row{display:grid;grid-template-columns:48px 82px minmax(150px,1.25fr) 105px 88px 88px 88px 88px 78px 72px minmax(170px,1.5fr) 58px;align-items:center;gap:9px;min-width:1190px;min-height:45px;padding:0 12px;border-top:1px solid var(--line2);font-size:9.5px}.opportunity-head{min-height:36px;border-top:0;background:#f8f9fb;color:#89919f;font-size:8px;text-transform:uppercase;letter-spacing:.4px}.opportunity-row:hover:not(.opportunity-head){background:#fafaff}.opportunity-row strong{font-size:9.5px}.stock-link{border:0;background:transparent;color:#4f46d8;text-align:left;padding:0;font-weight:800;cursor:pointer}.reason-cell{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--muted)}.opportunity-empty{padding:25px;text-align:center;color:var(--muted)}
.opportunity-detail{font-size:11px;line-height:1.55}.detail-theses{display:grid;grid-template-columns:1fr 1fr;gap:12px}.detail-theses section{padding:12px;background:#f8f9fb;border-radius:11px}.opportunity-detail pre{white-space:pre-wrap;max-height:300px;overflow:auto;background:#111827;color:#dbe5f5;padding:12px;border-radius:10px}.capital-live-summary{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0;padding:11px;border:1px solid var(--line2);border-radius:11px;background:#fafbff;font-size:10px}.capital-live-summary div{flex-basis:100%;color:var(--muted)}
'''
styles.write_text(css, encoding="utf-8")

print("0.14.1 complete-universe Opportunities UI applied")
