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

marker = "function renderDashboard(data){"
pos = t.find(marker)
if pos < 0:
    raise RuntimeError("renderDashboard function missing")
body_pos = t.find("\n", pos)
if body_pos < 0:
    raise RuntimeError("renderDashboard body missing")
inject = """
  const source=state.dataSource?.active||{};
  const universeTarget=Number(source.official_universe_target||200);
  const universeMembers=Number(source.official_universe_members||0);
  const loadedHistories=Number(data.symbol_count??source.stock_files??0);
"""
if "const universeTarget=Number(source.official_universe_target||200);" not in t:
    t = t[:body_pos+1] + inject + t[body_pos+1:]

lines = t.splitlines()
count_done = False
text_done = False
for i, line in enumerate(lines):
    if "$('#engineSymbolCount').textContent=" in line and not count_done:
        lines[i:i+1] = [
            "  $('#engineSymbolCount').textContent=universeMembers||universeTarget;",
            "  const orbLabel=$('#engineSymbolCount')?.parentElement?.querySelector('small');",
            "  if(orbLabel) orbLabel.textContent='universe';",
        ]
        count_done = True
        continue
    if "$('#engineText').textContent=" in line and not text_done:
        lines[i:i+1] = [
            "  const universeLabel=universeMembers?(universeMembers+'/'+universeTarget):('target '+universeTarget);",
            "  const modeLabel=state.dataSource?.mode==='REAL_OFFICIAL_DATA'?'official':'frozen';",
            "  $('#engineText').textContent='Universe '+universeLabel+' · history loaded '+loadedHistories+'/'+universeTarget+' · '+modeLabel+' data · '+(state.dataSource?.active?.latest_session||data.engine_status?.latest_session||'—');",
        ]
        text_done = True

if not count_done:
    raise RuntimeError("engine symbol count line missing")
if not text_done:
    raise RuntimeError("engine text line missing")
t = "\n".join(lines) + "\n"

refresh = """api('/api/data-source').then(source=>{state.dataSource=source;if(state.dashboard)renderDashboard(state.dashboard);}).catch(()=>{});"""
if refresh not in t:
    tail = t.rfind("init();")
    if tail < 0:
        raise RuntimeError("init call missing")
    t = t[:tail+7] + "\n" + refresh + t[tail+7:]

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
assert "universeTarget" in js.read_text(encoding="utf-8")
print("0.9.12 universe visibility hotfix applied")
