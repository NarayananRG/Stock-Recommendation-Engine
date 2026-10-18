from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import hashlib
import json
import math
from pathlib import Path
from typing import Any


HORIZON_SESSIONS = 20


def classify_mixed_event(fundamental: dict[str, Any]) -> dict[str, Any]:
    """Score mixed evidence without changing any production recommendation."""
    risk = fundamental.get("risk_event") or {}
    if risk.get("event_profile") != "MIXED_DIRECTIONAL":
        return {"eligible": False, "classification": "NOT_MIXED_DIRECTIONAL"}

    positive = 0.0
    negative = 0.0
    covered_weight = 0.0
    contributions: dict[str, float] = {}
    for name, component in (fundamental.get("score_components") or {}).items():
        signal = component.get("signal")
        weight = component.get("weight")
        if isinstance(signal, bool) or isinstance(weight, bool):
            continue
        if not isinstance(signal, (int, float)) or not isinstance(weight, (int, float)):
            continue
        signal = float(signal)
        weight = float(weight)
        if not math.isfinite(signal) or not math.isfinite(weight) or weight <= 0.0:
            continue
        contribution = max(-1.0, min(1.0, signal)) * weight
        contributions[name] = contribution
        positive += max(contribution, 0.0)
        negative += max(-contribution, 0.0)
        covered_weight += weight

    normalized_positive = positive / covered_weight if covered_weight else 0.0
    normalized_negative = negative / covered_weight if covered_weight else 0.0
    balance = normalized_positive - normalized_negative
    freshness = fundamental.get("filing_freshness")
    hard_block = bool(
        risk.get("strong_deterioration_transition") is True
        or fundamental.get("structural_deterioration") is True
        or freshness not in {"CURRENT_FOR_DECISION_TIME", "CURRENT"}
        or fundamental.get("point_in_time_safe") is not True
    )
    if hard_block:
        classification = "MIXED_RISK_BLOCKED"
    elif covered_weight < 0.65:
        classification = "MIXED_INSUFFICIENT_COVERAGE"
    elif balance >= 0.20:
        classification = "MIXED_POSITIVE_BALANCE"
    elif balance <= -0.20:
        classification = "MIXED_NEGATIVE_BALANCE"
    else:
        classification = "MIXED_BALANCED"
    return {
        "eligible": True,
        "classification": classification,
        "positive_weighted_evidence": round(normalized_positive, 8),
        "negative_weighted_evidence": round(normalized_negative, 8),
        "net_evidence_balance": round(balance, 8),
        "covered_feature_weight": round(covered_weight, 8),
        "strong_deterioration_transition": risk.get("strong_deterioration_transition") is True,
        "filing_freshness": freshness,
        "contributions": contributions,
        "production_action_changed": False,
        "production_rank_changed": False,
        "promotion_allowed": False,
    }


def evaluate_snapshots(paths: list[Path], as_of: date) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    sessions: set[str] = set()
    run_ids: set[str] = set()
    per_artifact: list[dict[str, Any]] = []
    repeatability: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    evidence_revisions: dict[tuple[str, str], set[str]] = defaultdict(set)
    for path in sorted(paths):
        payload = json.loads(path.read_text(encoding="utf-8"))
        run = payload.get("run") or {}
        session = str(run.get("market_session") or "")
        run_id = str(run.get("run_id") or "")
        sessions.add(session)
        run_ids.add(run_id)
        counts: Counter[str] = Counter()
        mixed = 0
        for candidate in payload.get("candidates") or []:
            decision = candidate.get("live_decision") or {}
            fundamental = ((decision.get("evidence") or {}).get("fundamental") or {})
            shadow = classify_mixed_event(fundamental)
            if not shadow["eligible"]:
                continue
            mixed += 1
            counts[shadow["classification"]] += 1
            symbol = str(candidate.get("symbol") or "")
            evidence_hash = hashlib.sha256(
                json.dumps(fundamental, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
            ).hexdigest()
            repeatability[(run_id, symbol, evidence_hash)].add(shadow["classification"])
            evidence_revisions[(run_id, symbol)].add(evidence_hash)
            records.append(
                {
                    "artifact": path.name,
                    "run_id": run_id,
                    "market_session": session,
                    "symbol": symbol,
                    "production_action": decision.get("final_action"),
                    "production_rank": candidate.get("rank"),
                    **shadow,
                }
            )
        per_artifact.append(
            {"artifact": path.name, "run_id": run_id, "market_session": session, "mixed_events": mixed, "shadow_classes": dict(counts)}
        )

    valid_sessions = sorted(s for s in sessions if s)
    span = 0
    if valid_sessions:
        first = date.fromisoformat(valid_sessions[0])
        last = min(as_of, date.fromisoformat(valid_sessions[-1]))
        cursor = first
        while cursor <= last:
            if cursor.weekday() < 5:
                span += 1
            cursor = date.fromordinal(cursor.toordinal() + 1)
    maturity = max(0, span - 1)
    unstable = [
        {"run_id": run_id, "symbol": symbol, "evidence_hash": evidence_hash, "classifications": sorted(values)}
        for (run_id, symbol, evidence_hash), values in repeatability.items()
        if len(values) > 1
    ]
    return {
        "schema": "SRE_MIXED_EVENT_SHADOW_EVALUATION_V1",
        "authority": "SHADOW_ONLY",
        "method": "weighted signed score-component evidence with PIT/freshness and strong-deterioration safety blocks",
        "snapshot_artifacts": len(paths),
        "distinct_run_ids": len(run_ids),
        "market_sessions": valid_sessions,
        "per_artifact": per_artifact,
        "records": records,
        "repeatability_failures": unstable,
        "same_run_evidence_revisions": sum(1 for values in evidence_revisions.values() if len(values) > 1),
        "historical_validation": {
            "required_forward_sessions": HORIZON_SESSIONS,
            "available_session_span": maturity,
            "matured_out_of_sample_cohorts": 0,
            "outcome_quality_comparison_available": False,
            "calendar_weekdays_elapsed_upper_bound": maturity,
            "forward_outcome_evidence_supplied": False,
        },
        "production_action_changes": 0,
        "production_rank_changes": 0,
        "promotion_allowed": False,
        "promotion_blocker": (
            "No independently verified per-symbol 20-session forward price outcomes were supplied; calendar weekdays are not evidence of exchange sessions or performance."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshots", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    paths = list(args.snapshots.glob("*.json"))
    result = evaluate_snapshots(paths, args.as_of)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "mixed_event_shadow_evaluation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in {"records", "per_artifact"}}, indent=2))
    return 1 if result["repeatability_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
