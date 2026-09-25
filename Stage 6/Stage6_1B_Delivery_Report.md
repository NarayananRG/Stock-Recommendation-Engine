# Stage 6.1B Delivery Report

## Outcome

Stage 6.1B is **PASS**. It adds one deliberately narrow external acquisition boundary for the official SEBI RSS document at `https://www.sebi.gov.in/sebirss.xml`. The final opt-in live smoke made one request to `www.sebi.gov.in`, created retrieved evidence `S6EV_75818548cd4fc4d2aae1953f`, preserved exact response bytes with SHA-256 `b446c6731b6bbcd9dd872192e7cc20c3f2a57e0ca4631cc3390eb78c34e167f5`, reopened the store, and passed full integrity verification.

The complete Stage 6.1A regression remains **152/152 PASS**. The new deterministic Stage 6.1B suite is **68/68 PASS** and uses an enforced socket sentinel, so its network-call count is zero. The unchanged Stage 6.0C validator is **PASS** with all 10 frozen schemas parsed.

## What Stage 6.1B does

- Builds deterministic operational V1 Entity and Source Registry snapshots for SEBI and `SEBI_OFFICIAL_RSS`; it does not reuse synthetic Stage 6.1A fixtures as live identities.
- Documents the fixed source review time and why the official SEBI RSS endpoint is approved for controlled automated ingestion.
- Requires point-in-time registry integrity, source approval, and unambiguous SEBI regulator resolution before transport is invoked.
- Restricts transport to HTTPS, host `www.sebi.gov.in`, path `/sebirss.xml`, standard port 443, bounded redirects, a bounded timeout, and a 2 MiB response limit.
- Rejects downgrade, cross-host, arbitrary-path, IP, localhost, user-info, query-substitution, and non-HTTPS endpoints.
- Retrieves one RSS document per explicit run, performs bounded minimal XML/RSS validation without external entity resolution, and never follows item links or attachments.
- Sends exact response bytes unchanged to the Stage 6.1A content-addressed raw store.
- Captures a valid document as `EVIDENCE`, a retrieved but unusable document as `QUARANTINED` evidence, and a no-payload transport/HTTP failure as an `ACQUISITION_ATTEMPT`.
- Uses an idempotency key derived from operation kind, exact registry snapshots, source identity, observation/retrieval timestamps, and payload hash or failure discriminator. An exact retry is idempotent; a later observation remains a new immutable record even when bytes are unchanged.
- Exposes an explicit one-shot command only: `python -m stage6_connectors.run_sebi_rss --live` from the `Stage 6` directory.

## What Stage 6.1B does not do

- It does not generate recommendations, BUY/SELL/HOLD decisions, rankings, quantities, stops, targets, portfolio actions, event causality, sentiment, or ML output.
- It has no broker connectivity and no production decision influence.
- It does not modify Stage 5D.5 or any frozen Stage 6 architecture file.
- It does not add NSE, BSE, Yahoo, Google, GDELT, news-site, social-media, company-IR, search-engine, or generic crawler access.
- It does not fetch SEBI item links, webpages, PDFs, circular attachments, or order attachments.
- It does not schedule itself or execute network activity on import.
- It does not interpret the acquired RSS content as market intelligence; that remains outside Stage 6.1B.

Authority remains `SHADOW_ONLY`. Stage 6.1A remains frozen at `stage6-1a-ingestion-foundation-baseline` / `d5012decd2ff92ab088648b651d6285be17e8cc3`. The Stage 6 architecture and Stage 5D.5 production-control baselines remain unchanged.

## Live validation

Two explicit validation executions were made, each issuing exactly one request to the sole allowlisted host. The first preserved the real 19,657-byte response as quarantined evidence because the feed's first channel timestamp, `lastBuildDate`, omitted a timezone. Inspection showed the same document also provides a standards-usable, timezone-qualified channel `pubDate`. The parser was narrowed to prefer that explicit publication timestamp, a deterministic regression test was added, and a fresh final smoke succeeded as `RETRIEVED`. Both runtime stores passed full integrity, and neither is committed.

Failure means acquisition failure only. It is never interpreted as no SEBI news, no event, neutral, safe, or no risk.

## Evidence and deferred work

- Deterministic test evidence: `Stage 6/results/stage6_1b_test_results.csv`
- Machine-readable contract: `Stage 6/results/stage6_1b_contract.json`
- Final live evidence ID: `S6EV_75818548cd4fc4d2aae1953f`
- Initial quarantined evidence ID: `S6EV_e5916e819d23c98bf3e97c1a`
- Live raw payload SHA-256: `b446c6731b6bbcd9dd872192e7cc20c3f2a57e0ca4631cc3390eb78c34e167f5`

ETag/Last-Modified conditional polling, scheduling, linked-document acquisition, event interpretation, and every additional source connector are deferred. Runtime SQLite files, raw objects, caches, credentials, cookies, and session artifacts are gitignored and excluded from delivery.
