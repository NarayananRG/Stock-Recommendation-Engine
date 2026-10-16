from __future__ import annotations

import csv
import json
import os
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "NextGen Research"
sys.path.insert(0, str(ROOT))

from fundamental_research_v2_phase2a.canonical_mapping_audit import classify_domain
from fundamental_research_v2_phase2a.scaled_mapping_validation import latest_event_groups
from fundamental_research_v2_phase2a.xbrl_extraction import parse_ixbrl_document, parse_xbrl_document

OFFICIAL_HOST = "nsearchives.nseindia.com"
DIAG = Path(os.environ["SRE_PHASE5_DIAGNOSTICS_ROOT"])
OUT = Path(os.environ.get("SRE_EVIDENCE_AUDIT_OUT", str(Path.cwd() / "work" / "missing-evidence-audit")))
OUT.mkdir(parents=True, exist_ok=True)
EVENTS = DIAG / "fundamental_v2_phase2a1_scaled" / "all_target_events.json"
_tls = threading.local()

METRICS = {
    "GNPA": re.compile(r"GrossNonPerformingAssets|PercentageOfGrossNpa", re.I),
    "NNPA": re.compile(r"^(NonPerformingAssets|PercentageOfNpa)$", re.I),
    "asset quality": re.compile(r"NonPerforming|AssetQuality", re.I),
    "capital adequacy / CRAR": re.compile(r"CapitalAdequacy|CRAR|CapitalRatio", re.I),
    "CET1 / Tier 1": re.compile(r"CET1|Tier.?1", re.I),
    "provisioning": re.compile(r"Provision|Contingenc", re.I),
    "provision coverage": re.compile(r"ProvisionCoverage|CoverageRatio", re.I),
    "credit cost": re.compile(r"CreditCost", re.I),
    "deposits": re.compile(r"Deposit", re.I),
    "advances": re.compile(r"Advance", re.I),
    "funding/liquidity": re.compile(r"Liquidity|Funding", re.I),
    "loan/deposit or credit/deposit ratio": re.compile(r"(Loan|Credit).*Deposit.*Ratio|Deposit.*(Loan|Credit).*Ratio", re.I),
    "NIM / spread": re.compile(r"NetInterestMargin|InterestSpread|^NIM$", re.I),
    "ROA": re.compile(r"ReturnOnAssets|^ROA$", re.I),
    "ROE": re.compile(r"ReturnOnEquity|^ROE$", re.I),
}


def _session() -> requests.Session:
    value = getattr(_tls, "value", None)
    if value is None:
        value = requests.Session()
        value.headers.update({"User-Agent": "Mozilla/5.0 Chrome/155", "Accept": "application/xml,text/xml,text/html,*/*"})
        _tls.value = value
    return value


def _fetch(url: str) -> bytes:
    if (urlparse(url).hostname or "").lower() != OFFICIAL_HOST:
        raise RuntimeError("NON_OFFICIAL_SOURCE:" + url)
    last = None
    for attempt in range(6):
        try:
            response = _session().get(url, timeout=50)
            if response.status_code in {403, 429, 500, 502, 503, 504}:
                time.sleep(attempt + 1)
                continue
            response.raise_for_status()
            return response.content
        except Exception as exc:
            last = exc
            time.sleep(.5 * (attempt + 1))
    raise last or RuntimeError("FETCH_FAILED")


def _selected_events() -> list[dict]:
    events = latest_event_groups(json.loads(EVENTS.read_text(encoding="utf-8")))
    by_symbol = defaultdict(list)
    for event in events:
        by_symbol[str(event.get("symbol"))].append(event)
    selected = []
    for _, items in sorted(by_symbol.items()):
        items.sort(key=lambda e: (str(e.get("quarter_end") or ""), e.get("reporting_basis") == "CONSOLIDATED"), reverse=True)
        chosen = next((e for e in items if e.get("reporting_basis") == "CONSOLIDATED" and e.get("xbrl_url")), None)
        chosen = chosen or next((e for e in items if e.get("xbrl_url")), None)
        if chosen:
            selected.append(chosen)
    return selected


def _parse(event: dict) -> dict:
    xurl = str(event["xbrl_url"])
    try:
        document = parse_xbrl_document(_fetch(xurl), source_url=xurl, source_event=event)
    except requests.HTTPError as exc:
        ixurl = str(event.get("ixbrl_url") or "")
        if getattr(exc.response, "status_code", None) != 404 or not ixurl:
            raise
        document = parse_ixbrl_document(_fetch(ixurl), source_url=ixurl, source_event=event)
        document["domain_source_url"] = xurl
    domain = classify_domain(document.get("domain_source_url") or document.get("source_url"))
    if domain not in {"BANK", "NBFC"}:
        return {"skip": True, "domain": domain}
    contexts = {c.get("context_id"): c for c in document.get("contexts", [])}
    units = {u.get("unit_id"): u for u in document.get("units", [])}
    hits = {name: [] for name in METRICS}
    seen = set()
    for fact in document.get("numeric_facts", []):
        concept = str(fact.get("concept_local_name") or "")
        if not concept:
            continue
        context = contexts.get(fact.get("context_ref")) or {}
        for metric, pattern in METRICS.items():
            if not pattern.search(concept):
                continue
            signature = (metric, concept, fact.get("context_ref"), fact.get("raw_value"))
            if signature in seen:
                continue
            seen.add(signature)
            hits[metric].append({
                "concept": concept,
                "raw_value": fact.get("raw_value"),
                "unit_ref": fact.get("unit_ref"),
                "unit": units.get(fact.get("unit_ref")),
                "context_ref": fact.get("context_ref"),
                "instant": context.get("instant"),
                "start_date": context.get("start_date"),
                "end_date": context.get("end_date"),
                "dimensions": context.get("dimensions") or [],
            })
    return {
        "symbol": event.get("symbol"), "domain": domain, "quarter_end": event.get("quarter_end"),
        "reporting_basis": event.get("reporting_basis"), "availability_ts": event.get("effective_availability_ts") or event.get("availability_ts"),
        "source_url": xurl, "source_host": OFFICIAL_HOST, "hits": hits,
    }


events = _selected_events()
rows = []
failures = []
with ThreadPoolExecutor(max_workers=6) as pool:
    futures = {pool.submit(_parse, event): event for event in events}
    for index, future in enumerate(as_completed(futures), 1):
        event = futures[future]
        try:
            result = future.result()
            if not result.get("skip"):
                rows.append(result)
        except Exception as exc:
            failures.append({"symbol": event.get("symbol"), "error": type(exc).__name__ + ": " + str(exc)})
        if index % 25 == 0 or index == len(events):
            print(f"[{index}/{len(events)}] financial={len(rows)} failures={len(failures)}", flush=True)

rows.sort(key=lambda x: x["symbol"])
flat = []
for row in rows:
    for metric, facts in row["hits"].items():
        concepts = sorted({f["concept"] for f in facts})
        flat.append({
            "symbol": row["symbol"], "domain": row["domain"], "metric": metric,
            "condition": "POLICY_NOT_VALIDATED" if facts else "MISSING_SOURCE_DATA",
            "concepts": ";".join(concepts), "fact_count": len(facts),
            "units": json.dumps(sorted({str(f.get("unit")) for f in facts if f.get("unit")})),
            "current_or_period_contexts": json.dumps(sorted({str(f.get("instant") or f.get("end_date") or "") for f in facts})),
            "dimensional_fact_count": sum(bool(f.get("dimensions")) for f in facts),
            "quarter_end": row["quarter_end"], "reporting_basis": row["reporting_basis"],
            "availability_ts": row["availability_ts"], "source_host": OFFICIAL_HOST,
            "source_url": row["source_url"], "production_ready": False,
        })

with (OUT / "financial_domain_metric_coverage.csv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(flat[0].keys()) if flat else ["symbol"])
    writer.writeheader()
    writer.writerows(flat)

report = {
    "schema": "SRE_FINANCIAL_DOMAIN_METRIC_COVERAGE_V1",
    "source": "OFFICIAL_NSE_INTEGRATED_FILING_XBRL",
    "source_host_restriction": OFFICIAL_HOST,
    "documents_requested": len(events), "financial_documents_parsed": len(rows), "failures": failures,
    "domain_counts": dict(Counter(row["domain"] for row in rows)),
    "metric_symbol_coverage": {
        metric: sum(bool(row["hits"][metric]) for row in rows) for metric in METRICS
    },
    "rows": rows,
    "production_policy": "FAIL_CLOSED_POLICY_NOT_VALIDATED",
    "financial_domain_ready": False,
    "thresholds_validated": False,
    "production_logic_changed": False,
    "automatic_yfinance_fallback": False,
}
(OUT / "financial_domain_metric_coverage.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
assert all(item["source_host"] == OFFICIAL_HOST for item in rows)
assert all(item["domain"] in {"BANK", "NBFC"} for item in rows)
assert report["financial_domain_ready"] is False
print(json.dumps({key: value for key, value in report.items() if key != "rows"}, indent=2), flush=True)

