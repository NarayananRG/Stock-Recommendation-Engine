from pathlib import Path
import runpy

base = Path(__file__).parent
for name in ("patch142_ui_core.py", "patch142_ui_runtime.py", "patch142_ui_capital.py"):
    runpy.run_path(str(base / name), run_name="__main__")
print("0.14.2 UX repair bundle applied")
