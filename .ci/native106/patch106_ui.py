from pathlib import Path
import os
import re

root = Path(os.environ["SRE_ENGINE_ROOT"])

def repl(text, old, new, label):
    if old not in text:
        raise RuntimeError(label + " contract missing")
    return text.replace(old, new, 1)

def replace_line(text, needle, replacement, label):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if needle in line:
            indent = line[: len(line) - len(line.lstrip())]
            lines[i] = indent + replacement
            return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    raise RuntimeError(label + " line missing")

html = root / "modern_ui" / "frontend" / "index.html"
h = html.read_text(encoding="utf-8")
fund_start = h.find('id="fundamentalV3Panel"')
if fund_start < 0:
    raise RuntimeError("Fundamental V3 panel missing")
fund_close = h.find("</article>", fund_start)
if fund_close < 0:
    raise RuntimeError("Fundamental V3 closing tag missing")
fund_close += len("</article>")

if 'id="combinedV2Panel"' not in h:
    panel = '''
        <article id="combinedV2Panel" class="panel-card combined-v2-panel">
          <div class="panel-head">
            <div><span class="card-label">COMBINED PREDICTION V2</span><h3>Frozen engine + Technical V2 + Fundamental V3 + market context</h3></div>
            <div class="phase6-head-status"><span id="combinedV2Authority" class="status-pill neutral">SHADOW ONLY</span><strong id="combinedV2Score">—</strong><span>/100</span></div>
          </div>
          <div class="combined-v2-summary"><strong id="combinedV2Label">Waiting for combined evidence</strong><span id="combinedV2Coverage">—</span><div class="combined-v2-scorebar"><span id="combinedV2ScoreFill"></span></div></div>
          <div id="combinedV2Grid" class="combined-v2-grid"></div>
          <div class="combined-v2-foot">
            <div><span class="card-label">SHADOW DECISION</span><strong id="combinedV2Decision">—</strong><span id="combinedV2Reasons">—</span></div>
            <div><span class="card-label">TARGET POLICY</span><strong>DESIRED RETURN NOT USED IN SCORE</strong><span>User targets compare outcomes only; they never enter the Combined V2 score.</span></div>
          </div>
        </article>
'''
    h = h[:fund_close] + "\n" + panel + h[fund_close:]

h, changed = re.subn(r'(<input\b[^>]*\bid="oppTarget"[^>]*?)\s+value="[^"]*"', r'\1 placeholder="Optional"', h, count=1)
if changed == 0 and 'id="oppTarget"' in h and 'placeholder="Optional"' not in h:
    h = h.replace('id="oppTarget"', 'id="oppTarget" placeholder="Optional"', 1)
html.write_text(h, encoding="utf-8")

js = root / "modern_ui" / "frontend" / "app.js"
t = js.read_text(encoding="utf-8")

decision_anchor = "function decisionTone(text=''){"
if "function displayTarget(item)" not in t:
    t = repl(t, decision_anchor, "function displayTarget(item){return item&&item.target_explicit===true?(item.target_status||'NO TARGET'):'NOT SET';}\n\n" + decision_anchor, "display-target helper")

t = repl(t, "const target=item.target_status||'NO TARGET'; const targetCls=target==='MEETS TARGET'?'positive-text':target==='BELOW TARGET'?'negative-text':'';", "const target=displayTarget(item); const targetCls=target==='MEETS TARGET'?'positive-text':target==='BELOW TARGET'?'negative-text':'';", "card target")
t = repl(t, "escapeHtml(item.opportunity_status||'Evidence available')", "escapeHtml(decisionDisplayTitle(item.opportunity_status||'Evidence available'))", "card decision display")

t = repl(
    t,
    "  const hero=opps[0];\n",
    "  const actionable=opps.find(x=>x.executable===true&&(+x.executable_qty||0)>0&&decisionTone(x.opportunity_status||'')==='buy')||null;\n"
    "  const watch=opps.find(x=>decisionTone(x.opportunity_status||'')==='watch')||null;\n"
    "  const hero=actionable||watch;\n"
    "  const heroKind=actionable?'TOP OPPORTUNITY':watch?'TOP WATCH CANDIDATE':'NO ACTIONABLE OPPORTUNITY';\n"
    "  const heroRoot=$('#heroSymbol')?.closest('article')||$('#heroSymbol')?.parentElement?.parentElement;\n"
    "  const heroLabel=heroRoot?.querySelector('.card-label')||heroRoot?.querySelector('.eyebrow');\n"
    "  if(heroLabel)heroLabel.textContent=heroKind;\n"
    "  const targetState=data.target_state||{};\n",
    "hero selection",
)

t = replace_line(
    t,
    "$('#heroSub').textContent=",
    "$('#heroSub').textContent=decisionDisplayTitle(hero.opportunity_status||'Ranked evidence')+' · '+(targetState.explicit?(hero.target_status||'NO TARGET'):'target not set');",
    "hero subtitle",
)

t = repl(
    t,
    "  }else{$('#asOfSession').textContent=active.latest_session||'—';}\n",
    "  }else{$('#heroSymbol').textContent='—';$('#heroSub').textContent=opps.length?'No executable BUY or WATCH candidate in the active run.':'Run opportunity analysis to create an explicit active run.';$('#heroPrice').textContent='—';$('#heroReturn').textContent='—';$('#heroProbability').textContent='—';$('#heroConfidence').textContent='—';$('#heroDecision').textContent='NO ACTIONABLE SIGNAL';$('#heroOpen').removeAttribute('data-symbol');$('#heroOpen').disabled=true;$('#asOfSession').textContent=active.latest_session||'—';}\n",
    "empty hero",
)

t = repl(t, "escapeHtml(i.target_status||'NO TARGET')", "escapeHtml(displayTarget(i))", "table target")

lines = t.splitlines()
changed_status = False
for i, line in enumerate(lines):
    if "$('#oppRunStatus').textContent=" in line and "data session" in line and "target" in line:
        indent = line[: len(line) - len(line.lstrip())]
        lines[i] = indent + "try{const d=await api('/api/opportunities/run',{method:'POST',body:{capital,horizon_sessions:horizon,target_return_percent:target}});state.opportunityItems=d.items||[];syncRunInputs(d.run);applyOpportunityFilter();const ts=d.target_state||{};$('#oppRunStatus').textContent=(d.reused_run?'Reused':'Created')+' Run '+shortRun(d.run)+' · '+(d.count||0)+' rows · data session '+(d.run?.market_session||'—')+' · '+(ts.explicit?('explicit target '+fmtPctFraction(ts.value)):'no target');renderDashboard(await api('/api/dashboard'));toast(d.reused_run?'Existing identical run reused':'Opportunity analysis complete');}"
        changed_status = True
        break
if not changed_status:
    raise RuntimeError("opportunity run status line missing")
t = "\n".join(lines) + ("\n" if t.endswith("\n") else "")

t = repl(t, "renderFundamentalV3(d.fundamental_v3||{});", "renderFundamentalV3(d.fundamental_v3||{}); renderCombinedV2(d.combined_v2||{});", "combined render hook")

if "function renderCombinedV2(x)" not in t:
    renderer = '''
function renderCombinedV2(x){
  const panel=$('#combinedV2Panel');if(!panel)return;
  const score=Number.isFinite(+x.combined_score)?+x.combined_score:null;
  const conf=Number.isFinite(+x.confidence)?Math.round(+x.confidence*100):null;
  $('#combinedV2Score').textContent=score==null?'—':score.toFixed(0);
  $('#combinedV2Authority').textContent=x.authority||'SHADOW ONLY';
  $('#combinedV2ScoreFill').style.width=(score==null?0:Math.max(0,Math.min(100,score)))+'%';
  $('#combinedV2Label').textContent=(x.combined_label||x.status||'UNAVAILABLE').replaceAll('_',' ');
  $('#combinedV2Coverage').textContent='Evidence '+(x.evidence_coverage!=null?Math.round(+x.evidence_coverage*100)+'%':'—')+' · confidence '+(conf==null?'—':conf+'%')+' · agreement '+(x.component_agreement!=null?Math.round(+x.component_agreement*100)+'%':'—');
  const c=x.components||{};
  const rows=[['Frozen engine',c.frozen_engine],['Technical V2',c.technical_v2],['Fundamental V3',c.fundamental_v3],['Market context',c.market_context]];
  $('#combinedV2Grid').innerHTML=rows.map(function(row){const q=row[1]||{};return '<div class="combined-v2-cell"><span>'+escapeHtml(row[0])+'</span><strong>'+(q.available&&Number.isFinite(+q.score)?Number(q.score).toFixed(0)+'/100':'UNAVAILABLE')+'</strong><small>'+escapeHtml(String(q.label||q.regime||q.confidence_label||'—').replaceAll('_',' '))+'</small></div>';}).join('');
  $('#combinedV2Decision').textContent=(x.shadow_decision||'NO SIGNAL').replaceAll('_',' ');
  $('#combinedV2Reasons').textContent=(x.reason_codes||[]).length?(x.reason_codes||[]).map(function(v){return String(v).replaceAll('_',' ');}).join(' · '):'Target never enters the Combined V2 score.';
}

'''
    t = repl(t, "function sma(bars,n){", renderer + "function sma(bars,n){", "combined renderer")

js.write_text(t, encoding="utf-8")

css = root / "modern_ui" / "frontend" / "styles.css"
c = css.read_text(encoding="utf-8")
if ".combined-v2-panel" not in c:
    c += '''
/* Phase 6 Combined Prediction V2 */
.combined-v2-panel{margin-top:18px;padding:22px}.phase6-head-status{display:flex;align-items:center;gap:8px}.phase6-head-status>strong{font-size:28px}
.combined-v2-summary{display:grid;grid-template-columns:minmax(180px,1fr) auto;gap:8px 18px;align-items:center;margin:12px 0 18px}.combined-v2-scorebar{grid-column:1/-1;height:7px;border-radius:999px;background:rgba(120,128,150,.14);overflow:hidden}.combined-v2-scorebar span{display:block;height:100%;width:0;background:linear-gradient(90deg,#4f46e5,#0b9f70);border-radius:999px}
.combined-v2-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.combined-v2-cell{padding:14px;border:1px solid rgba(120,128,150,.14);border-radius:14px;background:rgba(255,255,255,.38);display:flex;flex-direction:column;gap:7px;min-height:96px}.combined-v2-cell>span{font-size:10px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;opacity:.56}.combined-v2-cell>strong{font-size:17px}.combined-v2-cell>small{font-size:11px;opacity:.65}
.combined-v2-foot{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}.combined-v2-foot>div{padding:14px;border-radius:14px;background:rgba(120,128,150,.07);display:grid;gap:5px}.combined-v2-foot span:last-child{font-size:11px;opacity:.65}
@media(max-width:900px){.combined-v2-grid,.combined-v2-foot{grid-template-columns:1fr 1fr}}@media(max-width:620px){.combined-v2-grid,.combined-v2-foot{grid-template-columns:1fr}}
'''
css.write_text(c, encoding="utf-8")

assert "TOP WATCH CANDIDATE" in t
assert "renderCombinedV2" in t
assert "combinedV2Panel" in h
print("Phase 6 UI integration applied")
