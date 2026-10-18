"""Gate A: fail-closed count-writer repair in reconstructed 0.14.13 engine.

Does not touch order ledgers, recommendation rules, or original installations.
"""
from pathlib import Path
import os
root=Path(os.environ["SRE_ENGINE_ROOT"])
api=root/"modern_ui"/"api.py"
source=api.read_text(encoding="utf-8")
old='            "executable_count": len([x for x in rows if x.get("executable")]),'
new='            "executable_count": sum(1 for x in rows if (x.get("live_decision") or {}).get("executable") is True),'
if source.count(old)!=1:
    raise RuntimeError(f"GATE_A_COUNT_PATCH_ANCHOR_MISMATCH: {source.count(old)}")
if source.count(new)!=0:
    raise RuntimeError("GATE_A_COUNT_PATCH_ALREADY_PRESENT")
patched=source.replace(old,new,1)
compile(patched,str(api),"exec")
api.write_text(patched,encoding="utf-8")
assert api.read_text(encoding="utf-8").count(new)==1
print("GATE_A_COUNT_WRITER_PATCH_PASS")
