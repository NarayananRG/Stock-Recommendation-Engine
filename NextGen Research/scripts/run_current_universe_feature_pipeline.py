from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "NextGen Research"
sys.path.insert(0, str(ROOT))

from fundamental_research_v2_phase2a.derived_event_transforms import transform_all  # noqa: E402
from fundamental_research_v2_phase2a.event_feature_eligibility import eligibility_audit  # noqa: E402
from fundamental_research_v2_phase2a.risk_event_builder import build_risk_profiles, summarize_profiles  # noqa: E402
from fundamental_research_v2_phase2a.semantic_interpretation import semantic_audit  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    with args.panel.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["archive_gap"] = str(row.get("archive_gap") or "").lower() in {"true", "1", "yes"}

    eligibility = eligibility_audit(rows)
    if eligibility["eligible_event_count"] != (
        eligibility["pre_pit_candidate_count"] - eligibility["pit_order_rejection_count"]
    ):
        raise RuntimeError("CURRENT_UNIVERSE_ELIGIBILITY_ARITHMETIC_MISMATCH")
    events = transform_all(eligibility["eligible_events"], rows)
    if len(events) != eligibility["eligible_event_count"]:
        raise RuntimeError("CURRENT_UNIVERSE_TRANSFORM_COUNT_MISMATCH")
    semantics = semantic_audit(events)
    if semantics["derived_event_count"] != len(events):
        raise RuntimeError("CURRENT_UNIVERSE_SEMANTIC_COUNT_MISMATCH")
    profiles = build_risk_profiles(events)

    eligibility_dir = args.out / "fundamental_v2_phase2a5_event_feature_eligibility"
    event_dir = args.out / "fundamental_v2_phase2a5_derived_event_transforms"
    semantic_dir = args.out / "fundamental_v2_phase2a6_semantic_interpretation"
    risk_dir = args.out / "fundamental_v2_phase2a7_risk_events"
    for path in (eligibility_dir, event_dir, semantic_dir, risk_dir):
        path.mkdir(parents=True, exist_ok=True)

    (eligibility_dir / "eligibility_audit.json").write_text(
        json.dumps(eligibility, indent=2, sort_keys=True), encoding="utf-8"
    )
    with (event_dir / "derived_events.jsonl").open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
    (semantic_dir / "semantic_coverage_audit.json").write_text(
        json.dumps(semantics, indent=2, sort_keys=True), encoding="utf-8"
    )
    with (risk_dir / "risk_event_profiles.jsonl").open("w", encoding="utf-8") as handle:
        for profile in profiles:
            handle.write(json.dumps(profile, sort_keys=True) + "\n")

    risk_summary = summarize_profiles(profiles)
    summary = {
        "artifact_type": "CURRENT_LIVE_UNIVERSE_FEATURE_PIPELINE_V1",
        "authority": "SHADOW_ONLY",
        "panel_row_count": len(rows),
        "panel_symbol_count": len({row.get("symbol") for row in rows}),
        "eligible_event_count": eligibility["eligible_event_count"],
        "pit_order_rejection_count": eligibility["pit_order_rejection_count"],
        "derived_event_count": len(events),
        "risk_profile_count": len(profiles),
        "risk_event_profile_counts": risk_summary.get("profile_class_counts"),
        "strong_deterioration_transition_count": risk_summary.get("strong_deterioration_event_count"),
        "point_in_time_safe": True,
        "frozen_validation_counts_used": False,
        "production_model_changed": False,
        "automatic_yfinance_fallback": False,
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
