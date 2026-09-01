"""Standalone executable unit-test entry point for Stage 2B.1."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stage2b"))

from policies import PolicyConfig
from Stock_Alert_Stage2B_1_Dynamic_Management import self_tests


def main() -> int:
    config = PolicyConfig.from_mapping(json.loads((ROOT / "config/stage2b_1_policy_config.json").read_text(encoding="utf-8")))
    results = self_tests(config)
    destination = ROOT / "tests/stage2b_1_unit_test_results.csv"
    results.to_csv(destination, index=False)
    print(results.to_string(index=False))
    return int((results["Status"] != "PASS").any())


if __name__ == "__main__":
    raise SystemExit(main())
