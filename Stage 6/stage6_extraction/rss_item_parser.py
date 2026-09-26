"""Bounded, deterministic, no-fetch RSS/Atom item parser."""
from __future__ import annotations

from datetime import timezone
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

from stage6_ingestion.canonical import utc_timestamp
from stage6_ingestion.errors import Stage6IngestionError

from .errors import Stage6ExtractionError


PARSER_VERSION = "STAGE6_2B_RSS_ITEM_PARSER_V1"
MAX_FEED_ITEMS = 100
MAX_TEXT_FIELD_CHARS = 100_000
MAX_TOTAL_EXTRACTED_CHARS = 1_000_000


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _children(parent: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in parent if local_name(child.tag) == name]


def _first(parent: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in parent if local_name(child.tag) == name), None)


def _text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    # XML decoding and nested text traversal are deterministic. Only surrounding
    # whitespace is removed; wording, punctuation, case, and internal spacing remain.
    value = "".join(element.itertext()).strip()
    return value or None


def _timestamp(value: str | None, feed_type: str) -> tuple[str | None, str]:
    if value is None or not value.strip():
        return None, "MISSING"
    try:
        if feed_type == "RSS":
            parsed = parsedate_to_datetime(value.strip())
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("timezone required")
            return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"), "VALID"
        return utc_timestamp(value.strip(), "atom.item_timestamp"), "VALID"
    except (TypeError, ValueError, Stage6IngestionError):
        return None, "INVALID_OR_AMBIGUOUS"


def _atom_link(entry: ET.Element) -> str | None:
    for link in _children(entry, "link"):
        rel = link.attrib.get("rel")
        href = link.attrib.get("href")
        if href and (rel is None or rel.casefold() == "alternate"):
            return href.strip() or None
    return None


def _bounded(value: str | None, field: str) -> str | None:
    if value is not None and len(value) > MAX_TEXT_FIELD_CHARS:
        raise Stage6ExtractionError(f"EXTRACTED_FIELD_LIMIT_EXCEEDED:{field}")
    return value


def parse_feed_items(payload: bytes) -> list[dict]:
    if not isinstance(payload, bytes):
        raise Stage6ExtractionError("RAW_PAYLOAD_BYTES_REQUIRED")
    lowered = payload.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise Stage6ExtractionError("UNSAFE_XML_DECLARATION_REJECTED")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise Stage6ExtractionError("MALFORMED_XML") from exc
    root_kind = local_name(root.tag)
    if root_kind == "rss":
        channel = _first(root, "channel")
        if channel is None:
            raise Stage6ExtractionError("RSS_CHANNEL_MISSING")
        nodes, feed_type, locator_root = _children(channel, "item"), "RSS", "/rss/channel/item"
    elif root_kind == "feed":
        nodes, feed_type, locator_root = _children(root, "entry"), "ATOM", "/feed/entry"
    else:
        raise Stage6ExtractionError("UNSUPPORTED_FEED_ROOT")
    if len(nodes) > MAX_FEED_ITEMS:
        raise Stage6ExtractionError("FEED_ITEM_LIMIT_EXCEEDED")
    output: list[dict] = []
    total = 0
    for ordinal, node in enumerate(nodes):
        title = _bounded(_text(_first(node, "title")), "title_text")
        if feed_type == "RSS":
            description = _bounded(_text(_first(node, "description")), "description_text")
            link = _bounded(_text(_first(node, "link")), "link_value")
            stable_id = _bounded(_text(_first(node, "guid")), "guid_or_atom_id")
            date_text = _text(_first(node, "pubdate"))
            identifier_type = "GUID" if stable_id else "LINK" if link else "STRUCTURAL_LOCATOR"
        else:
            summary = _first(node, "summary")
            description = _bounded(_text(summary) if summary is not None else _text(_first(node, "content")), "description_text")
            link = _bounded(_atom_link(node), "link_value")
            stable_id = _bounded(_text(_first(node, "id")), "guid_or_atom_id")
            published = _first(node, "published")
            date_text = _text(published) if published is not None else _text(_first(node, "updated"))
            identifier_type = "ATOM_ID" if stable_id else "LINK" if link else "STRUCTURAL_LOCATOR"
        locator = f"{locator_root}[{ordinal}]"
        identifier_value = stable_id or link or locator
        publication, timestamp_status = _timestamp(date_text, feed_type)
        total += sum(len(value) for value in (title, description, link, stable_id) if value is not None)
        if total > MAX_TOTAL_EXTRACTED_CHARS:
            raise Stage6ExtractionError("TOTAL_EXTRACTED_CHARACTER_LIMIT_EXCEEDED")
        output.append({
            "item_ordinal": ordinal, "structural_locator": locator,
            "item_identifier_type": identifier_type, "item_identifier_value": identifier_value,
            "title_text": title, "description_text": description, "link_value": link,
            "guid_or_atom_id": stable_id, "publication_timestamp_utc": publication,
            "timestamp_status": timestamp_status,
        })
    return output
