"""Live-only portfolio-wide paper entry admission guard."""
from __future__ import annotations

from typing import Any, Iterable, Mapping

MAX_SLOTS = 5


def available_slots(open_tickers: Iterable[str], pending: Iterable[Any]) -> int:
    held = {str(ticker).upper() for ticker in open_tickers}
    pending_new = {
        str(item.ticker if hasattr(item, "ticker") else item["ticker"]).upper()
        for item in pending
    } - held
    return max(0, MAX_SLOTS - len(held | pending_new))


def admission_status(
    recommendation: Mapping[str, Any], overlay: Mapping[str, Any], news_status: str,
    open_tickers: Iterable[str], pending: Iterable[Any],
) -> str:
    ticker = str(recommendation["ticker"]).upper()
    recommendation_id = str(recommendation["recommendation_id"])
    held = {str(item).upper() for item in open_tickers}
    reservations = tuple(pending)
    if news_status != "AVAILABLE":
        return "BLOCKED_NEWS_DATA_UNAVAILABLE"
    if str(overlay["official_paper_action"]) not in {"BUY", "STRONG BUY"}:
        return "BLOCKED_OFFICIAL_ACTION_NOT_BUY"
    if ticker in held:
        return "BLOCKED_EXISTING_POSITION"
    if any(str(item.source_recommendation_id) == recommendation_id for item in reservations):
        return "BLOCKED_DUPLICATE_PENDING_RECOMMENDATION"
    if any(str(item.ticker).upper() == ticker for item in reservations):
        return "BLOCKED_DUPLICATE_PENDING_TICKER"
    if available_slots(held, reservations) == 0:
        return "BLOCKED_MAX_PORTFOLIO_SLOTS"
    return "ADMISSION_ALLOWED"
