"""No-key live news acquisition; unavailable feeds are never treated as no news."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _publication(value: Any) -> str:
    if value is None or value == "":
        raise ValueError("NEWS_PUBLICATION_TIMESTAMP_MISSING")
    if isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(value, timezone.utc)
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("NEWS_PUBLICATION_TIMESTAMP_UNTRUSTWORTHY")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def fetch_yfinance_news(ticker: str) -> tuple[list[dict[str, str]], list[str]]:
    import yfinance as yf  # Frozen Stage 4A.3 runtime dependency.

    cache = Path(__file__).resolve().parents[1] / "runtime/yfinance_news_cache"
    cache.mkdir(parents=True, exist_ok=True)
    if hasattr(yf, "set_tz_cache_location"):
        yf.set_tz_cache_location(str(cache))
    raw = yf.Ticker(ticker).news
    if raw is None or not isinstance(raw, list) or not raw:
        raise RuntimeError("NEWS_DATA_UNAVAILABLE")
    articles: list[dict[str, str]] = []
    quarantined: list[str] = []
    for index, item in enumerate(raw):
        content = item.get("content") if isinstance(item, dict) else None
        content = content if isinstance(content, dict) else item if isinstance(item, dict) else {}
        try:
            observed = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
            related = content.get("relatedTickers") or item.get("relatedTickers") if isinstance(item, dict) else None
            if related and ticker.upper() not in {str(value).upper() for value in related}:
                raise ValueError("ARTICLE_NOT_RELATED_TO_TICKER")
            title = str(content.get("title") or "").strip()
            if not title:
                raise ValueError("HEADLINE_MISSING")
            published = _publication(content.get("pubDate", content.get("providerPublishTime")))
            if published > observed:
                raise ValueError("PUBLICATION_AFTER_OBSERVATION")
            provider = content.get("provider") or {}
            source = (provider.get("displayName") if isinstance(provider, dict) else provider) or content.get("publisher")
            canonical = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
            url = (canonical.get("url") if isinstance(canonical, dict) else canonical) or content.get("link")
            articles.append({"ticker": ticker.upper(), "headline": title,
                             "source": str(source or "Yahoo Finance"), "source_url": str(url or ""),
                             "published_at_utc": published, "observed_at_utc": observed})
        except (ValueError, TypeError, OverflowError) as exc:
            quarantined.append(f"article[{index}]:{exc}")
    return articles, quarantined
