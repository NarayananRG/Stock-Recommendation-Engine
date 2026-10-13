from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])

api = root / "modern_ui" / "api.py"
s = api.read_text(encoding="utf-8")
s = s.replace('APP_VERSION = "0.13.3-phase8-runtime-fix"', 'APP_VERSION = "0.13.4-phase8-formatter-hotfix"', 1)
api.write_text(s, encoding="utf-8")

js = root / "modern_ui" / "frontend" / "app.js"
t = js.read_text(encoding="utf-8")
helpers = r'''
function fmtINR(value){
  const n=Number(value);
  if(!Number.isFinite(n))return '—';
  return new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:2}).format(n);
}
'''
if "function fmtINR(value)" not in t:
    anchor = "function renderValidationReplay"
    idx = t.find(anchor)
    if idx < 0:
        raise RuntimeError("Validation renderer anchor missing")
    t = t[:idx] + helpers + "\n" + t[idx:]
js.write_text(t, encoding="utf-8")

assert 'APP_VERSION = "0.13.4-phase8-formatter-hotfix"' in api.read_text(encoding="utf-8")
final_js = js.read_text(encoding="utf-8")
assert "function fmtINR(value)" in final_js
assert "function fmtPctFraction(value)" in final_js
assert final_js.find("function fmtINR(value)") < final_js.find("function renderValidationReplay")
assert final_js.find("function fmtPctFraction(value)") < final_js.find("function renderValidationReplay")
print("0.13.4 Phase 8 formatter hotfix applied")
