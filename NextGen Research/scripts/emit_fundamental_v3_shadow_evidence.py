"""Read-only Fundamental V3 evidence handoff; NEVER modifies recommendations/orders.

python emit_fundamental_v3_shadow_evidence.py --snapshot snapshot.json \
  --installed-engine PATH_TO_NATIVE_ENGINE --data-root PATH_TO_DATA \
  --output fundamental_v3_shadow.json
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

def build(snapshot: dict, engine: Path, root: Path) -> dict:
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("candidates"), list):
        raise ValueError("LIVE_SNAPSHOT_CANDIDATES_REQUIRED")
    run = snapshot.get("run") or {}
    session = date.fromisoformat(run["market_session"])
    # Same conservative cutoff as existing compare_live_snapshot_recovery.py
    cutoff = datetime.combine(session + timedelta(days=1),
                              time(5, 29, 59, 999999), tzinfo=ZoneInfo("Asia/Kolkata"))
    sys.path.insert(0, str(engine))
    from stock_app import fundamental_v3
    original = {k: hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
                for k in ["snapshot_sha256"]}
    rows = []
    for item in snapshot["candidates"]:
        sym = item["symbol"]
        decision = item.get("live_decision") or {}
        fund = ((decision.get("evidence") or {}).get("fundamental") or {})
        basis = fund.get("reporting_basis") or "CONSOLIDATED"
        result = fundamental_v3.analyze(root, sym, decision_timestamp=cutoff.isoformat(),
                                         latest_price=item.get("latest_close"),
                                         basis_preference=basis)
        components = result.get("score_components") or {}
        missing = [k for k, v in components.items() if v.get("signal") is None]
        rows.append({
            "symbol": sym, "authority": "SHADOW_ONLY",
            "legacy_final_action": decision.get("final_action"),
            "legacy_executable": decision.get("executable"),
            "v3_status": result.get("status"), "v3_available": result.get("available"),
            "v3_component_coverage": result.get("score_component_coverage"),
            "v3_missing_score_components": missing,
            "v3_quarter_end": result.get("quarter_end"),
            "v3_filing_available_at": result.get("effective_availability_ts"),
            "v3_source_panel": (result.get("sources") or {}).get("canonical_panel"),
            "promotion_allowed": False
        })
    return {"schema": "SRE_V3_SHADOW_HANDOFF_V1", "authority": "SHADOW_ONLY",
            "market_session": session.isoformat(), "decision_cutoff": cutoff.isoformat(),
            "run_id": run.get("run_id"), **original,
            "candidate_count": len(rows),
            "v3_available_count": sum(x["v3_available"] is True for x in rows),
            "v3_ready_count": sum(x["v3_status"] == "READY" for x in rows),
            "legacy_decisions_modified": False, "paper_orders_modified": False,
            "rows": rows}

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--snapshot", type=Path, required=True)
    p.add_argument("--installed-engine", type=Path, required=True)
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    # Output separate from engine, data and input; no implicit overwrite.
    output = a.output.resolve()
    if output.exists():
        raise FileExistsError(output)
    if not (a.installed_engine / "stock_app" / "fundamental_v3.py").is_file():
        raise FileNotFoundError("Installed Fundamental V3 source missing")
    report = build(json.loads(a.snapshot.read_text(encoding="utf-8")),
                   a.installed_engine.resolve(), a.data_root.resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"shadow candidates={report['candidate_count']} available={report['v3_available_count']} ready={report['v3_ready_count']}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
