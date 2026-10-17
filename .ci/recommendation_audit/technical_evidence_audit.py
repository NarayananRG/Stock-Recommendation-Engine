from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def audit_technical_evidence(payload: dict[str, Any]) -> list[str]:
    """Return deterministic quality violations for a serialized live snapshot."""
    violations: list[str] = []
    run_session = str((payload.get("run") or {}).get("market_session") or "")
    candidates = payload.get("candidates") or []
    if not candidates:
        return ["snapshot has no candidates"]

    for candidate in candidates:
        symbol = str(candidate.get("symbol") or "<unknown>")
        decision = candidate.get("live_decision") or {}
        technical = ((decision.get("evidence") or {}).get("technical") or {})
        prefix = f"{symbol}: "
        if technical.get("schema") != "SRE_TECHNICAL_INTELLIGENCE_V2":
            violations.append(prefix + "unexpected technical schema")
        status = technical.get("status")
        if status not in {"READY", "LIMITED_HISTORY"}:
            violations.append(prefix + "unexpected technical status")
        if technical.get("point_in_time_safe") is not True:
            violations.append(prefix + "point_in_time_safe is not true")
        if run_session and str(technical.get("as_of_session") or "") != run_session:
            violations.append(prefix + "technical session does not match run session")
        bars = technical.get("bars")
        if not _number(bars) or bars <= 0:
            violations.append(prefix + "no valid bars")
        elif status == "READY" and bars < 220:
            violations.append(prefix + "READY evidence has fewer than 220 bars")
        elif status == "LIMITED_HISTORY" and bars >= 220:
            violations.append(prefix + "LIMITED_HISTORY evidence has 220 or more bars")

        for name, low, high in (
            ("technical_score", 0.0, 100.0),
            ("evidence_coverage", 0.0, 1.0),
        ):
            value = technical.get(name)
            if not _number(value) or not math.isfinite(float(value)) or not low <= float(value) <= high:
                violations.append(prefix + f"invalid {name}")

        components = technical.get("score_components") or {}
        weight_sum = 0.0
        for name, component in components.items():
            signal = component.get("signal")
            weight = component.get("weight")
            # A limited-history lane may explicitly omit a component signal.
            if signal is not None and (not _number(signal) or not math.isfinite(float(signal)) or not -1.0 <= float(signal) <= 1.0):
                violations.append(prefix + f"invalid {name} signal")
            if not _number(weight) or not math.isfinite(float(weight)) or not 0.0 <= float(weight) <= 1.0:
                violations.append(prefix + f"invalid {name} weight")
            else:
                weight_sum += float(weight)
        if not math.isclose(weight_sum, 1.0, rel_tol=0.0, abs_tol=1e-9):
            violations.append(prefix + f"component weights sum to {weight_sum:.12g}, not 1")

        def walk(value: Any, path: str) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    walk(child, f"{path}.{key}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    walk(child, f"{path}[{index}]")
            elif _number(value) and not math.isfinite(float(value)):
                violations.append(prefix + f"non-finite numeric value at {path}")

        walk(technical, "technical")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.snapshot.read_text(encoding="utf-8"))
    violations = audit_technical_evidence(payload)
    print(json.dumps({"candidates": len(payload.get("candidates") or []), "violations": violations}, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
