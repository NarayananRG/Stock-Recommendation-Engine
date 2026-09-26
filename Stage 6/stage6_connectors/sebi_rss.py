"""Frozen-behaviour SEBI wrapper over the approved official RSS flow."""
from __future__ import annotations

from .live_registries import SEBI_SOURCE_ID
from .official_rss import OfficialRssConnector
from .rss_common import feed_metadata as _feed_metadata
from .transport import TransportResponse


class SebiRssConnector(OfficialRssConnector):
    def __init__(self, store, transport=None):
        super().__init__(store, SEBI_SOURCE_ID, transport)


__all__ = ["SEBI_SOURCE_ID", "SebiRssConnector", "TransportResponse", "_feed_metadata"]
