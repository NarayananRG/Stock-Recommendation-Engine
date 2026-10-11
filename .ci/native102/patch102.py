from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])

api = root / "modern_ui" / "api.py"
s = api.read_text(encoding="utf-8")
if 'APP_VERSION = "0.9.11-phase3b-official-data"' not in s:
    raise RuntimeError("0.9.11 baseline identity missing")
s = s.replace('APP_VERSION = "0.9.11-phase3b-official-data"', 'APP_VERSION = "0.9.12-phase3c-universe-visibility"', 1)
api.write_text(s, encoding="utf-8")

js = root / "modern_ui" / "frontend" / "app.js"
t = js.read_text(encoding="utf-8")

old_state = "const state = { page:'dashboard', stock:null, symbols:[], dashboard:null, chart:null, previousPage:'dashboard' };"
new_state = "const state = { page:'dashboard', stock:null, symbols:[], dashboard:null, dataSource:null, chart:null, previousPage:'dashboard' };"
if old_state not in t:
    raise RuntimeError("frontend state contract missing")
t = t.replace(old_state, new_state, 1)

old_count = "  $('#engineSymbolCount').textContent=data.symbol_count??0;"
new_count = """  const source=state.dataSource?.active||{};
  const universeTarget=Number(source.official_universe_target||200);
  const universeMembers=Number(source.official_universe_members||0);
  const loadedHistories=Number(data.symbol_count??source.stock_files??0);
  $('#engineSymbolCount').textContent=universeMembers||universeTarget;
  const orbLabel=$('#engineSymbolCount')?.parentElement?.querySelector('small');
  if(orbLabel) orbLabel.textContent='universe';
"""
if old_count not in t:
    raise RuntimeError("engine symbol count contract missing")
t = t.replace(old_count, new_count, 1)

lines = t.splitlines()
replaced = False
for i, line in enumerate(lines):
    if "$('#engineText').textContent=" in line:
        lines[i:i+1] = [
            "  const universeLabel=universeMembers?(universeMembers+'/'+universeTarget):('target '+universeTarget);",
            "  const modeLabel=state.dataSource?.mode==='REAL_OFFICIAL_DATA'?'official':'frozen';",
            "  $('#engineText').textContent='Universe '+universeLabel+' · history loaded '+loadedHistories+'/'+universeTarget+' · '+modeLabel+' data · '+(state.dataSource?.active?.latest_session||data.engine_status?.latest_session||'—');",
        ]
        replaced = True
        break
if not replaced:
    raise RuntimeError("engine text contract missing")
t = "\n".join(lines) + "\n"

old_init = "  try{renderDashboard(await api('/api/dashboard')); await loadSymbols('');}"
new_init = """  try{
    const [dashboard,source]=await Promise.all([api('/api/dashboard'),api('/api/data-source')]);
    state.dataSource=source;
    renderDashboard(dashboard);
    await loadSymbols('');
  }"""
if old_init not in t:
    raise RuntimeError("init dashboard contract missing")
t = t.replace(old_init, new_init, 1)

js.write_text(t, encoding="utf-8")

html = root / "modern_ui" / "frontend" / "index.html"
h = html.read_text(encoding="utf-8")
h = h.replace('<span id="engineSymbolCount">0</span><small>stocks</small>', '<span id="engineSymbolCount">0</span><small>universe</small>', 1)
html.write_text(h, encoding="utf-8")

policy = root / "phase3" / "universe_visibility_contract_v1.json"
policy.parent.mkdir(parents=True, exist_ok=True)
policy.write_text("""{
  "schema": "SRE_PHASE3C_UNIVERSE_VISIBILITY_V1",
  "version": "0.9.12-phase3c-universe-visibility",
  "universe_target": 200,
  "rule": "Universe size must be shown separately from loaded history count.",
  "loaded_history_must_not_be_labeled_as_universe": true,
  "recommendation_authority_change": false,
  "authority": "UI_CORRECTNESS_ONLY"
}
""", encoding="utf-8")

assert "history loaded" in js.read_text(encoding="utf-8")
assert "<small>universe</small>" in html.read_text(encoding="utf-8")
print("0.9.12 universe visibility hotfix applied")
