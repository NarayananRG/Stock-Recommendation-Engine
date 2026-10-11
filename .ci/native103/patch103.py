from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])

def repl(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"{label} contract missing")
    return text.replace(old, new, 1)

p = root / "stock_app" / "allocation.py"
s = p.read_text(encoding="utf-8")

s = repl(s,
    'POLICY_VERSION = "LEG6_PORTFOLIO_ALLOCATION_POLICY_V2_SMALL_CAP_SINGLE_STOCK"',
    'POLICY_VERSION = "LEG6_PORTFOLIO_ALLOCATION_POLICY_V3_TARGET_DIVERSIFIED"',
    "V3 policy identity")

s = repl(s,
    'MAX_POSITION_CAPITAL_FRACTION = 0.35\n',
    '''MAX_POSITION_CAPITAL_FRACTION = 0.35
SMALL_CAPITAL_SINGLE_STOCK_MAX = 10000.0
DIVERSIFIED_CAPITAL_THRESHOLD = 100000.0
DIVERSIFIED_TARGET_HOLDINGS = 5
DIVERSIFIED_MAX_POSITION_CAPITAL_FRACTION = 0.20
TARGET_RETURN_EPSILON = 1e-12
''',
    "V3 constants")

s = repl(s,
    '''    "SINGLE_ELIGIBLE_FULL_CAPITAL": "Only one new model-executable stock is cash-affordable, so the normal concentration cap is relaxed for that stock; whole shares, available-cash and no-leverage rules still apply.",
}''',
    '''    "SINGLE_ELIGIBLE_FULL_CAPITAL": "Only one new model-executable stock is cash-affordable and capital is within the small-cap exception limit, so the normal concentration cap is relaxed for that stock.",
    "BELOW_DESIRED_RETURN": "Expected return is below the user-selected minimum desired return.",
    "TARGET_RETURN_UNAVAILABLE": "Expected return is unavailable, so the stock cannot be verified against the user-selected minimum desired return.",
}''',
    "V3 reason labels")

s = repl(s,
    '''class AllocationInput:
    rank: int
    symbol: str
    latest_close: float | None
    opportunity_status: str
    confidence_label: str
    sector: str = "UNKNOWN"
''',
    '''class AllocationInput:
    rank: int
    symbol: str
    latest_close: float | None
    opportunity_status: str
    confidence_label: str
    sector: str = "UNKNOWN"
    expected_return: float | None = None
''',
    "AllocationInput expected return")

s = repl(s,
    '''        "single_eligible_stock_exception": True,
        "single_eligible_stock_max_capital_fraction": 1.0,
        "single_eligible_stock_rule": "If exactly one new model-executable candidate is cash-affordable, the normal per-stock concentration cap is relaxed up to available deployable cash; whole shares and no leverage still apply.",
        "max_sector_exposure_fraction": MAX_SECTOR_EXPOSURE_FRACTION,''',
    '''        "single_eligible_stock_exception": True,
        "single_eligible_stock_max_capital_fraction": 1.0,
        "single_eligible_stock_max_deployable_capital": SMALL_CAPITAL_SINGLE_STOCK_MAX,
        "single_eligible_stock_rule": "The full-capital exception is allowed only when deployable capital is at or below the small-cap limit and exactly one target-qualified model-executable stock is cash-affordable.",
        "desired_return_policy": "MINIMUM_THRESHOLD_NOT_CEILING",
        "diversified_capital_threshold": DIVERSIFIED_CAPITAL_THRESHOLD,
        "diversified_target_holdings": DIVERSIFIED_TARGET_HOLDINGS,
        "diversified_max_position_capital_fraction": DIVERSIFIED_MAX_POSITION_CAPITAL_FRACTION,
        "max_sector_exposure_fraction": MAX_SECTOR_EXPOSURE_FRACTION,''',
    "V3 policy metadata")

s = repl(s,
    '''                    opportunity_status=effective_decision,
                    confidence_label=effective_confidence,
                    sector=sector,
''',
    '''                    opportunity_status=effective_decision,
                    confidence_label=effective_confidence,
                    sector=sector,
                    expected_return=_float_or_none(row.get("expected_return")),
''',
    "candidate expected return")

s = repl(s,
    '''def is_executable_decision(decision: str | None) -> bool:
    """Single recommendation-authority rule shared by Opportunities, Capital Plan and Live Pilot."""
    text = str(decision or "").upper()
    if "AVOID" in text or "INSUFFICIENT" in text or "NO STRONG EDGE" in text or "WATCH" in text:
        return False
    return any(token in text for token in EXECUTABLE_DECISIONS)


class PortfolioAllocator:
''',
    '''def is_executable_decision(decision: str | None) -> bool:
    """Single recommendation-authority rule shared by Opportunities, Capital Plan and Live Pilot."""
    text = str(decision or "").upper()
    if "AVOID" in text or "INSUFFICIENT" in text or "NO STRONG EDGE" in text or "WATCH" in text:
        return False
    return any(token in text for token in EXECUTABLE_DECISIONS)


def meets_target_return(candidate: AllocationInput, target_return: float | None) -> bool:
    """Desired return is a minimum threshold, never a ceiling."""
    if target_return is None:
        return True
    if candidate.expected_return is None or not math.isfinite(candidate.expected_return):
        return False
    return candidate.expected_return + TARGET_RETURN_EPSILON >= target_return


class PortfolioAllocator:
''',
    "target helper")

s = repl(s,
    '''        # If exactly one NEW model-executable candidate is cash-affordable,
        # relax the normal 35% position cap for that stock only.
        viable_new_symbols: list[str] = []
        for candidate in sorted(candidates, key=lambda c: (c.rank, c.symbol)):
            if candidate.symbol in held_symbols or not self._is_executable(candidate):
                continue
            price = candidate.latest_close
            if price is None:
                price, _ = self.history.latest_close(candidate.symbol)
            if price is not None and price > 0 and int(request.deployable_capital // price) >= 1:
                viable_new_symbols.append(candidate.symbol)
        single_eligible_symbol = viable_new_symbols[0] if len(viable_new_symbols) == 1 else None

        for candidate in sorted(candidates, key=lambda c: (c.rank, c.symbol)):
''',
    '''        # V3: desired return is a minimum threshold, not a ceiling.
        # For ₹1L+ plans target five holdings and cap each selected stock at 20%.
        diversification_target = DIVERSIFIED_TARGET_HOLDINGS if request.deployable_capital >= DIVERSIFIED_CAPITAL_THRESHOLD else None
        effective_position_cap_fraction = (
            min(MAX_POSITION_CAPITAL_FRACTION, DIVERSIFIED_MAX_POSITION_CAPITAL_FRACTION)
            if diversification_target
            else MAX_POSITION_CAPITAL_FRACTION
        )

        viable_new_symbols: list[str] = []
        for candidate in sorted(candidates, key=lambda c: (c.rank, c.symbol)):
            if candidate.symbol in held_symbols or not self._is_executable(candidate):
                continue
            if not meets_target_return(candidate, request.target_return):
                continue
            price = candidate.latest_close
            if price is None:
                price, _ = self.history.latest_close(candidate.symbol)
            eligibility_budget = (
                request.deployable_capital
                if request.deployable_capital <= SMALL_CAPITAL_SINGLE_STOCK_MAX
                else request.deployable_capital * effective_position_cap_fraction
            )
            if price is not None and price > 0 and int(eligibility_budget // price) >= 1:
                viable_new_symbols.append(candidate.symbol)

        single_eligible_symbol = (
            viable_new_symbols[0]
            if len(viable_new_symbols) == 1 and request.deployable_capital <= SMALL_CAPITAL_SINGLE_STOCK_MAX
            else None
        )

        for candidate in sorted(candidates, key=lambda c: (c.rank, c.symbol)):
''',
    "V3 viable pool")

s = repl(s,
    '''            if not self._is_executable(candidate):
                rows.append(AllocationRow(action="EXCLUDED", shares=0, estimated_cost=0.0, remaining_cash_after=cash, reason_code="NON_EXECUTABLE_MODEL_STATUS", existing_holding=False, **common))
                continue
            if price is None or price <= 0:
''',
    '''            if not self._is_executable(candidate):
                rows.append(AllocationRow(action="EXCLUDED", shares=0, estimated_cost=0.0, remaining_cash_after=cash, reason_code="NON_EXECUTABLE_MODEL_STATUS", existing_holding=False, **common))
                continue
            if request.target_return is not None:
                if candidate.expected_return is None or not math.isfinite(candidate.expected_return):
                    rows.append(AllocationRow(action="EXCLUDED", shares=0, estimated_cost=0.0, remaining_cash_after=cash, reason_code="TARGET_RETURN_UNAVAILABLE", existing_holding=False, **common))
                    continue
                if candidate.expected_return + TARGET_RETURN_EPSILON < request.target_return:
                    rows.append(AllocationRow(action="EXCLUDED", shares=0, estimated_cost=0.0, remaining_cash_after=cash, reason_code="BELOW_DESIRED_RETURN", existing_holding=False, **common))
                    continue
            if price is None or price <= 0:
''',
    "V3 target gate")

s = repl(s,
    '''            single_stock_exception = candidate.symbol == single_eligible_symbol
            position_budget = cash if single_stock_exception else min(cash, request.deployable_capital * MAX_POSITION_CAPITAL_FRACTION)
            qty = int(position_budget // price)
''',
    '''            single_stock_exception = candidate.symbol == single_eligible_symbol
            position_budget = cash if single_stock_exception else min(cash, request.deployable_capital * effective_position_cap_fraction)
            qty = int(position_budget // price)
''',
    "V3 dynamic cap")

s = repl(s,
    '''                "normal_position_cap_fraction": MAX_POSITION_CAPITAL_FRACTION,
                "single_eligible_stock_exception_available": True,
                "single_eligible_symbol": single_eligible_symbol,
''',
    '''                "normal_position_cap_fraction": MAX_POSITION_CAPITAL_FRACTION,
                "effective_position_cap_fraction": effective_position_cap_fraction,
                "desired_return_is_minimum_threshold": True,
                "target_return_threshold": request.target_return,
                "target_qualified_affordable_count": len(viable_new_symbols),
                "diversification_target_holdings": diversification_target,
                "diversification_target_met": (len(buys) >= diversification_target) if diversification_target else None,
                "diversification_shortfall": max(0, diversification_target - len(buys)) if diversification_target else 0,
                "single_eligible_stock_exception_available": request.deployable_capital <= SMALL_CAPITAL_SINGLE_STOCK_MAX,
                "single_eligible_symbol": single_eligible_symbol,
''',
    "V3 capital summary")

p.write_text(s, encoding="utf-8")

p = root / "modern_ui" / "api.py"
s = p.read_text(encoding="utf-8")
s = repl(s,
    'APP_VERSION = "0.9.12-phase3c-universe-visibility"',
    'APP_VERSION = "0.9.13-capital-plan-v3"',
    "0.9.13 app version")

s = repl(s,
    '''                summary["unused_cash_explanation"] = (
                    "Only one new model-executable stock was cash-affordable, so Phase 2 relaxed the normal 35% concentration cap for " + str(row.get("symbol")) + ". "
                    + "The plan proposes " + str(int(row.get("shares") or 0)) + " whole share(s) without leverage; remaining cash is the whole-share residual."
                )
''',
    '''                summary["unused_cash_explanation"] = (
                    "A small-capital exception was used because only one target-qualified model-executable stock was affordable within the small-cap threshold. "
                    + "The plan proposes " + str(int(row.get("shares") or 0)) + " whole share(s) of " + str(row.get("symbol")) + " without leverage."
                )
''',
    "single-stock explanation")

s = repl(s,
    '''                max_pos = float(getattr(self.allocator, "policy", {}).get("max_position_capital_fraction", 0.35) or 0.35)
                summary["unused_cash_explanation"] = (
                    f"Cash is intentionally left unallocated. With multiple executable stocks, each new stock remains capped at {max_pos*100:.0f}% of deployable capital; "
                    "whole-share and sector constraints can leave a residual cash balance."
                )
''',
    '''                cap = float((result.get("capital_summary") or {}).get("effective_position_cap_fraction") or getattr(self.allocator, "policy", {}).get("max_position_capital_fraction", 0.35) or 0.35)
                target_n = (result.get("capital_summary") or {}).get("diversification_target_holdings")
                target_note = (" The allocator targets at least " + str(target_n) + " holdings when enough target-qualified executable stocks exist.") if target_n else ""
                summary["unused_cash_explanation"] = (
                    f"Cash is intentionally left unallocated. Each selected stock is capped at {cap*100:.0f}% of deployable capital."
                    + target_note
                    + " Stocks below the desired-return threshold are excluded rather than added merely to deploy cash."
                )
''',
    "diversified explanation")

p.write_text(s, encoding="utf-8")

policy = root / "phase3" / "capital_plan_v3_policy.json"
policy.parent.mkdir(parents=True, exist_ok=True)
policy.write_text("""{
  "schema": "SRE_CAPITAL_PLAN_V3_POLICY",
  "version": "0.9.13-capital-plan-v3",
  "desired_return_semantics": "MINIMUM_THRESHOLD_NOT_CEILING",
  "large_capital_threshold": 100000,
  "large_capital_target_holdings": 5,
  "large_capital_max_position_fraction": 0.20,
  "small_capital_single_stock_exception_max_capital": 10000,
  "rule": "Never add below-target stocks merely to fill a basket. If fewer than five qualifying executable stocks exist, return fewer and retain cash.",
  "recommendation_model_authority_changed": false
}
""", encoding="utf-8")

assert "LEG6_PORTFOLIO_ALLOCATION_POLICY_V3_TARGET_DIVERSIFIED" in (root/"stock_app"/"allocation.py").read_text(encoding="utf-8")
assert "desired_return_is_minimum_threshold" in (root/"stock_app"/"allocation.py").read_text(encoding="utf-8")
assert 'APP_VERSION = "0.9.13-capital-plan-v3"' in (root/"modern_ui"/"api.py").read_text(encoding="utf-8")
print("0.9.13 Capital Plan V3 patch applied")
