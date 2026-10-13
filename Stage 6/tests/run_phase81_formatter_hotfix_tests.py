from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    scratch = ROOT / "work"
    scratch.mkdir(exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="sre_phase81_formatter_", dir=scratch))
    try:
        engine = temp / "engine"
        (engine / "modern_ui/frontend").mkdir(parents=True)
        (engine / "modern_ui/api.py").write_text('APP_VERSION = "0.13.3-phase8-runtime-fix"\n', encoding="utf-8")
        (engine / "modern_ui/frontend/app.js").write_text(
            "function renderValidationReplay(r){return fmtPctFraction((r||{}).x||0)+fmtINR((r||{}).cash||100000)}\n"
            "function renderValidationPaper(p){return fmtINR((p||{}).nav||100000)+fmtPctFraction((p||{}).ret||0)}\n",
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["SRE_ENGINE_ROOT"] = str(engine)
        subprocess.run([sys.executable, str(ROOT / ".ci/native118/patch118_phase81_formatters.py")], cwd=ROOT, env=env, check=True)
        js = (engine / "modern_ui/frontend/app.js").read_text(encoding="utf-8")
        api = (engine / "modern_ui/api.py").read_text(encoding="utf-8")
        cases = [
            ("version bumped", '0.13.4-phase8-formatter-hotfix' in api),
            ("currency formatter defined", "function fmtINR(value)" in js),
            ("percent formatter defined", "function fmtPctFraction(value)" in js),
            ("currency formatter before renderer", js.find("function fmtINR(value)") < js.find("function renderValidationReplay")),
            ("percent formatter before renderer", js.find("function fmtPctFraction(value)") < js.find("function renderValidationReplay")),
        ]
        for name, ok in cases:
            print(f"{name}: {'PASS' if ok else 'FAIL'}")
        subprocess.run(["node", "--check", str(engine / "modern_ui/frontend/app.js")], check=True)
        return 0 if all(ok for _, ok in cases) else 1
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
