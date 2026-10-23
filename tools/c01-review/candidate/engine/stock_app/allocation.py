from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .historical import HistoricalTechnicalPredictionAdapter, MarketBar
from .portfolio import PortfolioService

POLICY_VERSION = "LEG6_PORTFOLIO_ALLOCATION_POLICY_V3_TARGET_DIVERSIFIED"
DEFAULT_CORRELATION_WINDOW = 126
FALLBACK_CORRELATION_WINDOW = 63
MAX_POSITION_CAPITAL_FRACTION = 0.35
SMALL_CAPITAL_SINGLE_STOCK_MAX = 10000.0
DIVERSIFIED_CAPITAL_THRESHOLD = 100000.0
DIVERSIFIED_TARGET_HOLDINGS = 5
DIVERSIFIED_MAX_POSITION_CAPITAL_FRACTION = 0.20
TARGET_RETURN_EPSILON = 1e-12
MAX_SECTOR_EXPOSURE_FRACTION = 0.60
MIN_CASH_RESERVE_FRACTION = 0.0
MIN_SUPPORTED_HORIZON = 5
MAX_SUPPORTED_HORIZON = 126
SUPPORTED_HORIZONS = tuple(range(MIN_SUPPORTED_HORIZON, MAX_SUPPORTED_HORIZON + 1))
RESEARCH_ANCHOR_HORIZONS = (20, 63, 126)
EXECUTABLE_DECISIONS = ("MOMENTUM BUY", "RECOVERY BUY", "MOMENTUM + RECOVERY BUY")

REASON_LABELS = {
    "WHOLE_SHARE_AFFORDABLE": "Fits the whole-share budget and passed portfolio constraints.",
    "EXISTING_HOLDING_SEPARATED": "Already held — review the existing position instead of creating a duplicate buy.",
    "NON_EXECUTABLE_MODEL_STATUS": "Latest combined decision is not a buy candidate.",
    "PRICE_UNAVAILABLE": "Official reference price is unavailable.",
    "INSUFFICIENT_CASH_FOR_ONE_WHOLE_SHARE": "Not enough deployable cash for one whole share.",
    "SECTOR_CONCENTRATION_LIMIT": "Deferred to avoid exceeding the sector concentration limit.",
    "SINGLE_ELIGIBLE_FULL_CAPITAL": "Only one new model-executable stock is cash-affordable and capital is within the small-cap exception limit, so the normal concentration cap is relaxed for that stock.",
    "BELOW_DESIRED_RETURN": "Expected return is below the user-selected minimum desired return.",
    "TARGET_RETURN_UNAVAILABLE": "Expected return is unavailable, so the stock cannot be verified against the user-selected minimum desired return.",
}


@dataclass(frozen=True)
class AllocationRequest:
    deployable_capital: float
    horizon_sessions: int
    target_return: float | None = None


@dataclass(frozen=True)
class Holding:
    symbol: str
    quantity: int
    latest_price: float
    sector: str

    @property
    def market_value(self) -> float:
        return self.quantity * self.latest_price


@dataclass(frozen=True)
class AllocationInput:
    rank: int
    symbol: str
    latest_close: float | None
    opportunity_status: str
    confidence_label: str
    sector: str = "UNKNOWN"
    expected_return: float | None = None


@dataclass(frozen=True)
class AllocationRow:
    rank: int
    symbol: str
    action: str
    shares: int
    reference_price: float | None
    estimated_cost: float
    remaining_cash_after: float
    sector: str
    reason_code: str
    existing_holding: bool
    correlation_status: str
    correlation_window: int | None
    max_abs_correlation_to_holdings: float | None
    source_decision: str
    single_stock_exception_applied: bool = False


class OfficialHistoryService:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.adapter = HistoricalTechnicalPredictionAdapter(repo_root, db=None)  # type: ignore[arg-type]

    def load_bars(self, symbol: str) -> list[MarketBar]:
        stem = symbol.upper().replace(".NS", "")
        for root in self.adapter.cache_roots:
            for name in (f"{stem}.NS.csv", f"{stem}.csv"):
                path = root / name
                if path.exists():
                    return self.adapter._read_bars(path)
        return []

    def latest_close(self, symbol: str) -> tuple[float | None, str | None]:
        bars = self.load_bars(symbol)
        if not bars:
            return None, None
        return bars[-1].close, bars[-1].date


def normalize_symbol(symbol: str) -> str:
    return str(symbol or "").upper().replace(".NS", "").strip()


def load_sector_map(repo_root: Path) -> dict[str, dict[str, str]]:
    path = repo_root / "outputs" / "Leg5_Official_Source_Access_Recovery" / "NSE_COMPANY_INDUSTRY_CLASSIFICATION.csv"
    sectors: dict[str, dict[str, str]] = {}
    if not path.exists():
        return sectors
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            symbol = normalize_symbol(row.get("symbol", ""))
            if symbol:
                sectors[symbol] = {
                    "sector": row.get("sector") or "UNKNOWN",
                    "industry": row.get("industry") or "UNKNOWN",
                    "macro_economic_sector": row.get("macro_economic_sector") or "UNKNOWN",
                    "classification_status": row.get("classification_status") or "UNKNOWN",
                    "source_endpoint": row.get("source_endpoint") or "",
                    "source_sha256": row.get("source_sha256") or "",
                }
    return sectors


def policy_payload() -> dict[str, Any]:
    payload = {
        "policy_version": POLICY_VERSION,
        "whole_shares_only": True,
        "no_overspend": True,
        "no_leverage": True,
        "no_broker_execution": True,
        "score_to_position_size_allowed": False,
        "position_size_basis": "equal_capital_budget_with_whole_share_floor_and_price_affordability",
        "max_position_capital_fraction": MAX_POSITION_CAPITAL_FRACTION,
        "single_eligible_stock_exception": True,
        "single_eligible_stock_max_capital_fraction": 1.0,
        "single_eligible_stock_max_deployable_capital": SMALL_CAPITAL_SINGLE_STOCK_MAX,
        "single_eligible_stock_rule": "The full-capital exception is allowed only when deployable capital is at or below the small-cap limit and exactly one target-qualified model-executable stock is cash-affordable.",
        "desired_return_policy": "MINIMUM_THRESHOLD_NOT_CEILING",
        "diversified_capital_threshold": DIVERSIFIED_CAPITAL_THRESHOLD,
        "diversified_target_holdings": DIVERSIFIED_TARGET_HOLDINGS,
        "diversified_max_position_capital_fraction": DIVERSIFIED_MAX_POSITION_CAPITAL_FRACTION,
        "max_sector_exposure_fraction": MAX_SECTOR_EXPOSURE_FRACTION,
        "min_cash_reserve_fraction": MIN_CASH_RESERVE_FRACTION,
        "correlation_source": "official_aligned_daily_close_returns",
        "correlation_default_sessions": DEFAULT_CORRELATION_WINDOW,
        "correlation_fallback_sessions": FALLBACK_CORRELATION_WINDOW,
        "supported_horizon_range": [MIN_SUPPORTED_HORIZON, MAX_SUPPORTED_HORIZON],
        "research_anchor_horizons": list(RESEARCH_ANCHOR_HORIZONS),
        "existing_holdings_policy": "separate_from_new_buy_recommendations",
    }
    payload["policy_hash"] = stable_hash({k: v for k, v in payload.items() if k != "policy_hash"})
    return payload


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def daily_returns(bars: list[MarketBar], window: int) -> dict[str, float]:
    selected = bars[-(window + 1) :]
    out: dict[str, float] = {}
    for prev, cur in zip(selected, selected[1:]):
        if prev.close > 0 and cur.close > 0:
            out[cur.date] = cur.close / prev.close - 1.0
    return out


def aligned_correlation(a: list[MarketBar], b: list[MarketBar], requested_window: int = DEFAULT_CORRELATION_WINDOW) -> tuple[float | None, str, int | None]:
    for window in (requested_window, FALLBACK_CORRELATION_WINDOW):
        ra = daily_returns(a, window)
        rb = daily_returns(b, window)
        dates = sorted(set(ra) & set(rb))
        if len(dates) >= min(window, FALLBACK_CORRELATION_WINDOW):
            xs = [ra[d] for d in dates[-window:]]
            ys = [rb[d] for d in dates[-window:]]
            if len(xs) < 2 or statistics.pstdev(xs) == 0 or statistics.pstdev(ys) == 0:
                return None, "CORRELATION_UNAVAILABLE_CONSTANT_RETURNS", window
            return statistics.correlation(xs, ys), "OFFICIAL_ALIGNED_RETURNS", window
    return None, "CORRELATION_UNAVAILABLE_INSUFFICIENT_OVERLAP", None


def is_executable_decision(decision: str | None) -> bool:
    """Single recommendation-authority rule shared by Opportunities, Capital Plan and Live Pilot."""
    text = str(decision or "").upper()
    if "AVOID" in text or "INSUFFICIENT" in text or "NO STRONG EDGE" in text or "WATCH" in text:
        return False
    return text in EXECUTABLE_DECISIONS


def meets_target_return(candidate: AllocationInput, target_return: float | None) -> bool:
    """Desired return is a minimum threshold, never a ceiling."""
    if target_return is None:
        return True
    if candidate.expected_return is None or not math.isfinite(candidate.expected_return):
        return False
    return candidate.expected_return + TARGET_RETURN_EPSILON >= target_return


class PortfolioAllocator:
    def __init__(self, repo_root: Path, portfolio: PortfolioService | None = None):
        self.repo_root = repo_root
        self.portfolio = portfolio
        self.history = OfficialHistoryService(repo_root)
        self.sectors = load_sector_map(repo_root)
        self.policy = policy_payload()

    def candidates_from_latest_run(self, latest_run: dict[str, Any] | None) -> list[AllocationInput]:
        if not latest_run:
            return []
        rows = latest_run.get("candidates", [])
        candidates: list[AllocationInput] = []
        seen = set()
        for row in rows:
            symbol = normalize_symbol(row.get("symbol", ""))
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            sector = self.sectors.get(symbol, {}).get("sector", "UNKNOWN")
            raw = row.get("raw") if isinstance(row.get("raw"), dict) else None
            if raw is None and row.get("raw_json"):
                try:
                    raw = json.loads(row["raw_json"])
                except (TypeError, ValueError, json.JSONDecodeError):
                    raw = {}
            combined = (raw or {}).get("combined_evidence") or {}
            # Capital Plan must consume the same effective Leg 5 combined decision
            # shown in Opportunities. Older persisted rows can still carry the
            # technical-only status in the top-level column while raw_json contains
            # the authoritative combined decision.
            effective_decision = str((row.get("live_decision") or {}).get("final_action") or row.get("opportunity_status") or "")
            effective_confidence = str((row.get("live_decision") or {}).get("confidence") or row.get("confidence_label") or "")
            candidates.append(
                AllocationInput(
                    rank=int(row.get("rank") or 0),
                    symbol=symbol,
                    latest_close=_float_or_none(row.get("latest_close")),
                    opportunity_status=effective_decision,
                    confidence_label=effective_confidence,
                    sector=sector,
                    expected_return=_float_or_none(row.get("expected_return")),
                )
            )
        return sorted(candidates, key=lambda c: (c.rank, c.symbol))

    def holdings_from_portfolio(self) -> list[Holding]:
        if not self.portfolio:
            return []
        holdings = []
        for row in self.portfolio.list_positions():
            if str(row.get("position_status") or "OPEN") != "OPEN":
                continue
            symbol = normalize_symbol(row.get("symbol", ""))
            qty = int(float(row.get("quantity") or 0))
            price, _ = self.history.latest_close(symbol)
            price = price if price is not None else _float_or_none(row.get("buy_price")) or 0.0
            holdings.append(Holding(symbol, qty, price, self.sectors.get(symbol, {}).get("sector", "UNKNOWN")))
        return holdings

    def execution_preview(self, request: AllocationRequest, candidates: list[AllocationInput], holdings: list[Holding] | None = None) -> dict[str, dict[str, Any]]:
        # Exact same allocation policy used by Capital Plan, exposed to Opportunities.
        result = self.allocate(request, candidates, holdings)
        preview: dict[str, dict[str, Any]] = {}
        for row in result.get("rows", []):
            price = _float_or_none(row.get("reference_price"))
            cash_affordable_qty = 0 if price is None or price <= 0 else int(request.deployable_capital // price)
            preview[normalize_symbol(row.get("symbol", ""))] = {
                "cash_affordable": cash_affordable_qty > 0,
                "cash_affordable_qty": cash_affordable_qty,
                "executable": row.get("action") == "BUY",
                "executable_qty": int(row.get("shares") or 0),
                "execution_action": row.get("action"),
                "execution_reason_code": row.get("reason_code"),
                "execution_reason": explain_reason_code(str(row.get("reason_code") or "")),
                "single_stock_exception_applied": bool(row.get("single_stock_exception_applied")),
            }
        return preview

    def allocate(self, request: AllocationRequest, candidates: list[AllocationInput], holdings: list[Holding] | None = None) -> dict[str, Any]:
        if request.deployable_capital <= 0 or not math.isfinite(request.deployable_capital):
            raise ValueError("Deployable capital must be a positive finite amount.")
        if request.horizon_sessions < MIN_SUPPORTED_HORIZON or request.horizon_sessions > MAX_SUPPORTED_HORIZON:
            raise ValueError(f"Holding period must be between {MIN_SUPPORTED_HORIZON} and {MAX_SUPPORTED_HORIZON} trading sessions.")
        holdings = holdings if holdings is not None else self.holdings_from_portfolio()
        held_symbols = {h.symbol for h in holdings if h.quantity > 0}
        current_exposure = self._sector_exposure(holdings, [])
        cash = request.deployable_capital
        rows: list[AllocationRow] = []
        buys: list[AllocationRow] = []

        # V3: desired return is a minimum threshold, not a ceiling.
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
            price = candidate.latest_close
            if price is None:
                price, _ = self.history.latest_close(candidate.symbol)
            correlation_value, correlation_status, correlation_window = self._holding_correlation(candidate.symbol, holdings)
            common = {
                "rank": candidate.rank,
                "symbol": candidate.symbol,
                "reference_price": price,
                "sector": candidate.sector or self.sectors.get(candidate.symbol, {}).get("sector", "UNKNOWN"),
                "correlation_status": correlation_status,
                "correlation_window": correlation_window,
                "max_abs_correlation_to_holdings": correlation_value,
                "source_decision": candidate.opportunity_status,
                "single_stock_exception_applied": False,
            }
            if candidate.symbol in held_symbols:
                rows.append(AllocationRow(action="ALREADY_HELD_REVIEW_ONLY", shares=0, estimated_cost=0.0, remaining_cash_after=cash, reason_code="EXISTING_HOLDING_SEPARATED", existing_holding=True, **common))
                continue
            if not self._is_executable(candidate):
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
                rows.append(AllocationRow(action="EXCLUDED", shares=0, estimated_cost=0.0, remaining_cash_after=cash, reason_code="PRICE_UNAVAILABLE", existing_holding=False, **common))
                continue
            single_stock_exception = candidate.symbol == single_eligible_symbol
            position_budget = cash if single_stock_exception else min(cash, request.deployable_capital * effective_position_cap_fraction)
            qty = int(position_budget // price)
            if qty < 1:
                rows.append(AllocationRow(action="UNAFFORDABLE", shares=0, estimated_cost=0.0, remaining_cash_after=cash, reason_code="INSUFFICIENT_CASH_FOR_ONE_WHOLE_SHARE", existing_holding=False, **common))
                continue
            cost = round(qty * price, 2)
            if cost > cash + 0.000001:
                qty = int(cash // price)
                cost = round(qty * price, 2)
            if qty < 1:
                rows.append(AllocationRow(action="UNAFFORDABLE", shares=0, estimated_cost=0.0, remaining_cash_after=cash, reason_code="INSUFFICIENT_CASH_FOR_ONE_WHOLE_SHARE", existing_holding=False, **common))
                continue
            buy_common = dict(common)
            buy_common["single_stock_exception_applied"] = single_stock_exception
            reason_code = "SINGLE_ELIGIBLE_FULL_CAPITAL" if single_stock_exception else "WHOLE_SHARE_AFFORDABLE"
            proposed_buys = buys + [AllocationRow(action="BUY", shares=qty, estimated_cost=cost, remaining_cash_after=round(cash - cost, 2), reason_code=reason_code, existing_holding=False, **buy_common)]
            exposure = self._sector_exposure(holdings, proposed_buys)
            if exposure.get(common["sector"], {}).get("post_allocation_fraction", 0.0) > MAX_SECTOR_EXPOSURE_FRACTION and len({b.sector for b in proposed_buys}) > 1:
                rows.append(AllocationRow(action="DEFERRED", shares=0, estimated_cost=0.0, remaining_cash_after=cash, reason_code="SECTOR_CONCENTRATION_LIMIT", existing_holding=False, **common))
                continue
            buy = proposed_buys[-1]
            buys.append(buy)
            rows.append(buy)
            cash = round(cash - cost, 2)

        spent = round(sum(r.estimated_cost for r in buys), 2)
        output = {
            "policy_version": POLICY_VERSION,
            "policy_hash": self.policy["policy_hash"],
            "generated_at": datetime.now(UTC).isoformat(),
            "request": asdict(request),
            "rows": [asdict(r) for r in rows],
            "new_buys": [asdict(r) for r in buys],
            "excluded": [asdict(r) for r in rows if r.action != "BUY"],
            "capital_summary": {
                "deployable_capital": request.deployable_capital,
                "normal_position_cap_fraction": MAX_POSITION_CAPITAL_FRACTION,
                "effective_position_cap_fraction": effective_position_cap_fraction,
                "desired_return_is_minimum_threshold": True,
                "target_return_threshold": request.target_return,
                "target_qualified_affordable_count": len(viable_new_symbols),
                "diversification_target_holdings": diversification_target,
                "diversification_target_met": (len(buys) >= diversification_target) if diversification_target else None,
                "diversification_shortfall": max(0, diversification_target - len(buys)) if diversification_target else 0,
                "single_eligible_stock_exception_available": request.deployable_capital <= SMALL_CAPITAL_SINGLE_STOCK_MAX,
                "single_eligible_symbol": single_eligible_symbol,
                "estimated_spend": spent,
                "remaining_cash": round(request.deployable_capital - spent, 2),
                "overspend": spent > request.deployable_capital,
                "whole_share_only": all(float(r.shares).is_integer() for r in rows),
                "leverage_used": False,
                "broker_order_generated": False,
            },
            "sector_exposure": self._sector_exposure(holdings, buys),
            "audit_hash": stable_hash({"request": asdict(request), "rows": [asdict(r) for r in rows], "policy": self.policy}),
        }
        return output

    @staticmethod
    def _is_executable(candidate: AllocationInput) -> bool:
        return is_executable_decision(candidate.opportunity_status)

    def _holding_correlation(self, symbol: str, holdings: list[Holding]) -> tuple[float | None, str, int | None]:
        candidate_bars = self.history.load_bars(symbol)
        values: list[tuple[float, int]] = []
        missing = False
        for holding in holdings:
            bars = self.history.load_bars(holding.symbol)
            corr, status, window = aligned_correlation(candidate_bars, bars, DEFAULT_CORRELATION_WINDOW)
            if corr is None:
                missing = True
                continue
            values.append((abs(corr), window or DEFAULT_CORRELATION_WINDOW))
        if values:
            value, window = max(values, key=lambda x: x[0])
            return value, "OFFICIAL_ALIGNED_RETURNS", window
        if holdings and missing:
            return None, "CORRELATION_UNAVAILABLE_NOT_ZERO_FILLED", None
        return None, "NO_EXISTING_HOLDINGS_FOR_CORRELATION", None

    @staticmethod
    def _sector_exposure(holdings: list[Holding], buys: list[AllocationRow]) -> dict[str, dict[str, float]]:
        totals: dict[str, dict[str, float]] = {}
        for holding in holdings:
            sector = holding.sector or "UNKNOWN"
            totals.setdefault(sector, {"current_value": 0.0, "new_allocation": 0.0, "post_value": 0.0, "post_allocation_fraction": 0.0})
            totals[sector]["current_value"] += holding.market_value
        for buy in buys:
            sector = buy.sector or "UNKNOWN"
            totals.setdefault(sector, {"current_value": 0.0, "new_allocation": 0.0, "post_value": 0.0, "post_allocation_fraction": 0.0})
            totals[sector]["new_allocation"] += buy.estimated_cost
        grand = sum(v["current_value"] + v["new_allocation"] for v in totals.values())
        for value in totals.values():
            value["post_value"] = round(value["current_value"] + value["new_allocation"], 2)
            value["current_value"] = round(value["current_value"], 2)
            value["new_allocation"] = round(value["new_allocation"], 2)
            value["post_allocation_fraction"] = 0.0 if grand <= 0 else round(value["post_value"] / grand, 6)
        return dict(sorted(totals.items()))


def explain_reason_code(reason_code: str) -> str:
    return REASON_LABELS.get(reason_code, str(reason_code or "").replace("_", " ").title())


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
