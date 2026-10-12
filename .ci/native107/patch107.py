from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])

api = root / "modern_ui" / "api.py"
s = api.read_text(encoding="utf-8")
old = 'APP_VERSION = "0.12.0-phase6-combined-prediction-v2"'
new = 'APP_VERSION = "0.12.1-first-launch-target-hotfix"'
if old not in s:
    raise RuntimeError("Phase 6 app version marker missing")
s = s.replace(old, new, 1)
api.write_text(s, encoding="utf-8")

html = root / "modern_ui" / "frontend" / "index.html"
h = html.read_text(encoding="utf-8")
# The field must never carry a default target in markup.
import re
h = re.sub(r'(<input\\b[^>]*\\bid="oppTarget"[^>]*?)\\s+value="[^"]*"', r'\\1', h, count=1)
if 'id="oppTarget"' not in h:
    raise RuntimeError("oppTarget input missing")
html.write_text(h, encoding="utf-8")

js = root / "modern_ui" / "frontend" / "app.js"
t = js.read_text(encoding="utf-8")

# When dashboard state says there is no explicit user target, forcibly keep the UI field blank.
needle = "  const targetState=data.target_state||{};\n"
insert = needle + "  if(!targetState.explicit&&$('#oppTarget')){$('#oppTarget').value='';}\n"
if insert not in t:
    if needle not in t:
        raise RuntimeError("Phase 6 targetState anchor missing")
    t = t.replace(needle, insert, 1)

# Critical fix: POST payload derives desired return from the visible field itself.
# Blank means null. No fallback/default target is allowed.
old_payload = "target_return_percent:target"
new_payload = "target_return_percent:(String($('#oppTarget')?.value||'').trim()===''?null:Number($('#oppTarget').value))"
if new_payload not in t:
    if old_payload not in t:
        raise RuntimeError("Opportunity target payload anchor missing")
    t = t.replace(old_payload, new_payload, 1)

# After Opportunities GET/restore, unconfirmed/absent target must also stay blank.
# This guards older persisted runs that happened to contain a numeric target.
restore_anchor = "syncRunInputs(d.run);"
restore_patch = "syncRunInputs(d.run);if(!(d.target_state||{}).explicit&&$('#oppTarget')){$('#oppTarget').value='';}"
if restore_patch not in t and restore_anchor in t:
    t = t.replace(restore_anchor, restore_patch, 1)

js.write_text(t, encoding="utf-8")

assert "target_return_percent:(String($('#oppTarget')?.value||'').trim()===''?null:Number($('#oppTarget').value))" in t
assert "if(!targetState.explicit&&$('#oppTarget')){$('#oppTarget').value='';}" in t
assert '0.12.1-first-launch-target-hotfix' in s
print("0.12.1 first-launch target hotfix applied")
