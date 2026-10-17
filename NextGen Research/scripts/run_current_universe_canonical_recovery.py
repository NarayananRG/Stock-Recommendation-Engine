from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlparse
import sys

import requests

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "NextGen Research"
sys.path.insert(0, str(ROOT))

from fundamental_research_v2_phase2a.canonical_feature_panel import build_panel_rows  # noqa: E402
from fundamental_research_v2_phase2a.current_universe_recovery import symbols_from_live_snapshot  # noqa: E402
from fundamental_research_v2_phase2a.scaled_mapping_validation import (  # noqa: E402
    compact_document_resolution,
    latest_event_groups,
)
from fundamental_research_v2_phase2a.xbrl_extraction import (  # noqa: E402
    parse_ixbrl_document,
    parse_xbrl_document,
)

OFFICIAL_HOST = "nsearchives.nseindia.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/155 Safari/537.36"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--existing-panel", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class OfficialCache:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept": "application/xml,text/xml,text/html,application/xhtml+xml,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/",
        })

    def fetch(self, url: str) -> tuple[bytes, dict]:
        parsed = urlparse(str(url or ""))
        if parsed.scheme != "https" or (parsed.hostname or "").lower() != OFFICIAL_HOST:
            raise ValueError("OFFICIAL_NSE_ARCHIVE_SOURCE_REQUIRED")
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        body_path = self.root / f"{key}.bin"
        meta_path = self.root / f"{key}.json"
        if body_path.exists() and meta_path.exists():
            body = body_path.read_bytes()
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if hashlib.sha256(body).hexdigest() != meta.get("document_sha256"):
                raise ValueError("OFFICIAL_CACHE_HASH_MISMATCH")
            return body, {**meta, "cache_reused": True}

        last = None
        for attempt in range(6):
            try:
                response = self.session.get(url, timeout=50)
                if response.status_code in {403, 429, 500, 502, 503, 504} and attempt < 5:
                    time.sleep(1 + attempt)
                    continue
                response.raise_for_status()
                body = response.content
                if not body:
                    raise ValueError("EMPTY_OFFICIAL_DOCUMENT")
                meta = {
                    "source_url": url,
                    "source_host": OFFICIAL_HOST,
                    "http_status": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "document_sha256": hashlib.sha256(body).hexdigest(),
                    "cache_reused": False,
                }
                body_path.write_bytes(body)
                meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
                return body, meta
            except Exception as exc:
                last = exc
        raise last or RuntimeError("OFFICIAL_DOCUMENT_FETCH_FAILED")


def main() -> int:
    args = arguments()
    args.out.mkdir(parents=True, exist_ok=True)
    raw_cache = OfficialCache(args.out / "raw_official")
    mapping = json.loads(
        (ROOT / "fundamental_research_v2_phase2a" / "phase2a2_canonical_mapping_freeze_v1.json").read_text(encoding="utf-8")
    )
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    events = json.loads(args.events.read_text(encoding="utf-8"))
    existing_rows = read_csv(args.existing_panel)
    target_symbols = set(symbols_from_live_snapshot(snapshot))
    panel_symbols = {str(row.get("symbol") or "").upper() for row in existing_rows}
    missing_symbols = sorted(target_symbols - panel_symbols)
    selected = [row for row in latest_event_groups(events) if row.get("symbol") in missing_symbols]

    documents = []
    terminal_ids = set()
    failures = []
    provenance = []
    by_document = args.out / "by_document"
    by_document.mkdir(exist_ok=True)
    for index, event in enumerate(selected, start=1):
        event_id = event.get("event_id")
        compact_path = by_document / f"{event_id}.json"
        try:
            if compact_path.exists():
                compact = json.loads(compact_path.read_text(encoding="utf-8"))
                documents.append(compact)
                provenance.append({"event_id": event_id, "cache_reused": True, "source_content_sha256": compact.get("source_content_sha256")})
                continue
            xbrl_url = event.get("xbrl_url")
            if not xbrl_url:
                raise ValueError("OFFICIAL_XBRL_URL_MISSING")
            try:
                body, meta = raw_cache.fetch(xbrl_url)
                document = parse_xbrl_document(body, source_url=xbrl_url, source_event=event)
                representation = "XBRL_PRIMARY"
            except requests.HTTPError as exc:
                if getattr(exc.response, "status_code", None) != 404 or not event.get("ixbrl_url"):
                    raise
                body, meta = raw_cache.fetch(event["ixbrl_url"])
                document = parse_ixbrl_document(body, source_url=event["ixbrl_url"], source_event=event)
                document["domain_source_url"] = xbrl_url
                representation = "IXBRL_SAME_EVENT_404_RECOVERY"
            compact = compact_document_resolution(document, mapping)
            compact["retrieval_representation"] = representation
            compact["primary_xbrl_url"] = xbrl_url
            compact["same_event_ixbrl_url"] = event.get("ixbrl_url")
            compact_path.write_text(json.dumps(compact, indent=2, sort_keys=True), encoding="utf-8")
            documents.append(compact)
            provenance.append({
                "event_id": event_id,
                "symbol": event.get("symbol"),
                "quarter_end": event.get("quarter_end"),
                "reporting_basis": event.get("reporting_basis"),
                "submission_type": event.get("submission_type"),
                "publication_ts": event.get("publication_ts"),
                "availability_ts": event.get("availability_ts"),
                "source_url": document.get("source_url"),
                "source_content_sha256": document.get("source_content_sha256"),
                "retrieval_representation": representation,
                "cache_reused": meta.get("cache_reused"),
            })
        except Exception as exc:
            terminal_ids.add(event_id)
            failures.append({
                "event_id": event_id,
                "symbol": event.get("symbol"),
                "quarter_end": event.get("quarter_end"),
                "reporting_basis": event.get("reporting_basis"),
                "xbrl_url": event.get("xbrl_url"),
                "ixbrl_url": event.get("ixbrl_url"),
                "reason": f"{type(exc).__name__}: {exc}",
            })
        if index % 25 == 0 or index == len(selected):
            print(f"[{index}/{len(selected)}] parsed={len(documents)} terminal={len(terminal_ids)}", flush=True)

    recovered_rows = build_panel_rows(selected, documents, terminal_ids)
    recovered_keys = {
        (row.get("symbol"), row.get("quarter_end"), row.get("reporting_basis"))
        for row in recovered_rows
    }
    merged_rows = [
        row for row in existing_rows
        if (row.get("symbol"), row.get("quarter_end"), row.get("reporting_basis")) not in recovered_keys
    ] + recovered_rows
    merged_rows.sort(key=lambda row: (str(row.get("symbol")), str(row.get("reporting_basis")), str(row.get("quarter_end"))))
    write_csv(args.out / "canonical_feature_panel_recovered.csv", recovered_rows)
    write_csv(args.out / "canonical_feature_panel_merged.csv", merged_rows)
    (args.out / "provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True), encoding="utf-8")
    summary = {
        "artifact_type": "CURRENT_LIVE_UNIVERSE_CANONICAL_RECOVERY_V1",
        "authority": "SHADOW_ONLY",
        "run_id": (snapshot.get("run") or {}).get("run_id"),
        "market_session": (snapshot.get("run") or {}).get("market_session"),
        "target_symbols": missing_symbols,
        "selected_filing_count": len(selected),
        "parsed_document_count": len(documents),
        "terminal_document_gap_count": len(terminal_ids),
        "terminal_document_gaps": failures,
        "recovered_panel_row_count": len(recovered_rows),
        "merged_panel_symbol_count": len({row.get("symbol") for row in merged_rows}),
        "source": "OFFICIAL_NSE_INTEGRATED_FILING_XBRL_IXBRL",
        "source_hashes_preserved": True,
        "frozen_historical_universe_changed": False,
        "production_model_changed": False,
        "automatic_yfinance_fallback": False,
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
    return 0 if not failures else 4


if __name__ == "__main__":
    raise SystemExit(main())
