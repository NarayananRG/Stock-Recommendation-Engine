"""Reconstruct and SHA-256 verify any Stage 3 artifact split into .partNNN files."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    root = args.manifest.parent
    for item in manifest.get("split_artifacts", []):
        target = root / item["artifact"]
        parts = [root / name for name in item["parts"]]
        digest = hashlib.sha256()
        with target.open("wb") as output:
            for part in parts:
                payload = part.read_bytes(); output.write(payload); digest.update(payload)
        actual = digest.hexdigest()
        if actual != item["sha256"]:
            target.unlink(missing_ok=True)
            raise RuntimeError(f"Hash mismatch for {target}: {actual}")
        print(f"verified {target}: {actual}")


if __name__ == "__main__":
    main()
