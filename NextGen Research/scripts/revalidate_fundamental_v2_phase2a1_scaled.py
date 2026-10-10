from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "NextGen Research"
sys.path.insert(0, str(ROOT))

from fundamental_research_v2_phase2a.core import coverage_audit  # noqa: E402
from fundamental_research_v2_phase2a.validation import validate_pit_events  # noqa: E402

UNIVERSE = ROOT / "fundamental_research_v2_phase2a" / "phase2a1_universe_resolution.json"
OUT = ROOT / "results" / "fundamental_v2_phase2a1_scaled"
EVENTS = OUT / "all_target_events.json"
VALIDATION = OUT / "scaled_pit_validation.json"
SUMMARY = OUT / "scaled_summary.json"
COVERAGE = OUT / "scaled_coverage_audit.json"


def main() -> int:
    universe_doc = json.loads(UNIVERSE.read_text(encoding="utf-8"))
    symbols = universe_doc["canonical_symbols"]
    if len(symbols) != 186 or len(set(symbols)) != 186:
        raise RuntimeError("CANONICAL_186_UNIVERSE_CONTRACT_FAILED")

    events = json.loads(EVENTS.read_text(encoding="utf-8"))
    if not isinstance(events, list):
        raise RuntimeError("SCALED_EVENTS_NOT_LIST")

    validation = validate_pit_events(
        events,
        required_symbols=symbols,
        require_all_target_quarters=True,
    )
    VALIDATION.write_text(
        json.dumps(validation, indent=2, sort_keys=True), encoding="utf-8"
    )

    coverage = coverage_audit(events, target_symbols=symbols)
    COVERAGE.write_text(
        json.dumps(coverage, indent=2, sort_keys=True), encoding="utf-8"
    )

    summary = json.loads(SUMMARY.read_text(encoding="utf-8")) if SUMMARY.exists() else {}
    summary["pit_validation_status"] = validation["status"]
    summary["pit_validation_failure_count"] = validation["failure_count"]
    summary["pit_validation_warning_count"] = validation["warning_count"]
    summary["authority"] = "SHADOW_ONLY"
    summary["production_model_changed"] = False
    summary["model_training_started"] = False
    SUMMARY.write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )

    print(json.dumps({
        "artifact_type": "FUNDAMENTAL_RESEARCH_V2_PHASE2A1_SCALED_REVALIDATION_V1",
        "event_count": len(events),
        "target_symbol_count": len(symbols),
        "validation_status": validation["status"],
        "failure_count": validation["failure_count"],
        "failure_codes": sorted({x.get("code") for x in validation["failures"]}),
        "warning_count": validation["warning_count"],
        "warning_codes": sorted({x.get("code") for x in validation["warnings"]}),
        "authority": "SHADOW_ONLY",
        "production_model_changed": False,
        "model_training_started": False,
    }, indent=2, sort_keys=True))

    if validation["failures"]:
        print(json.dumps({
            "failures": validation["failures"]
        }, indent=2, sort_keys=True))

    return 0 if validation["status"] == "PASS" else 4


if __name__ == "__main__":
    raise SystemExit(main())
