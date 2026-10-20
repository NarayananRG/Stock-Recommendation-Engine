"""Gate A hotfix: legacy position summaries may lack entry_fill_date.

Do not fabricate a position entry date or mutate persisted trading records.
"""
from __future__ import annotations

import os
from pathlib import Path

target = Path(os.environ["SRE_ENGINE_ROOT"]) / "modern_ui" / "api.py"
original = target.read_text(encoding="utf-8")
old = 'pos = {**pos, "sessions_held": sum(str(b["date"])[:10] > str(pos["entry_fill_date"]) for b in self.prices.history(pos["symbol"], limit=5000))}'
new = '''pos = {**pos, "sessions_held": (
                sum(str(b["date"])[:10] > str(pos["entry_fill_date"]) for b in self.prices.history(pos["symbol"], limit=5000))
                if pos.get("entry_fill_date") else None
            )}'''
if new in original:
    print("Position-check missing-fill-date guard already applied")
elif original.count(old) == 1:
    target.write_text(original.replace(old, new, 1), encoding="utf-8")
    print("Position-check missing-fill-date guard applied")
else:
    raise SystemExit(f"Unexpected position-check anchor count: {original.count(old)}")
