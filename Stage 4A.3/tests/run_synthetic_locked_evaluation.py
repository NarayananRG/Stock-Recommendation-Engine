"""Prove the final evaluator refuses an immature ledger, without touching production."""
from __future__ import annotations
import json,shutil,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;sys.path.insert(0,str(ROOT))
from stage4a3.final_evaluation import evaluate
source=ROOT/"tests/SYNTHETIC_MATURED_PROSPECTIVE_FIXTURE";receipt=source/"tests/locked_evaluation_receipt.json"
with tempfile.TemporaryDirectory() as td:
    target=Path(td)/"tests/SYNTHETIC_LOCKED_PROSPECTIVE_FIXTURE";shutil.copytree(source,target)
    try:evaluate(REPO,target,"2024-06-01",target/"tests/locked_outputs");result={"Status":"FAIL","Reason":"evaluation unexpectedly unlocked"}
    except RuntimeError as exc:result={"Status":"PASS" if "PROSPECTIVE_EVALUATION_LOCKED" in str(exc) else "FAIL","As Of":"2024-06-01","Gate Result":"LOCKED","Premature Attempt Logged":(target/"prospective/audit/protocol_breaches.csv").exists(),"Production Data Written":0}
receipt.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8");print(json.dumps(result,indent=2));raise SystemExit(0 if result["Status"]=="PASS" else 1)
