"""Bounded, no-fetch RSS/Atom metadata validation shared by approved connectors."""
from __future__ import annotations

from datetime import timezone
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

from stage6_ingestion.canonical import parse_utc, utc_timestamp


ALLOWED_CONTENT_TYPES = {"application/rss+xml", "application/xml", "text/xml"}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def feed_metadata(body: bytes, content_type: str, observed: str, *, truncated: bool) -> dict:
    media_type = content_type.split(";", 1)[0].strip().casefold()
    if truncated:
        return {"valid": False, "reason": "TRUNCATED_PAYLOAD", "publication": None, "title": None}
    if media_type not in ALLOWED_CONTENT_TYPES:
        return {"valid": False, "reason": "CONTENT_TYPE_REJECTED", "publication": None, "title": None}
    lowered = body.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        return {"valid": False, "reason": "XML_EXTERNAL_OR_ENTITY_DECLARATION_REJECTED", "publication": None, "title": None}
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return {"valid": False, "reason": "MALFORMED_XML", "publication": None, "title": None}
    root_name = _local_name(root.tag)
    if root_name == "rss":
        channel = next((child for child in root if _local_name(child.tag) == "channel"), None)
        if channel is None:
            return {"valid": False, "reason": "RSS_CHANNEL_MISSING", "publication": None, "title": None}
        title_node = next((child for child in channel if _local_name(child.tag) == "title"), None)
        date_node = next((child for child in channel if _local_name(child.tag) == "pubdate"), None)
        if date_node is None:
            date_node = next((child for child in channel if _local_name(child.tag) == "lastbuilddate"), None)
    elif root_name == "feed":
        channel = root
        title_node = next((child for child in channel if _local_name(child.tag) == "title"), None)
        date_node = next((child for child in channel if _local_name(child.tag) in {"updated", "published"}), None)
    else:
        return {"valid": False, "reason": "RSS_ROOT_REJECTED", "publication": None, "title": None}
    title = title_node.text.strip() if title_node is not None and title_node.text else None
    publication = None
    if date_node is not None and date_node.text and date_node.text.strip():
        raw_date = date_node.text.strip()
        try:
            if root_name == "rss":
                parsed = parsedate_to_datetime(raw_date)
                if parsed.tzinfo is None:
                    raise ValueError("timezone required")
                publication = parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            else:
                publication = utc_timestamp(raw_date, "feed.publication")
        except (TypeError, ValueError):
            return {"valid": False, "reason": "PUBLISHER_TIMESTAMP_INVALID", "publication": None, "title": title}
        if parse_utc(publication, "feed.publication") > parse_utc(observed, "observed"):
            return {"valid": False, "reason": "PUBLISHER_TIMESTAMP_FROM_FUTURE", "publication": None, "title": title}
    return {"valid": True, "reason": None, "publication": publication, "title": title}
