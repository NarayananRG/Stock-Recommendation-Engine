from __future__ import annotations
import inspect
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

engine=Path(os.environ["SRE_ENGINE_ROOT"]).resolve()
port=int(os.environ.get("SRE_ANALYSIS_E2E_PORT","8891"))
app_data=Path(tempfile.mkdtemp(prefix="sre0148-analysis-e2e-"))
env=dict(os.environ)
env["SRE_BROWSER_PORT"]=str(port)
env["SRE_BROWSER_APP_DATA"]=str(app_data)
env.setdefault("SRE_EXPECTED_SESSION_NOW","2026-10-15T19:15:00+05:30")

sys.path.insert(0,str(engine))
from modern_ui.api import ModernAppContext
print("FINAL ensure_analysis_run SOURCE:")
print(inspect.getsource(ModernAppContext.ensure_analysis_run))

proc=subprocess.Popen(
    [sys.executable,".ci/native145/serve_runtime.py"],
    cwd=str(Path.cwd()),
    env=env,
)
base="http://127.0.0.1:"+str(port)

def request(path:str, method:str="GET"):
    req=urllib.request.Request(base+path,method=method)
    with urllib.request.urlopen(req,timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))

try:
    for _ in range(120):
        try:
            request("/api/health")
            break
        except Exception:
            time.sleep(.25)
    else:
        raise RuntimeError("FastAPI runtime did not start")

    before=request("/api/post-close-daily-flow")
    print("BEFORE",json.dumps(before,indent=2,default=str))
    expected=before.get("expected_market_session") or before.get("target_session")
    official=before.get("latest_available_official_session")
    if expected != "2026-10-15":
        raise AssertionError("Expected-session fixture mismatch: "+str(expected))
    if official != expected:
        raise AssertionError("Official data not current before analysis E2E: official="+str(official)+" expected="+str(expected))

    result=request("/api/post-close-daily-flow?force=true","POST")
    print("POST_RESULT",json.dumps(result,indent=2,default=str))
    after=request("/api/post-close-daily-flow")
    consistency=request("/api/ui-consistency")
    print("AFTER",json.dumps(after,indent=2,default=str))
    print("CONSISTENCY",json.dumps(consistency,indent=2,default=str))

    active=after.get("active_analysis_session")
    if active != expected:
        raise AssertionError("Post-close flow failed to advance analysis: active="+str(active)+" expected="+str(expected))
    if after.get("analysis_current") is not True:
        raise AssertionError("Analysis did not become current: "+str(after.get("analysis_status")))
    if after.get("run_status") != "READY":
        raise AssertionError("Post-close status not READY after recompute: "+str(after.get("run_status")))
    if consistency.get("active_analysis_session") != expected:
        raise AssertionError("UI consistency active session mismatch: "+str(consistency))
    if consistency.get("latest_official_session") != expected:
        raise AssertionError("UI consistency official session mismatch: "+str(consistency))
    if int(after.get("recommendation_count") or 0) <= 0:
        raise AssertionError("No active recommendation rows after current-session recompute")
    print("0.14.8 LIVE ANALYSIS SESSION E2E PASS")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
