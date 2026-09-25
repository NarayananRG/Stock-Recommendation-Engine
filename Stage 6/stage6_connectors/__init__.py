"""Controlled Stage 6.1B external-source connectors.

Importing this package performs no network or persistence activity.
"""

from .sebi_rss import SEBI_SOURCE_ID, SebiRssConnector

__all__ = ["SEBI_SOURCE_ID", "SebiRssConnector"]
