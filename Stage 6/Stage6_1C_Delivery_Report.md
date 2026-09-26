# Stage 6.1C Delivery Report

## Outcome

Stage 6.1C is **PASS**. It evolves the frozen operational Entity and Source Registries from V1 to complete V2 snapshots, preserves the unchanged SEBI records and their hashes, and adds exactly one source family: `RBI_OFFICIAL_PRESS_RELEASES_RSS` at `https://rbi.org.in/pressreleases_rss.xml`.

The complete Stage 6.1A regression is **152/152 PASS**, the frozen-behaviour Stage 6.1B regression is **68/68 PASS**, and the new socket-free Stage 6.1C suite is **86/86 PASS**. The unchanged Stage 6.0C validator is **PASS** with 10 schemas parsed.

## Registry evolution and historical reproducibility

- Entity Registry V2 (`S6ENTREG_2aed0e083e1186bcade4ede9`) links exactly to operational Entity Registry V1 and contains the unchanged SEBI regulator plus new `RBI_REGULATOR_IN` record V1 with a null predecessor and no ticker mappings.
- Source Registry V2 (`S6SRCREG_39b7deae3a0e811e7327af2c`) links exactly to operational Source Registry V1 and contains the unchanged `SEBI_OFFICIAL_RSS` record plus new `RBI_OFFICIAL_PRESS_RELEASES_RSS` record V1 with a null predecessor.
- SEBI entity/source canonical records and record hashes are identical between V1 and V2.
- Evidence created under V1 remains bound to V1 and passes full integrity after both V2 snapshots are appended.
- New SEBI evidence can bind V2 while retaining the exact unchanged SEBI source-record identity.
- RBI fails closed with zero network calls against V1 because neither its source nor entity exists historically there.
- RBI succeeds under V2 and binds both registry version 2 snapshots and exact RBI source-record version 1.

## Controlled sources

Only these live endpoint policies exist:

- `SEBI_OFFICIAL_RSS` → `https://www.sebi.gov.in/sebirss.xml`
- `RBI_OFFICIAL_PRESS_RELEASES_RSS` → `https://rbi.org.in/pressreleases_rss.xml`

The official RBI RSS documentation at `https://www.rbi.org.in/Scripts/rss.aspx` was reviewed at `2026-09-26T06:49:51Z`. It describes RSS as automatic site updates and lists a distinct Press Releases feed. Approval is restricted to the exact RSS endpoint; it does not authorize linked-page or general RBI website scraping.

A controlled no-follow discovery request returned HTTP 200 and `text/xml` directly from `rbi.org.in` with no redirect. Consequently, `www.rbi.org.in`, wildcard subdomains, and all other RBI paths remain prohibited.

## Live validation

- SEBI regression: **PASS**, one request to `www.sebi.gov.in`, retrieved evidence `S6EV_68500dfb372b50b8279d4247`, raw SHA-256 `2120106ed900bca08637fb17223990cd97f0f128bba64cce99213bfaa539cb25`, restart integrity PASS.
- RBI smoke: **PASS**, one request to `rbi.org.in`, zero redirects, retrieved evidence `S6EV_25194dbd877a83a0adbaa981`, raw SHA-256 `0ccad2f0859e5481bf34499fdb14fe16c901f7bc73110dc78a0bb0fae269f8a0`, Entity/Source Registry V2, restart integrity PASS.
- Total Stage 6.1C validation network requests: three—one RBI redirect-discovery request and the two explicit smoke requests.

## What Stage 6.1C does

- Maintains frozen SEBI acquisition behaviour while adding the RBI Press Releases RSS feed.
- Uses immutable program-controlled source definitions and exact scheme/host/path allowlists.
- Validates complete registry chains, source approval, entity identity, and PIT cutoffs before transport.
- Preserves exact raw response bytes in the existing append-only content-addressed store.
- Keeps retrieved-but-invalid payloads as `QUARANTINED` evidence and no-payload failures as `ACQUISITION_ATTEMPT` records.
- Keeps source/entity identities isolated and retains deterministic idempotency.
- Remains `SHADOW_ONLY` with zero Stage 5D or production-decision influence.

## What Stage 6.1C does not do

It does not interpret announcements, classify events or sentiment, fetch RSS links/enclosures/PDFs, use conditional ETag/304 polling, schedule requests, rank securities, generate recommendations, change portfolios/stops/targets, call brokers, add NSE/BSE or any other source, run ML, or implement Stage 6.2.

Failure means acquisition failure only; it never means no announcement, no macro risk, neutral conditions, or a safe market.

## Evidence and deferred work

- Tests: `Stage 6/results/stage6_1c_test_results.csv`
- Contract: `Stage 6/results/stage6_1c_contract.json`
- Explicit RBI runner: `python -m stage6_connectors.run_rbi_rss --live`

Conditional polling/304 semantics, scheduling, linked-document acquisition, additional RBI feeds, event interpretation, and additional sources are deferred. Runtime databases, raw objects, caches, cookies, credentials, and session files are gitignored and are not part of this delivery.
