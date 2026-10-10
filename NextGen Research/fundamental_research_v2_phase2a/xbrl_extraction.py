"""Generic official-XBRL extraction controls for Fundamental Research V2 Phase 2A.2.

This module intentionally does not map taxonomy concepts to business features.
It preserves the source taxonomy and context first so mappings can be audited
from observed evidence rather than guessed.
"""
from __future__ import annotations

import hashlib
from decimal import Decimal, InvalidOperation
from io import BytesIO
from html.parser import HTMLParser
from typing import Iterable
import xml.etree.ElementTree as ET

from .core import effective_availability_ts, require_official_fundamental_url


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _namespace(tag: str) -> str | None:
    if tag.startswith("{") and "}" in tag:
        return tag[1:].split("}", 1)[0]
    return None


def _text(node: ET.Element | None) -> str | None:
    if node is None:
        return None
    value = "".join(node.itertext()).strip()
    return value or None


def _descendant(node: ET.Element, local: str) -> ET.Element | None:
    for child in node.iter():
        if _local_name(child.tag) == local:
            return child
    return None


def _numeric(value: str | None) -> bool:
    if value is None:
        return False
    cleaned = value.strip().replace(",", "")
    if not cleaned or cleaned in {"-", "—"}:
        return False
    try:
        Decimal(cleaned)
        return True
    except InvalidOperation:
        return False


def _namespace_map(xml_bytes: bytes) -> dict[str, str]:
    mapping: dict[str, str] = {}
    try:
        for _, item in ET.iterparse(BytesIO(xml_bytes), events=("start-ns",)):
            prefix, uri = item
            mapping[prefix or ""] = uri
    except ET.ParseError:
        return {}
    return mapping


def _concept_from_inline_name(name: str | None, namespaces: dict[str, str]) -> tuple[str | None, str | None]:
    text = str(name or "").strip()
    if not text:
        return None, None
    if ":" in text:
        prefix, local = text.split(":", 1)
        return namespaces.get(prefix) or namespaces.get(prefix.lower()), local
    return namespaces.get(""), text


class _TolerantIxbrlHtmlParser(HTMLParser):
    """Tolerant extractor for NSE inline-XBRL HTML that is not strict XML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.namespaces: dict[str, str] = {}
        self.contexts: dict[str, dict] = {}
        self.units: dict[str, dict] = {}
        self.numeric_facts: list[dict] = []
        self.all_fact_count = 0
        self.numeric_fact_count = 0
        self.nil_fact_count = 0
        self.current_context: dict | None = None
        self.current_unit: dict | None = None
        self.current_fact: dict | None = None
        self.fact_buffer: list[str] = []
        self.exclude_depth = 0
        self.captures: list[dict] = []

    @staticmethod
    def _local(tag: str) -> str:
        return str(tag or "").split(":")[-1].lower()

    @staticmethod
    def _attrs(attrs) -> dict[str, str | None]:
        return {str(k).lower(): v for k, v in attrs}

    def _start_capture(self, kind: str, end_local: str, **meta):
        self.captures.append({
            "kind": kind, "end_local": end_local, "buffer": [], **meta
        })

    def handle_starttag(self, tag, attrs):
        attr = self._attrs(attrs)
        local = self._local(tag)
        for key, value in attr.items():
            if key == "xmlns" and value:
                self.namespaces[""] = value
            elif key.startswith("xmlns:") and value:
                self.namespaces[key.split(":", 1)[1].lower()] = value

        if local == "context":
            context_id = attr.get("id")
            if context_id:
                self.current_context = {
                    "context_id": context_id,
                    "entity_identifier": None,
                    "instant": None,
                    "start_date": None,
                    "end_date": None,
                    "dimensions": [],
                }
        elif local == "unit":
            unit_id = attr.get("id")
            if unit_id:
                self.current_unit = {"unit_id": unit_id, "measures": []}

        if self.current_context is not None:
            field_map = {
                "identifier": "entity_identifier",
                "instant": "instant",
                "startdate": "start_date",
                "enddate": "end_date",
            }
            if local in field_map:
                self._start_capture(
                    "context_field", local, field=field_map[local]
                )
            elif local in {"explicitmember", "typedmember"}:
                self._start_capture(
                    "dimension", local,
                    dimension=attr.get("dimension"),
                    member_kind=("explicitMember" if local == "explicitmember" else "typedMember"),
                )

        if self.current_unit is not None and local == "measure":
            self._start_capture("measure", local)

        if local in {"nonfraction", "fraction"}:
            context_ref = attr.get("contextref")
            if context_ref:
                self.all_fact_count += 1
                nil_value = attr.get("xsi:nil") or attr.get("nil")
                if str(nil_value or "").strip().lower() in {"true", "1"}:
                    self.nil_fact_count += 1
                    self.current_fact = None
                    self.fact_buffer = []
                else:
                    self.current_fact = {
                        "name": attr.get("name"),
                        "context_ref": context_ref,
                        "unit_ref": attr.get("unitref"),
                        "decimals": attr.get("decimals"),
                        "scale": attr.get("scale"),
                        "sign": attr.get("sign"),
                        "end_local": local,
                    }
                    self.fact_buffer = []

        if local == "exclude" and self.current_fact is not None:
            self.exclude_depth += 1

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):
        for capture in self.captures:
            capture["buffer"].append(data)
        if self.current_fact is not None and self.exclude_depth == 0:
            self.fact_buffer.append(data)

    def handle_endtag(self, tag):
        local = self._local(tag)
        if local == "exclude" and self.exclude_depth > 0:
            self.exclude_depth -= 1

        for index in range(len(self.captures) - 1, -1, -1):
            capture = self.captures[index]
            if capture["end_local"] != local:
                continue
            self.captures.pop(index)
            value = "".join(capture["buffer"]).strip() or None
            if capture["kind"] == "context_field" and self.current_context is not None:
                self.current_context[capture["field"]] = value
            elif capture["kind"] == "dimension" and self.current_context is not None:
                self.current_context["dimensions"].append({
                    "kind": capture["member_kind"],
                    "dimension": capture.get("dimension"),
                    "member": value,
                })
            elif capture["kind"] == "measure" and self.current_unit is not None and value:
                self.current_unit["measures"].append(value)
            break

        if self.current_fact is not None and local == self.current_fact["end_local"]:
            value = "".join(self.fact_buffer).strip() or None
            if _numeric(value):
                concept_namespace, concept_local_name = _concept_from_inline_name(
                    self.current_fact.get("name"), self.namespaces
                )
                if concept_local_name:
                    self.numeric_fact_count += 1
                    self.numeric_facts.append({
                        "concept_namespace": concept_namespace,
                        "concept_local_name": concept_local_name,
                        "context_ref": self.current_fact.get("context_ref"),
                        "unit_ref": self.current_fact.get("unit_ref"),
                        "decimals": self.current_fact.get("decimals"),
                        "scale": self.current_fact.get("scale"),
                        "sign": self.current_fact.get("sign"),
                        "raw_value": value,
                    })
            self.current_fact = None
            self.fact_buffer = []
            self.exclude_depth = 0

        if local == "context" and self.current_context is not None:
            self.contexts[self.current_context["context_id"]] = self.current_context
            self.current_context = None
        elif local == "unit" and self.current_unit is not None:
            self.units[self.current_unit["unit_id"]] = self.current_unit
            self.current_unit = None


def _parse_ixbrl_html_tolerant(xml_bytes: bytes) -> dict:
    parser = _TolerantIxbrlHtmlParser()
    text = xml_bytes.decode("utf-8", errors="replace")
    parser.feed(text)
    parser.close()
    if not parser.contexts:
        raise ValueError("IXBRL_HTML_CONTEXTS_NOT_FOUND")
    if not parser.numeric_facts:
        raise ValueError("IXBRL_HTML_NUMERIC_FACTS_NOT_FOUND")
    return {
        "contexts": parser.contexts,
        "units": parser.units,
        "numeric_facts": parser.numeric_facts,
        "all_fact_count": parser.all_fact_count,
        "numeric_fact_count": parser.numeric_fact_count,
        "nil_fact_count": parser.nil_fact_count,
        "parser_mode": "HTML_TOLERANT",
    }

def parse_ixbrl_document(
    xml_bytes: bytes,
    *,
    source_url: str,
    source_event: dict,
) -> dict:
    """Parse official NSE inline-XBRL, tolerating non-XML HTML markup."""
    require_official_fundamental_url(source_url)
    if not xml_bytes:
        raise ValueError("EMPTY_IXBRL_DOCUMENT")

    parser_mode = "XML_STRICT"
    namespaces = _namespace_map(xml_bytes)
    try:
        root = ET.fromstring(xml_bytes)
        contexts: dict[str, dict] = {}
        units: dict[str, dict] = {}
        for node in root.iter():
            local = _local_name(node.tag)
            if local == "context":
                context_id = node.attrib.get("id")
                if not context_id:
                    continue
                identifier = _text(_descendant(node, "identifier"))
                instant = _text(_descendant(node, "instant"))
                start_date = _text(_descendant(node, "startDate"))
                end_date = _text(_descendant(node, "endDate"))
                dimensions = []
                for member in node.iter():
                    member_local = _local_name(member.tag)
                    if member_local in {"explicitMember", "typedMember"}:
                        dimensions.append({
                            "kind": member_local,
                            "dimension": member.attrib.get("dimension"),
                            "member": _text(member),
                        })
                contexts[context_id] = {
                    "context_id": context_id,
                    "entity_identifier": identifier,
                    "instant": instant,
                    "start_date": start_date,
                    "end_date": end_date,
                    "dimensions": dimensions,
                }
            elif local == "unit":
                unit_id = node.attrib.get("id")
                if not unit_id:
                    continue
                measures = [
                    _text(child) for child in node.iter()
                    if _local_name(child.tag) == "measure" and _text(child)
                ]
                units[unit_id] = {"unit_id": unit_id, "measures": measures}

        numeric_facts = []
        all_fact_count = 0
        numeric_fact_count = 0
        nil_fact_count = 0
        for node in root.iter():
            local = _local_name(node.tag)
            if local not in {"nonFraction", "fraction"}:
                continue
            context_ref = node.attrib.get("contextRef")
            if not context_ref:
                continue
            all_fact_count += 1
            nil_value = (
                node.attrib.get("{http://www.w3.org/2001/XMLSchema-instance}nil")
                or node.attrib.get("nil")
            )
            if str(nil_value or "").strip().lower() in {"true", "1"}:
                nil_fact_count += 1
                continue
            value = _text(node)
            if not _numeric(value):
                continue
            concept_namespace, concept_local_name = _concept_from_inline_name(
                node.attrib.get("name"), namespaces
            )
            if not concept_local_name:
                continue
            numeric_fact_count += 1
            numeric_facts.append({
                "concept_namespace": concept_namespace,
                "concept_local_name": concept_local_name,
                "context_ref": context_ref,
                "unit_ref": node.attrib.get("unitRef"),
                "decimals": node.attrib.get("decimals"),
                "scale": node.attrib.get("scale"),
                "sign": node.attrib.get("sign"),
                "raw_value": value,
            })
    except ET.ParseError:
        tolerant = _parse_ixbrl_html_tolerant(xml_bytes)
        contexts = tolerant["contexts"]
        units = tolerant["units"]
        numeric_facts = tolerant["numeric_facts"]
        all_fact_count = tolerant["all_fact_count"]
        numeric_fact_count = tolerant["numeric_fact_count"]
        nil_fact_count = tolerant["nil_fact_count"]
        parser_mode = tolerant["parser_mode"]

    event = dict(source_event)
    return {
        "artifact_type": "FUNDAMENTAL_RESEARCH_V2_PHASE2A2_IXBRL_DOCUMENT_V1",
        "source_url": source_url,
        "source_content_sha256": sha256_bytes(xml_bytes),
        "source_event_id": event.get("event_id"),
        "symbol": event.get("symbol"),
        "quarter_end": event.get("quarter_end"),
        "reporting_basis": event.get("reporting_basis"),
        "submission_type": event.get("submission_type"),
        "provider_seq_id": event.get("provider_seq_id"),
        "availability_ts": effective_availability_ts(event),
        "context_count": len(contexts),
        "unit_count": len(units),
        "all_fact_count": all_fact_count,
        "numeric_fact_count": numeric_fact_count,
        "nil_fact_count": nil_fact_count,
        "contexts": sorted(contexts.values(), key=lambda item: item["context_id"]),
        "units": sorted(units.values(), key=lambda item: item["unit_id"]),
        "numeric_facts": numeric_facts,
        "authority": "SHADOW_ONLY",
        "source_document_kind": "IXBRL",
        "ixbrl_parser_mode": parser_mode,
    }

def parse_xbrl_document(
    xml_bytes: bytes,
    *,
    source_url: str,
    source_event: dict,
) -> dict:
    require_official_fundamental_url(source_url)
    if not xml_bytes:
        raise ValueError("EMPTY_XBRL_DOCUMENT")

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"INVALID_XBRL_XML: {exc}") from exc

    contexts: dict[str, dict] = {}
    units: dict[str, dict] = {}

    for node in root.iter():
        local = _local_name(node.tag)
        if local == "context":
            context_id = node.attrib.get("id")
            if not context_id:
                continue
            identifier = _text(_descendant(node, "identifier"))
            instant = _text(_descendant(node, "instant"))
            start_date = _text(_descendant(node, "startDate"))
            end_date = _text(_descendant(node, "endDate"))
            dimensions = []
            for member in node.iter():
                member_local = _local_name(member.tag)
                if member_local in {"explicitMember", "typedMember"}:
                    dimensions.append({
                        "kind": member_local,
                        "dimension": member.attrib.get("dimension"),
                        "member": _text(member),
                    })
            contexts[context_id] = {
                "context_id": context_id,
                "entity_identifier": identifier,
                "instant": instant,
                "start_date": start_date,
                "end_date": end_date,
                "dimensions": dimensions,
            }
        elif local == "unit":
            unit_id = node.attrib.get("id")
            if not unit_id:
                continue
            measures = [
                _text(child) for child in node.iter()
                if _local_name(child.tag) == "measure" and _text(child)
            ]
            units[unit_id] = {
                "unit_id": unit_id,
                "measures": measures,
            }

    numeric_facts = []
    all_fact_count = 0
    numeric_fact_count = 0
    nil_fact_count = 0

    for node in root.iter():
        context_ref = node.attrib.get("contextRef")
        if not context_ref:
            continue
        all_fact_count += 1

        nil_value = (
            node.attrib.get("{http://www.w3.org/2001/XMLSchema-instance}nil")
            or node.attrib.get("nil")
        )
        is_nil = str(nil_value or "").strip().lower() in {"true", "1"}
        if is_nil:
            nil_fact_count += 1
            continue

        value = _text(node)
        if not _numeric(value):
            continue

        numeric_fact_count += 1
        numeric_facts.append({
            "concept_namespace": _namespace(node.tag),
            "concept_local_name": _local_name(node.tag),
            "context_ref": context_ref,
            "unit_ref": node.attrib.get("unitRef"),
            "decimals": node.attrib.get("decimals"),
            "scale": node.attrib.get("scale"),
            "sign": node.attrib.get("sign"),
            "raw_value": value,
        })

    event = dict(source_event)
    return {
        "artifact_type": "FUNDAMENTAL_RESEARCH_V2_PHASE2A2_XBRL_DOCUMENT_V1",
        "source_url": source_url,
        "source_content_sha256": sha256_bytes(xml_bytes),
        "source_event_id": event.get("event_id"),
        "symbol": event.get("symbol"),
        "quarter_end": event.get("quarter_end"),
        "reporting_basis": event.get("reporting_basis"),
        "submission_type": event.get("submission_type"),
        "provider_seq_id": event.get("provider_seq_id"),
        "availability_ts": effective_availability_ts(event),
        "context_count": len(contexts),
        "unit_count": len(units),
        "all_fact_count": all_fact_count,
        "numeric_fact_count": numeric_fact_count,
        "nil_fact_count": nil_fact_count,
        "contexts": sorted(contexts.values(), key=lambda x: x["context_id"]),
        "units": sorted(units.values(), key=lambda x: x["unit_id"]),
        "numeric_facts": numeric_facts,
        "authority": "SHADOW_ONLY",
        "source_document_kind": "XBRL",
    }


def latest_events_by_group(events: Iterable[dict], *, symbols: set[str], quarters: set[str]) -> list[dict]:
    grouped: dict[tuple[str, str, str], dict] = {}
    for raw in events:
        event = dict(raw)
        symbol = event.get("symbol")
        quarter = event.get("quarter_end")
        basis = event.get("reporting_basis")
        if symbol not in symbols or quarter not in quarters or not basis:
            continue
        if not event.get("xbrl_url"):
            continue
        key = (symbol, quarter, basis)
        current = grouped.get(key)
        if current is None or effective_availability_ts(event) > effective_availability_ts(current):
            grouped[key] = event
    return [grouped[key] for key in sorted(grouped)]
