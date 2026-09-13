from __future__ import annotations

import argparse,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stage4a3.freeze_readiness import run_end_to_end_replay

def main()->None:
    parser=argparse.ArgumentParser();parser.add_argument("--repo-root",type=Path,required=True);parser.add_argument("--output-root",type=Path,default=ROOT/"results");parser.add_argument("--named-only",action="store_true");parser.add_argument("--random-workers",type=int,default=4)
    args=parser.parse_args();print(json.dumps(run_end_to_end_replay(args.repo_root.resolve(),args.output_root.resolve(),not args.named_only,args.random_workers),indent=2))

if __name__=="__main__":main()
