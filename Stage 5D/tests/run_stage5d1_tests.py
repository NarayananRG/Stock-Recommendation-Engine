from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from stage5d.allocator import allocate_candidates
from stage5d.horizon import HorizonPreference
from stage5d.portfolio_state import OpenPosition, PortfolioSnapshot
from stage5d.recommendation_contract import contract_payload
from stage5d.user_profile import InvestmentProfile, ProfileStore


def profile(capital: int, horizon: HorizonPreference = HorizonPreference.THREE_MONTHS, version: int = 1) -> InvestmentProfile:
    from decimal import Decimal
    return InvestmentProfile(version, "2026-09-13T00:00:00+00:00", Decimal(str(capital)), horizon)


def candidate(ticker: str = "AAA.NS", **changes: object) -> dict[str, object]:
    value = {"signal_id": f"S-{ticker}", "ticker": ticker, "signal_date": "2026-09-14", "deterministic_signal": "BUY", "entry_low": 99, "entry_high": 100, "sizing_entry_price": 100, "stop": 99, "target_1": 110, "target_2": 120, "deterministic_rank": 1}
    value.update(changes)
    return value


def main() -> int:
    rows: list[dict[str, object]] = []
    def check(number: int, name: str, passed: bool, details: str = "") -> None:
        rows.append({"Test Number": number, "Test": name, "Status": "PASS" if passed else "FAIL", "Details": details})

    clean5 = allocate_candidates(profile(5000), [], [candidate()])
    check(1, "INR 5,000 clean portfolio", clean5.portfolio_summary["capital_ceiling_inr"] == 5000 and clean5.portfolio_summary["current_market_value_of_open_positions_inr"] == 0)
    clean20 = allocate_candidates(profile(20000), [], [candidate()])
    check(2, "INR 20,000 clean portfolio", clean20.portfolio_summary["available_capital_before_inr"] == 20000)
    with tempfile.TemporaryDirectory() as directory:
        store = ProfileStore(Path(directory)); old = store.save(20000, "THREE_MONTHS", effective_timestamp="2026-09-13T00:00:00+00:00"); old_recommendation = deepcopy(allocate_candidates(old, [], [candidate()]).recommendations[0]); new = store.save(15000, "THREE_MONTHS", effective_timestamp="2026-09-14T00:00:00+00:00")
        check(3, "capital change creates linked version", old.profile_version == 1 and new.profile_version == 2 and new.previous_profile_version == 1 and new.to_dict()["maximum_total_capital_inr"] == new.to_dict()["capital_ceiling_inr"] == 15000.0)
        check(22, "profile change does not mutate old recommendation", store.load(1).to_dict() == old.to_dict() and old_recommendation == allocate_candidates(store.load(1), [], [candidate()]).recommendations[0] and old_recommendation["profile_version"] == 1)
    position = OpenPosition.create("OPEN.NS", 170, 100, 90); over = PortfolioSnapshot.create(15000, [position])
    check(4, "portfolio becomes OVER_NEW_CAP", over.portfolio_status == "OVER_NEW_CAP" and float(over.capital_overage_inr) == 2000)
    check(5, "cap reduction does not force sale", over.positions == (position,) and over.number_of_open_positions == 1)
    blocked = allocate_candidates(profile(15000), [position], [candidate()])
    check(6, "new BUY blocked while above cap", blocked.recommendations[0]["portfolio_action_status"] == "BLOCKED_PORTFOLIO_OVER_CAP" and blocked.recommendations[0]["recommended_quantity"] == 0)
    check(7, "integer quantities only", isinstance(clean20.recommendations[0]["recommended_quantity"], int))
    expensive = allocate_candidates(profile(5000), [], [candidate(sizing_entry_price=6000, entry_low=6000, entry_high=6000, stop=5999, target_1=6100, target_2=6200)])
    check(8, "share price greater than available cash", expensive.recommendations[0]["portfolio_action_status"] == "WATCH_INSUFFICIENT_CAPITAL")
    high_risk = allocate_candidates(profile(5000), [], [candidate(stop=50)])
    check(9, "one-share risk exceeds risk budget", high_risk.recommendations[0]["portfolio_action_status"] == "WATCH_RISK_BUDGET_TOO_SMALL")
    cap_bound = clean20.recommendations[0]
    check(10, "position 25 percent cap binds", cap_bound["recommended_quantity"] == cap_bound["max_qty_by_position_cap"] == 50)
    cash_position = OpenPosition.create("OLD.NS", 190, 100, 100); cash_bound = allocate_candidates(profile(20000), [cash_position], [candidate()]).recommendations[0]
    check(11, "cash limit binds", cash_bound["recommended_quantity"] == cash_bound["max_qty_by_cash"] == 10)
    risk_bound = allocate_candidates(profile(20000), [], [candidate(stop=95)]).recommendations[0]
    check(12, "risk limit binds", risk_bound["recommended_quantity"] == risk_bound["max_qty_by_risk"] == 30)
    five = [OpenPosition.create(f"P{i}.NS", 1, 100, 100) for i in range(5)]; maxed = allocate_candidates(profile(20000), five, [candidate()])
    check(13, "maximum five positions enforced", maxed.recommendations[0]["portfolio_action_status"] == "BLOCKED_MAX_POSITIONS")
    check(14, "remaining cash retained", clean5.portfolio_summary["cash_after_proposed_orders_inr"] > 0)
    many = allocate_candidates(profile(20000), [], [candidate(f"T{i}.NS", deterministic_rank=i) for i in range(1, 7)])
    check(15, "multiple allocations never exceed ceiling", many.portfolio_summary["recommended_new_deployment_inr"] <= 20000 and many.portfolio_summary["cash_after_proposed_orders_inr"] >= 0)
    repeat = allocate_candidates(profile(20000), [], list(reversed([candidate("B.NS", deterministic_rank=2), candidate("A.NS", deterministic_rank=1)])))
    repeat2 = allocate_candidates(profile(20000), [], [candidate("A.NS", deterministic_rank=1), candidate("B.NS", deterministic_rank=2)])
    check(16, "allocation deterministic under identical inputs", repeat.recommendations == repeat2.recommendations and repeat.portfolio_summary == repeat2.portfolio_summary)
    one = allocate_candidates(profile(5000, HorizonPreference.ONE_MONTH), [], [candidate(validated_holding_sessions=10, holding_evidence_source="VALIDATED_DETERMINISTIC")])
    check(17, "ONE_MONTH accepted with validated evidence", one.recommendations[0]["horizon_status"] == "ELIGIBLE" and one.recommendations[0]["horizon_session_limit"] == 21)
    check(18, "THREE_MONTHS accepted", clean5.recommendations[0]["horizon_status"] == "ELIGIBLE" and clean5.recommendations[0]["horizon_session_limit"] == 63)
    six = allocate_candidates(profile(5000, HorizonPreference.SIX_MONTHS), [], [candidate()])
    check(19, "SIX_MONTHS rejected as unvalidated", six.recommendations[0]["horizon_status"] == "UNSUPPORTED_NOT_VALIDATED" and six.recommendations[0]["recommended_quantity"] == 0)
    mismatch = allocate_candidates(profile(5000, HorizonPreference.ONE_MONTH), [], [candidate(validated_holding_sessions=30, holding_evidence_source="VALIDATED_DETERMINISTIC")])
    check(20, "horizon mismatch blocks actionable BUY", mismatch.recommendations[0]["portfolio_action_status"] == "WATCH_HORIZON_MISMATCH")
    check(21, "profile version stored in recommendation", clean20.recommendations[0]["profile_version"] == 1)
    base = candidate(); with_ml = deepcopy(base); with_ml.update({"R3 Score": 0.999, "ml_probability": 0.001, "confidence": "HIGH"})
    allocation_a = allocate_candidates(profile(20000), [], [base]); allocation_b = allocate_candidates(profile(20000), [], [with_ml])
    check(23, "ML fields cannot affect allocation", allocation_a.recommendations == allocation_b.recommendations and allocation_a.portfolio_summary == allocation_b.portfolio_summary)
    changed = subprocess.check_output(["git", "diff", "--name-only", "stage4a3-prospective-shadow-protocol-baseline", "--", "Stage 4A.3"], cwd=REPO, text=True).strip()
    check(24, "Stage 4A.3 protected files unchanged", changed == "", changed)

    results = ROOT / "results"; results.mkdir(parents=True, exist_ok=True)
    with (results / "stage5d1_test_results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(sorted(rows, key=lambda row: int(row["Test Number"])))
    (results / "stage5d1_contract.json").write_text(json.dumps(contract_payload(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    counts = {status: sum(row["Status"] == status for row in rows) for status in ("PASS", "FAIL")}
    print(json.dumps(counts, sort_keys=True))
    return 0 if counts["FAIL"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
