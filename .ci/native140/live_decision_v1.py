"""Deterministic thesis router. Scores and desired return are never authority.

Evidence thresholds are versioned policy, not return predictions. Unavailable
evidence is distinct from negative evidence. No network or execution side effects.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any

AUTHORITY = "LIVE_DECISION_V1"
MODEL = "0.14.0-live-dual-strategy-v1"
BUY_ACTIONS = ("MOMENTUM BUY", "RECOVERY BUY", "MOMENTUM + RECOVERY BUY")


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def interpret(f: dict[str, Any]) -> dict[str, Any]:
    growth = f.get("growth") or {}
    values = [number(growth.get(k)) for k in
              ("revenue_yoy_symmetric_pct", "pat_yoy_symmetric_pct", "eps_yoy_symmetric_pct")]
    complete = all(v is not None for v in values)
    worsening = sum(v is not None and v <= -20 for v in values)
    weakening = sum(v is not None and v < -5 for v in values)
    earnings = ("UNAVAILABLE" if not complete else "DETERIORATING" if worsening >= 2
                else "WEAKENING" if weakening >= 2 else "MIXED" if weakening
                else "IMPROVING" if all(v >= 5 for v in values) else "STABLE")
    financial = f.get("sector_profile") == "FINANCIAL_DOMAIN_CONSERVATIVE"
    cash = f.get("cash_flow") or {}
    ocf = number(cash.get("latest_operating_cash_flow"))
    ocf_growth = number(cash.get("ocf_yoy_symmetric_pct"))
    cash_state = ("UNAVAILABLE" if financial or ocf is None else "DANGEROUS" if ocf < 0
                  else "WEAK" if ocf == 0 or (ocf_growth is not None and ocf_growth < -30)
                  else "SUPPORTIVE" if ocf_growth is not None and ocf_growth >= -5 else "ADEQUATE")
    debt = number((f.get("balance_sheet") or {}).get("debt_equity_ratio"))
    finance = number(((f.get("score_components") or {}).get("finance_cost") or {}).get("evidence"))
    balance = ("UNAVAILABLE" if financial or debt is None else "STRESSED" if debt > 2.5
               else "CAUTION" if debt > 1.5 or (finance is not None and finance > 30)
               else "HEALTHY" if debt <= 1 else "ACCEPTABLE")
    event = f.get("risk_event") or {}
    event_state = ("UNAVAILABLE" if not event.get("available") else "DETERIORATING"
                   if event.get("strong_deterioration_transition") or event.get("event_profile") == "PURE_DETERIORATION"
                   else "IMPROVING" if event.get("event_profile") == "PURE_IMPROVEMENT"
                   else "MIXED" if event.get("event_profile") == "MIXED_DIRECTIONAL" else "STABLE")
    margin = number((f.get("profitability") or {}).get("pat_margin_pct"))
    damaged = earnings == "DETERIORATING" or event.get("strong_deterioration_transition") is True
    damaged = damaged or (cash_state == "DANGEROUS" and (weakening >= 1 or balance == "STRESSED"))
    health = ("DETERIORATING" if damaged else "UNAVAILABLE" if not complete or margin is None
              else "WEAK" if margin <= 0 or earnings == "WEAKENING" else "MIXED"
              if earnings == "MIXED" or event_state in ("MIXED", "DETERIORATING") or balance in ("CAUTION", "STRESSED")
              else "STRONG" if earnings == "IMPROVING" and cash_state == "SUPPORTIVE" else "HEALTHY")
    # A P/E level alone cannot establish attractiveness across different sectors.
    # Relative valuation needs an explicitly supported PIT comparison.
    valuation = f.get("valuation") or {}
    pe = number(valuation.get("implied_pe_from_ttm_eps"))
    reference = number(valuation.get("pit_historical_pe_reference")) if valuation.get("pit_comparison_available") is True else None
    valuation_state = "UNAVAILABLE"
    if pe is not None and pe > 0 and reference is not None and reference > 0:
        ratio = pe / reference
        valuation_state = "ATTRACTIVE" if ratio <= .8 else "REASONABLE" if ratio <= 1 else "FULL" if ratio <= 1.2 else "EXPENSIVE"
    quality = "STALE" if f.get("filing_freshness") == "STALE" else "AVAILABLE" if f.get("available") and f.get("point_in_time_safe") else "UNAVAILABLE"
    return dict(business_health=health, earnings_direction=earnings, cash_flow_state=cash_state,
                balance_sheet_state=balance, valuation_state=valuation_state,
                fundamental_event_state=event_state, structural_deterioration=bool(damaged),
                fundamental_data_quality=quality, financial_domain=financial)


def route(symbol: str, market_session: str, technical: dict, fundamental: dict,
          *, price_context: dict, official_current: bool, legacy: dict | None = None) -> dict:
    s = interpret(fundamental)
    reasons = []
    trend = technical.get("trend") or {}
    momentum = technical.get("momentum") or {}
    rs = number((technical.get("relative_strength") or {}).get("rs20_vs_nifty"))
    flow = number((technical.get("volume_flow") or {}).get("cmf20"))
    slope = number(trend.get("ema50_slope_5d_pct"))
    close = number(trend.get("close"))
    ema50 = number(trend.get("ema50"))
    roc = number(momentum.get("roc20_pct"))
    macd = number(momentum.get("macd_hist"))
    atr = number((technical.get("volatility") or {}).get("atr_pct"))
    support = number(price_context.get("prior_support"))
    drawdown = number(price_context.get("drawdown_from_126_high_pct"))
    # Evidence of a dislocation needs a usable historical price context.
    depressed = drawdown is not None and drawdown <= -15
    breakdown = (close is not None and support is not None and close < support * .97
                 and roc is not None and roc < -10)
    strong = (technical.get("status") == "READY" and None not in (close, ema50, slope, roc, rs, flow, macd)
              and close > ema50 and slope > 0 and roc > 0 and rs > 0 and flow > 0 and macd > 0
              and (technical.get("multi_timeframe") or {}).get("weekly_trend_confirmed") is True)
    stabilising = not breakdown and roc is not None and roc >= -3 and flow is not None and flow >= 0
    tech_state = "BREAKDOWN" if breakdown else "STRONG" if strong else "STABILISING" if stabilising else "WEAK"
    s.update(technical_state=tech_state, price_condition="DEPRESSED" if depressed else
             "EXTENDED" if close and ema50 and close > ema50 * 1.15 else "NORMAL")
    safety = s["fundamental_data_quality"] == "AVAILABLE" and not s["structural_deterioration"]
    fundamental_ready = (s["business_health"] in ("HEALTHY", "STRONG") and s["earnings_direction"] in ("STABLE", "IMPROVING")
                         and s["fundamental_event_state"] in ("STABLE", "IMPROVING"))
    balance_ready = s["balance_sheet_state"] in ("HEALTHY", "ACCEPTABLE")
    cash_ready = s["cash_flow_state"] in ("SUPPORTIVE", "ADEQUATE")
    downside_controlled = (not breakdown and atr is not None and atr <= 6
                           and close is not None and support is not None and support > 0 and close >= support * .97)
    regime = (technical.get("market_context") or {}).get("nifty_regime")
    momentum_valid = (strong and safety and fundamental_ready and atr is not None and atr <= 6 and
                      (s["financial_domain"] or (balance_ready and cash_ready)) and regime in ("BULL", "MIXED"))
    # Weak trend, RSI, MACD and EMA location are deliberately absent here.
    recovery_valid = (depressed and safety and fundamental_ready and cash_ready and balance_ready
                      and not s["financial_domain"] and downside_controlled
                      and s["valuation_state"] in ("ATTRACTIVE", "REASONABLE"))
    if not official_current: reasons.append("OFFICIAL_SESSION_NOT_CURRENT")
    if s["fundamental_data_quality"] != "AVAILABLE": reasons.append("FUNDAMENTALS_" + s["fundamental_data_quality"])
    if not fundamental_ready: reasons.append("BUSINESS_EARNINGS_OR_EVENT_EVIDENCE_INSUFFICIENT")
    if s["financial_domain"]: reasons.append("BANKING_SPECIFIC_PIT_METRICS_UNAVAILABLE_FOR_RECOVERY")
    if not cash_ready and not s["financial_domain"]: reasons.append("CASH_FLOW_NOT_SUPPORTIVE_OR_UNAVAILABLE")
    if not balance_ready and not s["financial_domain"]: reasons.append("BALANCE_SHEET_NOT_ACCEPTABLE_OR_UNAVAILABLE")
    if s["valuation_state"] == "UNAVAILABLE": reasons.append("PIT_RELATIVE_VALUATION_UNAVAILABLE")
    if depressed and not downside_controlled: reasons.append("DOWNSIDE_UNCONTROLLED_OR_UNAVAILABLE")
    if not strong: reasons.append("MOMENTUM_CONFIRMATION_INCOMPLETE")
    if s["structural_deterioration"]:
        action = "AVOID - VALUE TRAP RISK" if depressed else "AVOID - FUNDAMENTAL DETERIORATION"
    elif breakdown:
        action = "AVOID - TECHNICAL BREAKDOWN"
    elif official_current and momentum_valid and recovery_valid:
        action = "MOMENTUM + RECOVERY BUY"
    elif official_current and momentum_valid:
        action = "MOMENTUM BUY"
    elif official_current and recovery_valid:
        action = "RECOVERY BUY"
    elif strong and depressed:
        action = "WATCH - MIXED"
    elif depressed or s["fundamental_data_quality"] != "AVAILABLE":
        action = "WATCH - RECOVERY"
    elif strong:
        action = "WATCH - MOMENTUM"
    else:
        action = "NO OPPORTUNITY"
    m = "VALID" if momentum_valid else "REJECT" if s["structural_deterioration"] or breakdown else "WATCH"
    r = "VALID" if recovery_valid else "REJECT" if s["structural_deterioration"] or breakdown else "WATCH"
    momentum_reason = "Trend, relative strength, volume and completed weekly confirmation support continuation; fundamentals show no material deterioration." if m == "VALID" else "Momentum confirmation or fundamental safety is incomplete. " + ", ".join(reasons)
    recovery_reason = ("Price is depressed while business, earnings, cash flow and PIT valuation evidence support recovery. Weak technical momentum increases entry risk without invalidating this thesis. The cause of the decline is not established by these data."
                       if r == "VALID" else "A price decline alone is insufficient. " + ", ".join(reasons))
    momentum_quality = sum((technical.get("trend", {}).get("supertrend_direction") == "BULL",
                            (number(momentum.get("adx14")) or 0) >= 25, regime == "BULL"))
    recovery_quality = sum((s["business_health"] == "STRONG", s["valuation_state"] == "ATTRACTIVE",
                           s["cash_flow_state"] == "SUPPORTIVE", s["balance_sheet_state"] == "HEALTHY"))
    primary = ("RECOVERY" if recovery_quality > momentum_quality else "MOMENTUM") if momentum_valid and recovery_valid else "MOMENTUM" if momentum_valid else "RECOVERY" if recovery_valid else None
    confidence = "HIGH" if momentum_valid and recovery_valid else "MEDIUM" if momentum_valid or recovery_valid else "LOW"
    return dict(schema="SRE_LIVE_DECISION_V1", authority=AUTHORITY, model_version=MODEL,
                market_session=market_session, symbol=symbol, final_action=action,
                strategy_style=action if action in BUY_ACTIONS else "NONE", primary_style=primary,
                secondary_style=("RECOVERY" if primary == "MOMENTUM" else "MOMENTUM") if momentum_valid and recovery_valid else None,
                momentum_thesis=m, recovery_thesis=r, momentum_reason=momentum_reason,
                recovery_reason=recovery_reason, thesis=momentum_reason if primary == "MOMENTUM" else recovery_reason,
                invalidation="Material business deterioration, uncontrolled downside or loss of the original thesis; recovery also requires review when valuation advantage disappears.",
                confidence=confidence, priority="HIGH" if confidence == "HIGH" else "MEDIUM" if action in BUY_ACTIONS else "LOW",
                executable=action in BUY_ACTIONS and official_current and close is not None and close > 0,
                reason_codes=reasons, target_used_in_score=False, **s,
                evidence=dict(technical=technical, fundamental=fundamental, price_context=price_context,
                              legacy_production_evidence=legacy, official_current=official_current),
                provenance="OFFICIAL_FIRST", point_in_time_safe=fundamental.get("point_in_time_safe") is True)


def lane_counts(rows):
    counts = Counter(row.get("final_action") for row in rows)
    return dict(momentum_buy=counts["MOMENTUM BUY"], recovery_buy=counts["RECOVERY BUY"],
                both=counts["MOMENTUM + RECOVERY BUY"], watch=sum(v for k,v in counts.items() if k and k.startswith("WATCH")),
                avoid=sum(v for k,v in counts.items() if k and k.startswith("AVOID")), no_opportunity=counts["NO OPPORTUNITY"])


def monitor(position, decision):
    """Use persisted entry style. Never exit Recovery merely for weak momentum."""
    style = position.get("primary_style") or position.get("strategy_style") or ""
    if decision.get("structural_deterioration"):
        return "EXIT", "Original business safety thesis invalidated by material deterioration."
    if "RECOVERY" in style:
        if decision.get("technical_state") == "BREAKDOWN":
            return "EXIT", "Recovery downside risk is uncontrolled."
        if decision.get("valuation_state") in ("FULL", "EXPENSIVE"):
            return "EXIT", "Recovery valuation advantage has disappeared."
        if decision.get("recovery_thesis") != "VALID":
            return "WEAKENING", "Recovery evidence requires review; weak momentum alone is not an exit."
        return "HOLD", "Original recovery thesis remains valid."
    if "MOMENTUM" in style:
        if decision.get("technical_state") == "BREAKDOWN":
            return "EXIT", "Original momentum trend structure failed."
        return ("HOLD", "Momentum thesis remains valid.") if decision.get("momentum_thesis") == "VALID" else ("WEAKENING", "Momentum confirmation has weakened.")
    return "WEAKENING", "Entry strategy unavailable; explicit position review required."
