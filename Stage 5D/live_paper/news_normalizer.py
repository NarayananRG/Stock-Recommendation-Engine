"""Conservative, deterministic mapping into the frozen Stage 5D.4 news contract."""
from __future__ import annotations

import hashlib
from typing import Mapping


ADVERSE_RULES = (
    ("FRAUD_ALLEGATION", "HIGH", ("accused of fraud", "fraud investigation", "fraud charges", "fraud detected", "accounting irregularities found", "bribery charges")),
    ("REGULATORY", "HIGH", ("regulator orders", "sebi bars", "enforcement action", "regulatory penalty")),
    ("DEBT_LIQUIDITY", "HIGH", ("defaults on", "debt default", "liquidity crisis", "files for insolvency", "admitted to insolvency")),
    ("CREDIT_RATING", "HIGH", ("rating downgraded", "credit downgrade", "downgrades rating")),
    ("GUIDANCE", "HIGH", ("cuts guidance", "guidance cut", "slashes forecast")),
    ("EARNINGS", "MEDIUM", ("misses earnings", "profit warning", "earnings miss")),
    ("ORDER_CANCELLATION", "MEDIUM", ("order cancelled", "contract cancelled", "order cancellation")),
    ("PROMOTER", "HIGH", ("promoter pledge default", "promoter shares invoked")),
    ("LEGAL", "HIGH", ("court orders damages", "major lawsuit", "class action lawsuit")),
    ("MANAGEMENT_CHANGE", "MEDIUM", ("auditor resigns", "ceo resigns", "cfo resigns")),
)


def normalize_article(article: Mapping[str, str]) -> dict[str, object]:
    from stage5d.news_ml_overlay import normalize_news_event

    headline = str(article["headline"]).strip()
    lower = headline.lower()
    category, severity, sentiment, materiality = "OTHER", "LOW", "NEUTRAL", "NON_MATERIAL"
    # A headline must explicitly describe a company-level adverse event. A
    # negative word in an otherwise ambiguous article cannot block a trade.
    for rule_category, rule_severity, phrases in ADVERSE_RULES:
        if any(phrase in lower for phrase in phrases):
            category, severity, sentiment, materiality = rule_category, rule_severity, "NEGATIVE", "MATERIAL"
            break
    identity = "|".join(str(article.get(key, "")) for key in
                        ("ticker", "headline", "source", "source_url", "published_at_utc"))
    event = {
        "event_id": "S5D5_NEWS_" + hashlib.sha256(identity.encode()).hexdigest()[:24],
        "ticker": article["ticker"], "headline": headline,
        "source": article["source"], "source_url": article.get("source_url"),
        "published_at_utc": article["published_at_utc"],
        "observed_at_utc": article["observed_at_utc"],
        "category": category, "sentiment": sentiment, "severity": severity,
        "materiality": materiality, "confidence": "0.75" if materiality == "MATERIAL" else "0.50",
        "summary": headline,
        "source_hash": hashlib.sha256(identity.encode()).hexdigest(),
    }
    return normalize_news_event(event)
