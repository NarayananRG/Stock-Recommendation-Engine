"""Offline CLI for user-supplied authoritative files."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .framework import ingest_file, write_derived


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline authoritative-data ingestion")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("--source", required=True, choices=["NSE_SECURITY_MASTER", "NIFTY_CONSTITUENTS", "NSE_CORPORATE_ACTIONS", "SECURITY_IDENTITY"])
    ingest.add_argument("--input", required=True)
    ingest.add_argument("--archive-id", required=True)
    ingest.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    rows = ingest_file(args.source, args.input, archive_id=args.archive_id)
    write_derived(args.output, {"source": args.source, "archive_id": args.archive_id,
                                "source_sha256": hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),
                                "record_count": len(rows), "records": rows,
                                "authority": "RESEARCH_ONLY", "network_used": False})
    print(json.dumps({"status": "PASS", "records": len(rows), "output": args.output}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
