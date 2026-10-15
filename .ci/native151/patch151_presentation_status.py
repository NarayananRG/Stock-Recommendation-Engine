from pathlib import Path
import os

root=Path(os.environ["SRE_ENGINE_ROOT"])

def replace_once(path:Path, old:str, new:str, label:str):
    text=path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(label+" patch point missing")
    path.write_text(text.replace(old,new,1),encoding="utf-8")

api=root/"modern_ui"/"api.py"
replace_once(
    api,
    'APP_VERSION = "0.14.9-pit-safety-evidence-repair"',
    'APP_VERSION = "0.14.10-recommendation-presentation-status-repair"',
    "release identity",
)

a=api.read_text(encoding="utf-8")
needle='''        analysis_complete = bool(run_id and active.get("candidates") is not None)
        stale_active = bool(active_analysis and latest_official and active_analysis != latest_official)

        if expected_session and latest_official == expected_session:
'''
replacement='''        analysis_complete = bool(run_id and active.get("candidates") is not None)
        stale_active = bool(active_analysis and latest_official and active_analysis != latest_official)
        lane_counts = dict(run.get("lane_counts") or {})
        live_buy_count = int(lane_counts.get("momentum_buy") or 0) + int(lane_counts.get("recovery_buy") or 0) + int(lane_counts.get("both") or 0)
        if not analysis_complete:
            production_decision_status = "NO_ACTIVE_ANALYSIS"
        elif stale_active:
            production_decision_status = "STALE_ANALYSIS"
        elif live_buy_count > 0:
            production_decision_status = "BUY_OPPORTUNITIES_AVAILABLE"
        else:
            production_decision_status = "ANALYSIS_COMPLETE"

        if expected_session and latest_official == expected_session:
'''
if needle not in a:
    raise RuntimeError("canonical status computation point missing")
a=a.replace(needle,replacement,1)
old_lane='            "lane_counts": dict(run.get("lane_counts") or {}),\n'
if old_lane not in a:
    raise RuntimeError("canonical lane count field missing")
a=a.replace(
    old_lane,
    '            "lane_counts": lane_counts,\n            "live_buy_count": live_buy_count,\n            "production_decision_status": production_decision_status,\n',
    1,
)
api.write_text(a,encoding="utf-8")

front=root/"modern_ui"/"frontend"
app=front/"app.js"
s=app.read_text(encoding="utf-8")

old_heading="<b>Why no capital was deployed</b>"
new_heading="<b>${buys.length?'Why other stocks were not allocated':'Why no capital was deployed'}</b>"
if old_heading not in s:
    raise RuntimeError("capital blocker heading missing")
s=s.replace(old_heading,new_heading,1)

anchor="function renderCapitalPlan(d){"
if anchor not in s:
    raise RuntimeError("renderCapitalPlan anchor missing")
helper=r'''function capitalRationale(b){
  let raw=String(b?.thesis||b?.reason_text||'').trim();
  raw=raw.replace(/Revenue direction is improving\.\s*PAT direction is improving\.\s*EPS direction is improving\./i,'Revenue, PAT and EPS trends are improving.');
  raw=raw.replace(/Cash-flow evidence is supportive\.\s*Balance-sheet evidence is healthy\.\s*PIT valuation comparison is attractive\./i,'Cash flow is supportive, balance sheet is healthy, and PIT valuation is attractive.');
  const parts=(raw.match(/[^.!?]+[.!?]+|[^.!?]+$/g)||[]).map(x=>x.trim()).filter(Boolean);
  const seen=new Set(),clean=[];
  const declineKey='the cause of the decline is not established by these data';
  let declineSeen=false;
  for(const part of parts){
    const key=part.toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
    if(!key||seen.has(key))continue;
    if(key.includes(declineKey)){
      if(declineSeen&&key===declineKey)continue;
      declineSeen=true;
    }
    seen.add(key);clean.push(part);
  }
  let core=clean.join(' ').trim();
  if(core.length>520)core=core.slice(0,517).trimEnd()+'...';
  const meta=[];
  if(b?.confidence)meta.push('Confidence: '+String(b.confidence));
  if(b?.technical_state)meta.push('Technical: '+String(b.technical_state));
  return [core,meta.join(' · ')].filter(Boolean).join(' ');
}
'''
if "function capitalRationale(b)" not in s:
    s=s.replace(anchor,helper+anchor,1)

old_expr="escapeHtml((b.thesis||b.reason_text||'')+' · Confidence '+(b.confidence||'UNAVAILABLE')+' · Risk '+(b.technical_state||'UNAVAILABLE'))"
if old_expr in s:
    s=s.replace(old_expr,"escapeHtml(capitalRationale(b))",1)
elif "escapeHtml(b.reason_text||'')" in s:
    s=s.replace("escapeHtml(b.reason_text||'')","escapeHtml(capitalRationale(b))",1)
else:
    raise RuntimeError("capital rationale presentation point missing")

runtime=r'''
function sre151DecisionStatus(ui){
  ui=ui||{};
  const count=Number(ui.live_buy_count ?? ((ui.lane_counts?.momentum_buy||0)+(ui.lane_counts?.recovery_buy||0)+(ui.lane_counts?.both||0)));
  if(ui.analysis_complete!==true)return 'NO ACTIVE ANALYSIS';
  if(ui.stale_active_run===true)return 'STALE ANALYSIS';
  if(count>0)return count+' BUY '+(count===1?'OPPORTUNITY':'OPPORTUNITIES');
  return 'ANALYSIS COMPLETE';
}
function sre151ApplyOverviewStatus(ui){
  const root=document.querySelector('#page-dashboard')||document.querySelector('#page-overview')||document;
  const labels=Array.from(root.querySelectorAll('span,small,div')).filter(el=>el.children.length===0&&String(el.textContent||'').trim().toLowerCase()==='v1 status');
  const value=sre151DecisionStatus(ui);
  labels.forEach(label=>{
    const box=label.parentElement;if(!box)return;
    let target=box.querySelector('strong,b,.metric-value,.value,[data-value]');
    if(!target)target=Array.from(box.children).find(el=>el!==label&&String(el.textContent||'').trim());
    if(target)target.textContent=value;
  });
}
async function sre151RefreshOverviewStatus(){
  try{const ui=await api('/api/ui-consistency');sre151ApplyOverviewStatus(ui)}catch(_){}
}
if(!window.__sre151PresentationBound){
  window.__sre151PresentationBound=true;
  document.addEventListener('DOMContentLoaded',()=>setTimeout(sre151RefreshOverviewStatus,250));
  document.addEventListener('click',e=>{
    if(e.target?.closest?.('.nav-item[data-page="dashboard"],.nav-item[data-page="overview"],#topRefresh'))setTimeout(sre151RefreshOverviewStatus,120);
  },true);
}
if(typeof renderDashboard==='function'&&!window.__sre151RenderDashboardWrapped){
  window.__sre151RenderDashboardWrapped=true;
  const __sre151RenderDashboard=renderDashboard;
  renderDashboard=function(data){
    const result=__sre151RenderDashboard(data);
    sre151ApplyOverviewStatus(data?.ui_state||{});
    return result;
  };
}
'''
if "function sre151DecisionStatus" not in s:
    s+="\n"+runtime+"\n"

app.write_text(s,encoding="utf-8")

policy=root/"phase7"/"recommendation_presentation_status_01410.json"
policy.write_text('''{
  "schema": "SRE_RECOMMENDATION_PRESENTATION_STATUS_01410",
  "release": "0.14.10-recommendation-presentation-status-repair",
  "overview_status_source": "CANONICAL_UI_STATE",
  "capital_blocker_heading_dynamic": true,
  "capital_rationale_deduplicated": true,
  "recommendation_logic_changed": false,
  "model_or_threshold_changed": false,
  "allocation_policy_changed": false,
  "provider_policy_changed": false,
  "automatic_yfinance_fallback": false
}
''',encoding="utf-8")

check=app.read_text(encoding="utf-8")
assert "Why other stocks were not allocated" in check
assert "function capitalRationale(b)" in check
assert "function sre151DecisionStatus" in check
assert "NO ACTIVE ANALYSIS" in check
assert "BUY OPPORTUNITIES" in check
print("0.14.10 recommendation presentation and status repair applied")
