from __future__ import annotations
import argparse,json
from pathlib import Path
from .hash_chain import genesis_hash
from .immutable_ledger import verify_ledger

def main() -> None:
    p=argparse.ArgumentParser();p.add_argument("--repo-root",type=Path,required=True);a=p.parse_args();root=a.repo_root.resolve()/"Stage 4A.3"
    activation=json.loads((root/"prospective/audit/activation_record.json").read_text(encoding="utf-8"))
    valid=verify_ledger(root/"prospective/snapshots",root/"prospective/audit",activation["Protocol Commit"],activation["Model Bundle Hash"],activation["Genesis Chain Hash"])
    print("LEDGER_CHAIN_PASS" if valid else "LEDGER_CHAIN_FAIL");raise SystemExit(0 if valid else 1)
if __name__=="__main__":main()
