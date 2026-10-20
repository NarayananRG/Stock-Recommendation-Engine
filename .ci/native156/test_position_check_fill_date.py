"""Targeted regression for optional fill dates in reconstructed Today API."""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

root = Path(os.environ["SRE_ENGINE_ROOT"])
api = root / "modern_ui" / "api.py"
src = api.read_text(encoding="utf-8")
ast.parse(src)
assert 'if pos.get("entry_fill_date") else None' in src
assert 'str(pos["entry_fill_date"])' in src  # normal dated path is retained
assert 'if pos.get("entry_fill_date") else None' in src
# Execute the actual guard expression extracted from API with a minimal price fixture.
tree = ast.parse(src)
guard = None
for node in ast.walk(tree):
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pos" for t in node.targets):
        if isinstance(node.value, ast.Dict):
            if any(isinstance(k, ast.Constant) and k.value == "sessions_held" for k in node.value.keys if k):
                guard = node
                break
assert guard is not None, "Position-check assignment missing"
class Prices:
    def history(self, symbol, limit):
        assert symbol == "HINDZINC" and limit == 5000
        return [{"date": "2026-10-17"}, {"date": "2026-10-20"}]
class Handler:
    prices = Prices()
code = compile(ast.fix_missing_locations(ast.Module(body=[guard], type_ignores=[])), "<actual-position-guard>", "exec")
for position, expected in [
    ({"symbol": "HINDZINC", "entry_fill_date": "2026-10-19", "quantity": 36}, 1),
    ({"symbol": "HINDZINC", "quantity": 36}, None),
    ({"symbol": "HINDZINC", "entry_fill_date": "", "quantity": 36}, None),
]:
    env = {"self": Handler(), "pos": dict(position)}
    exec(code, env)
    assert env["pos"]["sessions_held"] == expected, env["pos"]
    assert env["pos"]["quantity"] == 36
assert "entry_fill_date" not in env["pos"] or env["pos"].get("entry_fill_date") == ""
print("PASS: position check handles known and missing fill dates without changing position fields")
