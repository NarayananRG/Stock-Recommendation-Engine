from pathlib import Path
import os
import re

root = Path(os.environ["SRE_ENGINE_ROOT"])

# Backend identity bump only; recommendation/scoring authority is unchanged.
api = root / "modern_ui" / "api.py"
s = api.read_text(encoding="utf-8")
old = 'APP_VERSION = "0.12.0-phase6-combined-prediction-v2"'
new = 'APP_VERSION = "0.12.1-phase6-target-hotfix"'
if old not in s:
    raise RuntimeError("Phase 6 backend identity missing before 0.12.1 hotfix")
s = s.replace(old, new, 1)
api.write_text(s, encoding="utf-8")

# Fix the actual browser input, regardless of whether value= appears before or
# after id=oppTarget. Phase 6 only removed value attributes that appeared after
# the id, which allowed a hard-coded 5% default to survive in some markup.
html = root / "modern_ui" / "frontend" / "index.html"
h = html.read_text(encoding="utf-8")

tag_re = re.compile(r'<input\\b[^>]*\\bid=(["\\\'])oppTarget\\1[^>]*>', re.I)
match = tag_re.search(h)
if not match:
    raise RuntimeError("oppTarget input missing")
tag = match.group(0)
tag = re.sub(r'\\s+value\\s*=\\s*(["\\\']).*?\\1', '', tag, flags=re.I)
tag = re.sub(r'\\s+placeholder\\s*=\\s*(["\\\']).*?\\1', '', tag, flags=re.I)
tag = tag[:-1].rstrip() + ' placeholder="Optional">'
h = h[:match.start()] + tag + h[match.end():]
html.write_text(h, encoding="utf-8")

# Contract: the shipped HTML itself must not seed any desired-return value.
check = tag_re.search(h)
if not check:
    raise RuntimeError("oppTarget input disappeared")
fixed_tag = check.group(0)
if re.search(r'\\bvalue\\s*=', fixed_tag, re.I):
    raise RuntimeError("oppTarget still contains a hard-coded value")
if 'placeholder="Optional"' not in fixed_tag:
    raise RuntimeError("oppTarget optional placeholder missing")

phase = root / "phase6"
phase.mkdir(parents=True, exist_ok=True)
(phase / "target_input_hotfix_0121.json").write_text("""{
  "schema": "SRE_PHASE6_TARGET_INPUT_HOTFIX_0121",
  "release": "0.12.1-phase6-target-hotfix",
  "desired_return_default": null,
  "target_badges_require_explicit_user_input": true,
  "production_recommendation_authority_changed": false,
  "combined_v2_authority_changed": false
}
""", encoding="utf-8")

print("0.12.1 target input hotfix applied")
print(fixed_tag)
