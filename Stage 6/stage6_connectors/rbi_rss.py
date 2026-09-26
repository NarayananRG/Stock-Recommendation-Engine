"""RBI Press Releases RSS wrapper over the approved official RSS flow."""
from __future__ import annotations

from .live_registries import RBI_SOURCE_ID
from .official_rss import OfficialRssConnector
from .transport import TransportResponse


class RbiRssConnector(OfficialRssConnector):
    def __init__(self, store, transport=None):
        super().__init__(store, RBI_SOURCE_ID, transport)


__all__ = ["RBI_SOURCE_ID", "RbiRssConnector", "TransportResponse"]
