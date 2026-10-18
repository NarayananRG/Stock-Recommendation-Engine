"""Offline, read-only overnight CI validation across SRE subsystems."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
REPORT=Path(os.environ.get("SRE_AUDIT_REPORT_DIR","audit-output"))
REPORT.mkdir(parents=True,exist_ok=True)
CASES=[
 ("router_integrated",".ci/native140/test_live_decision_v1.py"),
 ("fundamental_pit",".ci/recommendation_audit/test_fundamental_pit_gate.py"),
 ("technical_boundaries",".ci/recommendation_audit/test_technical_batch.py"),
 ("weekly_session",".ci/recommendation_audit/test_thesis_session_consistency.py"),
 ("ranking_paper",".ci/recommendation_audit/test_rank_plan_batch.py"),
 ("position_monitor",".ci/recommendation_audit/test_position_metadata_batch.py"),
 ("technical_price",".ci/recommendation_audit/test_technical_price_sanity.py"),
 ("technical_formulas",".ci/recommendation_audit/test_technical_v2_formulas.py"),
 ("global_research",".ci/global_event_research/test_global_register.py"),
 ("official_recovery","NextGen Research/tests/run_current_universe_recovery_tests.py"),
 ("mixed_event_shadow","NextGen Research/tests/run_mixed_event_shadow_tests.py"),
 ("canonical_mapping","NextGen Research/tests/run_fundamental_research_v2_phase2a2_mapping_tests.py"),
 ("stage6_event_pipeline","Stage 6/tests/run_stage6_2a_tests.py"),
]
results=[]
for name,path in CASES:
 file=ROOT/path
 if not file.is_file():
  (REPORT/(name+".log")).write_text("TEST_FILE_ABSENT: "+path+"\n",encoding="utf-8")
  results.append({"test":name,"path":path,"status":"MISSING","exit_code":None,"diagnosis":"TEST_FILE_ABSENT","duration_seconds":0})
  continue
 started=time.monotonic()
 try:
  run=subprocess.run([sys.executable,str(file)],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=180)
  (REPORT/(name+".log")).write_text(run.stdout[-300000:],encoding="utf-8")
  lines=run.stdout.splitlines()
  markers=[line.strip()[:350] for line in lines if any(word in line.lower() for word in ("traceback", "assertionerror", "modulenotfounderror", "failed", "error:", "fatal:", "missing", "not found"))]
  results.append({"test":name,"path":path,"status":"PASS" if run.returncode==0 else "FAIL","exit_code":run.returncode,"diagnosis":markers[-12:] if run.returncode else [],"duration_seconds":round(time.monotonic()-started,2)})
 except subprocess.TimeoutExpired as exc:
  partial=exc.stdout or b""
  if isinstance(partial,bytes): partial=partial.decode("utf-8",errors="replace")
  (REPORT/(name+".log")).write_text(str(partial)[-300000:],encoding="utf-8")
  results.append({"test":name,"path":path,"status":"TIMEOUT","exit_code":None,"diagnosis":"TEST_EXCEEDED_180_SECONDS","duration_seconds":round(time.monotonic()-started,2)})
counts={status:sum(r["status"]==status for r in results) for status in ("PASS","FAIL","MISSING","TIMEOUT")}
source_sha=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
summary={"schema":"SRE_OVERNIGHT_READ_ONLY_AUDIT_V1","generated_utc":datetime.now(timezone.utc).isoformat(),"git_ref":source_sha,"workflow_trigger_sha":os.environ.get("GITHUB_SHA",""),"authority":"AUDIT_ONLY","production_modified":False,"counts":counts,"results":results}
(REPORT/"summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
with (REPORT/"summary.md").open("w",encoding="utf-8") as f:
 f.write("# SRE overnight validation\n\nNo production write or trading authority.\n\n| Check | Status |\n|---|---|\n")
 for x in results:f.write(f"| {x['test']} | {x['status']} |\n")
 f.write(f"\nTotals: {counts}. Audited checkout: `{source_sha}`. Workflow trigger: `{os.environ.get('GITHUB_SHA','')}`.\n")
 f.write("\n## Failure triage\n\n")
 for x in results:
  if x["status"]!="PASS":f.write(f"- **{x['test']}**: {x.get('diagnosis')}; see {x['test']}.log\n")
print(json.dumps(summary,indent=2))
sys.exit(0 if all(x["status"]=="PASS" for x in results) else 1)
