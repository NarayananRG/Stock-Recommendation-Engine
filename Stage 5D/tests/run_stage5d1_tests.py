from __future__ import annotations

import csv
import json
import math
import subprocess
import sys
import tempfile
from copy import deepcopy
from decimal import Decimal
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
    return InvestmentProfile(version, "2026-09-13T00:00:00+00:00", Decimal(str(capital)), horizon)


def candidate(ticker: str = "AAA.NS", **changes: object) -> dict[str, object]:
    value = {
        "signal_id": f"S-{ticker}", "ticker": ticker, "signal_date": "2026-09-14",
        "deterministic_signal": "BUY", "entry_low": 99, "entry_high": 100,
        "sizing_entry_price": 100, "stop": 99, "target_1": 110,
        "target_2": 120, "deterministic_rank": 1,
    }
    value.update(changes)
    return value


def source_candidate(signal: str, ticker: str = "SRC.NS", *, nullable_levels: bool = False) -> dict[str, object]:
    level = math.nan if nullable_levels else 100
    return {
        "Signal ID": f"SOURCE-{ticker}-{signal}", "Ticker": ticker,
        "Signal Date": "2026-09-14", "Signal": signal,
        "Entry Low": math.nan if nullable_levels else 99, "Entry High": level,
        "Stop Loss": math.nan if nullable_levels else 99,
        "Target 1": math.nan if nullable_levels else 110,
        "Target 2": math.nan if nullable_levels else 120, "Rank": 1,
    }


def rejects_quantity(value: object) -> bool:
    try:
        OpenPosition.create("Q.NS", value, 100, 90)
    except ValueError:
        return True
    return False


def main() -> int:
    rows: list[dict[str, object]] = []

    def check(number: int, name: str, passed: bool, details: str = "") -> None:
        rows.append({"Test Number": number, "Test": name, "Status": "PASS" if passed else "FAIL", "Details": details})

    clean5 = allocate_candidates(profile(5000), [], [candidate()])
    check(1, "INR 5,000 clean portfolio", clean5.portfolio_summary["capital_ceiling_inr"] == 5000 and clean5.portfolio_summary["current_market_value_of_open_positions_inr"] == 0)
    clean20 = allocate_candidates(profile(20000), [], [candidate()])
    check(2, "INR 20,000 clean portfolio", clean20.portfolio_summary["available_capital_before_inr"] == 20000)
    with tempfile.TemporaryDirectory() as directory:
        store = ProfileStore(Path(directory))
        old = store.save(20000, "THREE_MONTHS", effective_timestamp="2026-09-13T00:00:00+00:00")
        old_recommendation = deepcopy(allocate_candidates(old, [], [candidate()]).recommendations[0])
        new = store.save(15000, "THREE_MONTHS", effective_timestamp="2026-09-14T00:00:00+00:00")
        check(3, "capital change creates linked version", old.profile_version == 1 and new.profile_version == 2 and new.previous_profile_version == 1 and new.to_dict()["maximum_total_capital_inr"] == new.to_dict()["capital_ceiling_inr"] == 15000.0)
        check(22, "profile change does not mutate old recommendation", store.load(1).to_dict() == old.to_dict() and old_recommendation == allocate_candidates(store.load(1), [], [candidate()]).recommendations[0] and old_recommendation["profile_version"] == 1)
    position = OpenPosition.create("OPEN.NS", 170, 100, 90)
    over = PortfolioSnapshot.create(15000, [position])
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
    cash_position = OpenPosition.create("OLD.NS", 190, 100, 100)
    cash_bound = allocate_candidates(profile(20000), [cash_position], [candidate()]).recommendations[0]
    check(11, "cash limit binds", cash_bound["recommended_quantity"] == cash_bound["max_qty_by_cash"] == 10)
    risk_bound = allocate_candidates(profile(20000), [], [candidate(stop=95)]).recommendations[0]
    check(12, "risk limit binds", risk_bound["recommended_quantity"] == risk_bound["max_qty_by_risk"] == 30)
    five = [OpenPosition.create(f"P{i}.NS", 1, 100, 100) for i in range(5)]
    maxed = allocate_candidates(profile(20000), five, [candidate()])
    check(13, "maximum five positions enforced", maxed.recommendations[0]["portfolio_action_status"] == "BLOCKED_MAX_POSITIONS")
    check(14, "remaining cash retained", clean5.portfolio_summary["cash_after_proposed_orders_inr"] > 0)
    many = allocate_candidates(profile(20000), [], [candidate(f"T{i}.NS", deterministic_rank=i) for i in range(1, 7)])
    check(15, "multiple allocations never exceed ceiling", many.portfolio_summary["recommended_new_deployment_inr"] <= 20000 and many.portfolio_summary["cash_after_proposed_orders_inr"] >= 0)
    repeat = allocate_candidates(profile(20000), [], list(reversed([candidate("B.NS", deterministic_rank=2), candidate("A.NS", deterministic_rank=1)])))
    repeat2 = allocate_candidates(profile(20000), [], [candidate("A.NS", deterministic_rank=1), candidate("B.NS", deterministic_rank=2)])
    check(16, "allocation deterministic under identical inputs", repeat.recommendations == repeat2.recommendations and repeat.portfolio_summary == repeat2.portfolio_summary)
    one = allocate_candidates(profile(5000, HorizonPreference.ONE_MONTH), [], [candidate()])
    check(17, "ONE_MONTH accepted under fixed deterministic policy", one.recommendations[0]["horizon_status"] == "ELIGIBLE" and one.recommendations[0]["horizon_session_limit"] == 20)
    check(18, "THREE_MONTHS accepted", clean5.recommendations[0]["horizon_status"] == "ELIGIBLE" and clean5.recommendations[0]["horizon_session_limit"] == 63)
    six = allocate_candidates(profile(5000, HorizonPreference.SIX_MONTHS), [], [candidate()])
    check(19, "SIX_MONTHS rejected as unvalidated", six.recommendations[0]["horizon_status"] == "UNSUPPORTED_NOT_VALIDATED" and six.recommendations[0]["recommended_quantity"] == 0)
    policy_record = allocate_candidates(profile(5000, HorizonPreference.ONE_MONTH), [], [candidate(validated_holding_sessions=999, holding_evidence_source="CALLER_ASSERTED")])
    check(20, "horizon policy is independent of candidate predictions", policy_record.recommendations[0]["portfolio_action_status"] == "ACTIONABLE_BUY" and policy_record.recommendations[0]["management_policy_id"] == "STATIC_T2_20D")
    check(21, "profile version stored in recommendation", clean20.recommendations[0]["profile_version"] == 1)
    base = candidate()
    with_ml = deepcopy(base)
    with_ml.update({"R3 Score": 0.999, "ml_probability": 0.001, "confidence": "HIGH"})
    allocation_a = allocate_candidates(profile(20000), [], [base])
    allocation_b = allocate_candidates(profile(20000), [], [with_ml])
    check(23, "ML fields cannot affect allocation", allocation_a.recommendations == allocation_b.recommendations and allocation_a.portfolio_summary == allocation_b.portfolio_summary)
    changed = subprocess.check_output(["git", "diff", "--name-only", "stage4a3-prospective-shadow-protocol-baseline", "--", "Stage 4A.3"], cwd=REPO, text=True).strip()
    check(24, "Stage 4A.3 protected files unchanged", changed == "", changed)

    strong = allocate_candidates(profile(20000), [], [source_candidate("STRONG BUY")]).recommendations[0]
    check(25, "STRONG BUY is actionable", strong["portfolio_action_status"] == "ACTIONABLE_BUY" and strong["recommended_quantity"] > 0)
    buy = allocate_candidates(profile(20000), [], [source_candidate("BUY")]).recommendations[0]
    check(26, "BUY remains actionable", buy["portfolio_action_status"] == "ACTIONABLE_BUY" and buy["recommended_quantity"] > 0)
    wait_no_setup = allocate_candidates(profile(20000), [], [source_candidate("WAIT - NO SETUP", nullable_levels=True)]).recommendations[0]
    check(27, "WAIT - NO SETUP with NaN levels does not crash", wait_no_setup["portfolio_action_status"] == "WAIT_SOURCE_SIGNAL" and wait_no_setup["entry_low"] is None)
    avoid = allocate_candidates(profile(20000), [], [source_candidate("AVOID", nullable_levels=True)]).recommendations[0]
    check(28, "AVOID with NaN levels does not crash", avoid["portfolio_action_status"] == "AVOID_SOURCE_SIGNAL" and avoid["stop"] is None)
    watch_extended = allocate_candidates(profile(20000), [], [source_candidate("WATCH - EXTENDED", nullable_levels=True)]).recommendations[0]
    check(29, "WATCH - EXTENDED with NaN levels does not crash", watch_extended["portfolio_action_status"] == "WATCH_SOURCE_SIGNAL" and watch_extended["target_2"] is None)
    non_buy_rows = [
        allocate_candidates(profile(20000), [], [source_candidate(signal, ticker=f"NB{i}.NS", nullable_levels=True)]).recommendations[0]
        for i, signal in enumerate(("WATCH", "WATCH - MARKET RISK", "WATCH - EXTENDED", "WAIT FOR BETTER ENTRY", "WAIT - NO SETUP", "AVOID"))
    ]
    check(30, "non-BUY rows allocate zero shares", all(row["recommended_quantity"] == 0 and row["deterministic_signal"] in {"WATCH", "WATCH - MARKET RISK", "WATCH - EXTENDED", "WAIT FOR BETTER ENTRY", "WAIT - NO SETUP", "AVOID"} for row in non_buy_rows))
    existing = allocate_candidates(profile(20000), [OpenPosition.create("AAA.NS", 1, 100, 100)], [candidate()]).recommendations[0]
    check(31, "existing ticker blocks new allocation", existing["portfolio_action_status"] == "BLOCKED_EXISTING_POSITION" and existing["recommended_quantity"] == 0)
    duplicate = allocate_candidates(profile(20000), [], [candidate("DUP.NS", signal_id="D1", deterministic_rank=1), candidate("DUP.NS", signal_id="D2", deterministic_rank=2)])
    check(32, "duplicate candidate ticker cannot be allocated twice", duplicate.recommendations[0]["recommended_quantity"] > 0 and duplicate.recommendations[1]["portfolio_action_status"] == "BLOCKED_DUPLICATE_TICKER" and duplicate.recommendations[1]["recommended_quantity"] == 0)
    duplicate_value = sum(row["recommended_quantity"] * (row["sizing_entry_price"] or 0) for row in duplicate.recommendations)
    check(33, "duplicate ticker cannot bypass 25 percent cap", duplicate_value <= 20000 * 0.25)
    check(34, "fractional OpenPosition quantity rejected", rejects_quantity(1.5) and rejects_quantity("1.5"))
    integral_float = OpenPosition.create("FLOAT.NS", 2.0, 100, 90)
    check(35, "integral float quantity accepted", integral_float.quantity == 2 and isinstance(integral_float.quantity, int))
    check(36, "bool quantity rejected", rejects_quantity(True))
    identity_base = allocate_candidates(profile(20000), [], [candidate()])
    identity_position = allocate_candidates(profile(20000), [OpenPosition.create("OTHER.NS", 1, 100, 90)], [candidate()])
    check(37, "recommendation ID changes when open-position state changes", identity_base.recommendations[0]["recommendation_id"] != identity_position.recommendations[0]["recommendation_id"])
    identity_reserved = allocate_candidates(profile(20000), [], [candidate()], reserved_capital_for_pending_entries_inr=100)
    check(38, "recommendation ID changes when reserved capital changes", identity_base.recommendations[0]["recommendation_id"] != identity_reserved.recommendations[0]["recommendation_id"])
    identity_repeat = allocate_candidates(profile(20000), [], [candidate()])
    check(39, "allocation_run_id deterministic for identical inputs", identity_base.allocation_run_id == identity_repeat.allocation_run_id)
    identity_capital = allocate_candidates(profile(21000), [], [candidate()])
    check(40, "allocation_run_id changes when capital ceiling changes", identity_base.allocation_run_id != identity_capital.allocation_run_id)
    committed = PortfolioSnapshot.create(10000, [OpenPosition.create("C.NS", 20, 200, 150)], 1500)
    check(41, "committed capital includes reserved pending capital", committed.committed_capital_inr == Decimal("5500") and committed.available_capital_for_new_positions_inr == Decimal("4500"))
    committed_over = allocate_candidates(profile(5000), [OpenPosition.create("C.NS", 20, 200, 150)], [candidate()], reserved_capital_for_pending_entries_inr=1500)
    check(42, "committed-capital overage blocks new buys", committed_over.portfolio_summary["portfolio_status"] == "OVER_COMMITTED_CAP" and committed_over.portfolio_summary["new_buys_allowed"] is False and committed_over.recommendations[0]["portfolio_action_status"] == "BLOCKED_COMMITTED_CAPITAL_OVERAGE")
    one_policy = allocate_candidates(profile(20000, HorizonPreference.ONE_MONTH), [], [candidate()]).recommendations[0]
    check(43, "ONE_MONTH maps to STATIC_T2_20D", one_policy["management_policy_id"] == "STATIC_T2_20D" and one_policy["management_policy_source"] == "FROZEN_STAGE2_2_2_STATIC_BASELINE")
    check(44, "ONE_MONTH uses 20-session limit", one_policy["horizon_session_limit"] == one_policy["management_policy_max_sessions"] == 20)
    three_policy = allocate_candidates(profile(20000, HorizonPreference.THREE_MONTHS), [], [candidate()]).recommendations[0]
    check(45, "THREE_MONTHS maps to D1_TRAIL_ONLY_63D", three_policy["management_policy_id"] == "D1_TRAIL_ONLY_63D" and three_policy["management_policy_source"] == "FROZEN_STAGE2B_1_DYNAMIC_BASELINE")
    check(46, "THREE_MONTHS uses 63-session limit", three_policy["horizon_session_limit"] == three_policy["management_policy_max_sessions"] == 63)
    six_policy = allocate_candidates(profile(20000, HorizonPreference.SIX_MONTHS), [], [candidate()]).recommendations[0]
    check(47, "SIX_MONTHS remains unsupported", six_policy["management_policy_id"] is None and six_policy["horizon_status"] == "UNSUPPORTED_NOT_VALIDATED" and six_policy["recommended_quantity"] == 0)
    fake_sessions = allocate_candidates(profile(20000, HorizonPreference.ONE_MONTH), [], [candidate(validated_holding_sessions=999)])
    check(48, "arbitrary validated_holding_sessions cannot change production horizon", fake_sessions.recommendations == allocate_candidates(profile(20000, HorizonPreference.ONE_MONTH), [], [candidate()]).recommendations)
    fake_source = allocate_candidates(profile(20000, HorizonPreference.ONE_MONTH), [], [candidate(holding_evidence_source="VALIDATED_DETERMINISTIC")])
    check(49, "arbitrary holding_evidence_source cannot change production horizon", fake_source.recommendations == allocate_candidates(profile(20000, HorizonPreference.ONE_MONTH), [], [candidate()]).recommendations)
    check(50, "Stage 4A.3 changed files equals zero", changed == "", changed)
    ml_base_candidates = [candidate("B.NS", deterministic_rank=2), candidate("A.NS", deterministic_rank=1)]
    ml_candidates = deepcopy(ml_base_candidates)
    for item in ml_candidates:
        item.update({"R3 Score": 0.91, "ml_probability": 0.77, "confidence": "HIGH", "unknown_ml_shadow": "ignored"})
    ml_base_allocation = allocate_candidates(profile(20000), [], ml_base_candidates)
    ml_shadow_allocation = allocate_candidates(profile(20000), [], ml_candidates)
    check(51, "ML metadata cannot affect ordering sizing status or IDs", ml_base_allocation == ml_shadow_allocation)

    results = ROOT / "results"
    results.mkdir(parents=True, exist_ok=True)
    ordered_rows = sorted(rows, key=lambda row: int(row["Test Number"]))
    with (results / "stage5d1_test_results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ordered_rows[0]))
        writer.writeheader()
        writer.writerows(ordered_rows)
    (results / "stage5d1_contract.json").write_text(json.dumps(contract_payload(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    counts = {status: sum(row["Status"] == status for row in rows) for status in ("PASS", "FAIL")}
    print(json.dumps(counts, sort_keys=True))
    return 0 if counts["FAIL"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
