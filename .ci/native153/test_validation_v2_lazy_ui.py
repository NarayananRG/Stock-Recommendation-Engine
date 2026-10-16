from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
patch = repo / ".ci" / "native153" / "patch153_ui.py"

with tempfile.TemporaryDirectory(prefix="sre-v2-ui-preflight-") as td:
    root = Path(td)
    front = root / "modern_ui" / "frontend"
    front.mkdir(parents=True)
    # Model the legacy bug deliberately: an earlier definition auto-runs replay.
    (front / "app.js").write_text(
        """
async function loadValidation(){
  bindValidationTabs(); setValidationTab('replay');
  await api('/api/validation/historical-replay',{method:'POST'});
  renderValidationPaper(await api('/api/validation/paper-portfolio'));
}
""",
        encoding="utf-8",
    )
    (front / "styles.css").write_text("", encoding="utf-8")

    env = dict(os.environ)
    env["SRE_ENGINE_ROOT"] = str(root)
    subprocess.run([sys.executable, str(patch)], check=True, env=env, cwd=str(repo))

    final = (front / "app.js").read_text(encoding="utf-8")
    marker = final.rfind("async function loadValidation()")
    if marker < 0:
        raise AssertionError("Final Validation V2 loadValidation override missing")
    body = final[marker:]
    if "VALIDATION_V2_LAZY_LOAD" not in body:
        raise AssertionError("Final loadValidation is not the V2 lazy-load override")
    # Inspect only the final loadValidation function, not historical functions above it.
    end = body.find("\n}\n")
    final_load = body if end < 0 else body[: end + 3]
    if "/api/validation/historical-replay" in final_load:
        raise AssertionError("Final loadValidation still auto-starts Historical Replay")
    if "/api/validation/paper-portfolio" not in final_load:
        raise AssertionError("Final loadValidation does not fetch Paper Portfolio")
    if "renderValidationReplayIdle()" not in final_load:
        raise AssertionError("Replay idle state is not rendered before user action")
    if "setValidationTab('paper')" not in final_load:
        raise AssertionError("Paper Portfolio is not the lightweight default tab")

print("VALIDATION V2 LAZY-LOAD UI PREFLIGHT PASS")
print("Opening Validation does not start replay; Paper Portfolio loads independently.")
