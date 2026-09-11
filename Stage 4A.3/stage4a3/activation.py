from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .hash_chain import genesis_hash
from .hashing import canonical_json_hash
from .protocol_integrity import verify_protocol_material


def signal_is_after_activation(activation: dict, snapshot_created_utc: str, signal_date: str) -> bool:
    activated=datetime.fromisoformat(activation["Activation UTC"])
    created=datetime.fromisoformat(snapshot_created_utc)
    local_activation_date=activated.astimezone(ZoneInfo("Asia/Kolkata")).date()
    return created > activated and datetime.fromisoformat(signal_date).date() > local_activation_date


def git(repo: Path,*args: str) -> str:
    return subprocess.check_output(["git","-c",f"safe.directory={repo.as_posix()}",*args],cwd=repo,text=True).strip()


def activate(repo: Path, stage_root: Path) -> dict:
    config=json.loads((stage_root/"config/stage4a3_protocol.json").read_text(encoding="utf-8"));tag=config["protocol_tag"]
    try:
        integrity=verify_protocol_material(repo,stage_root,tag,require_head=True)
    except Exception as exc:
        raise RuntimeError("ACTIVATION_BLOCKED_PROTOCOL_DRIFT") from exc
    protocol_commit=integrity["protocol_commit"]
    identity=json.loads((stage_root/"results/stage4a3_protocol_identity.json").read_text(encoding="utf-8"))
    audit=stage_root/"prospective/audit";record_path=audit/"activation_record.json"
    if record_path.exists():
        raise FileExistsError("ACTIVATION_RECORD_IMMUTABLE")
    bundle=json.loads((stage_root/"models/frozen_2026/model_bundle_manifest.json").read_text(encoding="utf-8"));universe=json.loads((stage_root/"results/stage4a3_frozen_universe_hash.json").read_text(encoding="utf-8"))
    now=datetime.now(timezone.utc);local=now.astimezone(ZoneInfo("Asia/Kolkata"));record={"Protocol Tag":tag,"Protocol Commit":protocol_commit,"Model Bundle Hash":bundle["FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH"],"Activation UTC":now.isoformat(),"Activation Asia/Kolkata":local.isoformat(),"Activation Local Date":local.date().isoformat(),"Earliest Eligible Signal Date":(local.date()+timedelta(days=1)).isoformat(),"Earliest Eligible Signal Date Rule":"FIRST_CAPTURED_MARKET_SIGNAL_DATE_STRICTLY_AFTER_ACTIVATION_LOCAL_DATE","Frozen Universe Hash":universe["FROZEN_UNIVERSE_HASH"],"Genesis Chain Hash":genesis_hash(protocol_commit,bundle["FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH"]),"Protocol Identity":identity["PROTOCOL_ID"]}
    record["ACTIVATION_ID"]="S4A3_ACTIVATION_"+canonical_json_hash(record)[:16];audit.mkdir(parents=True,exist_ok=True);record_path.write_text(json.dumps(record,indent=2,sort_keys=True)+"\n",encoding="utf-8",newline="\n");return record


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument("--repo-root",type=Path,required=True);parser.add_argument("--stage-root",type=Path,required=True);args=parser.parse_args();print(json.dumps(activate(args.repo_root.resolve(),args.stage_root.resolve()),indent=2))


if __name__=="__main__":main()
