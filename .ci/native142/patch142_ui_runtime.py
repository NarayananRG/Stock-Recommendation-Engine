from pathlib import Path
import os
front=Path(os.environ['SRE_ENGINE_ROOT'])/'modern_ui/frontend'
app=front/'app.js';s=app.read_text(encoding='utf-8')
# Prefer canonical session truth anywhere the dashboard renders the official date.
s=s.replace("$('#asOfSession').textContent=active.latest_session||'—';","$('#asOfSession').textContent=(data.ui_state?.latest_official_session||active.latest_session||'—');")
s=s.replace("(state.dataSource?.active?.latest_session||data.engine_status?.latest_session||'—')","(data.ui_state?.latest_official_session||state.dataSource?.active?.latest_session||data.engine_status?.latest_session||'—')")
r=r"""
async function refreshUiSessionTruth(){try{state.uiSessionTruth=await api('/api/ui-consistency');repairOverviewUx();return state.uiSessionTruth}catch(_){return state.uiSessionTruth||null}}
function leafTextNodes(fn){return Array.from(document.querySelectorAll('span,strong,p,div,h2,h3')).filter(e=>e.children.length===0&&fn((e.textContent||'').trim()))}
function repairOverviewUx(){const t=state.uiSessionTruth;if(!t)return;const asOf=$('#asOfSession');if(asOf&&t.latest_official_session)asOf.textContent=t.latest_official_session;leafTextNodes(x=>x.toUpperCase()==='LATEST OFFICIAL SESSION').forEach(l=>{const b=l.parentElement;if(!b)return;const d=Array.from(b.querySelectorAll('strong,b,span,div')).find(e=>/^\d{4}-\d{2}-\d{2}$/.test((e.textContent||'').trim()));if(d&&t.latest_official_session)d.textContent=t.latest_official_session});if(t.analysis_complete)leafTextNodes(x=>x==='NO RESULT').forEach(e=>e.textContent='ANALYSIS COMPLETE');const c=t.lane_counts||{},w=+c.watch||0,b=(+c.momentum_buy||0)+(+c.recovery_buy||0)+(+c.both||0);leafTextNodes(x=>x.includes('No executable BUY or WATCH candidate')).forEach(e=>e.textContent=b?'Executable BUY opportunities are available.':(w?`No executable BUY opportunity today. ${w} stocks remain on WATCH.`:'No executable BUY opportunity in the active run.'));leafTextNodes(x=>x==='NO ACTIONABLE SIGNAL').forEach(e=>{if(t.analysis_complete)e.textContent=b?'BUY OPPORTUNITIES AVAILABLE':'NO EXECUTABLE BUY'});Array.from(document.querySelectorAll('button,a')).filter(e=>/Open stock intelligence/i.test(e.textContent||'')).forEach(e=>{if(!b){e.textContent='Browse stocks ->';e.dataset.browseStocks='true'}})}
document.addEventListener('click',e=>{const q=e.target.closest?.('[data-open-stock-intelligence],.stock-link[data-symbol]');if(q){const sym=q.dataset.openStockIntelligence||q.dataset.symbol;if(sym){e.preventDefault();e.stopImmediatePropagation();openStock(sym);return}}const b=e.target.closest?.('[data-browse-stocks="true"]');if(b){e.preventDefault();e.stopImmediatePropagation();document.querySelector('.nav-item[data-page="opportunities"]')?.click()}},true);
document.addEventListener('DOMContentLoaded',()=>{refreshUiSessionTruth();setTimeout(repairOverviewUx,400)});document.addEventListener('click',e=>{if(e.target.closest?.('.nav-item'))setTimeout(refreshUiSessionTruth,50)},true);
"""
if 'function refreshUiSessionTruth()' not in s:s+='\n'+r+'\n'
app.write_text(s,encoding='utf-8')
idx=front/'index.html';h=idx.read_text(encoding='utf-8').replace('Opportunities worth opening','Stocks to review');idx.write_text(h,encoding='utf-8')
print('0.14.2 UI session runtime applied')
