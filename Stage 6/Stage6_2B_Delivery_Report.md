# Stage 6.2B — Immutable RSS/Atom Item Extraction

## Delivery status

**PASS** — Stage 6.2B adds a deterministic, fixture-only, network-free extraction layer between immutable Stage 6.1 feed evidence and future event-candidate interpretation. Authority remains `SHADOW_ONLY`.

## Frozen identities

- Stage 6.2A: `stage6-2a-event-intelligence-foundation-baseline` at `850809db87b2d63380c532404ca8922bc8807a7b`
- Stage 6.1C: `stage6-1c-multisource-rss-ingestion-baseline` at `6046ea1bfcc13130581170c0d1a2ec50a1a2b2c5`
- Stage 6 architecture: `stage6-decision-intelligence-architecture-baseline-v2` at `d5bc19c7c2341f56bcaa8c890e0d95979dca878b`
- Stage 5D.5: `stage5d5-live-paper-runner-baseline` at `74b2710f0e19bd403978da81e87f25a3059ace06`
- Extraction schema: `STAGE6_RSS_ITEM_V1`
- Parser: `STAGE6_2B_RSS_ITEM_PARSER_V1`

## What Stage 6.2B does

- Reads immutable Stage 6.1 evidence for exactly `SEBI_OFFICIAL_RSS` and `RBI_OFFICIAL_PRESS_RELEASES_RSS`.
- Verifies the canonical evidence record, evidence hash, raw payload binding, and exact content-addressed raw bytes before parsing.
- Safely parses RSS `channel/item` and namespaced Atom `feed/entry` structures without dereferencing any resource.
- Persists one immutable derived extraction per publisher item, including a zero-based structural locator and deterministic extraction identity.
- Directly binds every extraction to its exact parent `(evidence_id, record_hash, EVIDENCE)`.
- Preserves XML-decoded publisher text without summarizing, translating, classifying, stemming, or semantic claim splitting. Only surrounding whitespace is removed; internal wording, punctuation, case, and spacing are retained.
- Preserves valid timezone-aware item timestamps as descriptive metadata. Missing or ambiguous timestamps remain null and never inherit feed or evidence timestamps.
- Preserves system availability separately as the parent evidence retrieval timestamp and enforces the explicit extraction cutoff.
- Stores derived field hashes and a canonical structural item fingerprint; neither is represented as a publisher raw-byte hash.
- Uses database triggers to prohibit updates and deletes and reruns the exact parser over the exact raw payload during restart integrity verification.
- Enforces 100-item, 100,000-character-per-field, and 1,000,000-total-character fail-closed limits with no silent truncation.

## What Stage 6.2B does not do

It does not create new `STAGE6_EVIDENCE_V2` envelopes, fetch item links, PDFs, HTML, redirects, images, enclosures, or external entities, classify events, infer entities, split semantic claims, infer sentiment/direction/severity/materiality/impact, create Stage 6 event records, call LLMs, use ML, rank stocks, make recommendations, trade, call brokers, or modify Stage 5D.

## Validation evidence

| Gate | Result |
|---|---:|
| Stage 6.1A regression | 152 PASS / 0 FAIL |
| Stage 6.1B regression | 68 PASS / 0 FAIL |
| Stage 6.1C regression | 86 PASS / 0 FAIL |
| Stage 6.2A regression | 75 PASS / 0 FAIL |
| Stage 6.2B acceptance/adversarial suite | 68 PASS / 0 FAIL |
| Stage 6.0C validator | PASS / 10 schemas |
| Network calls / linked-resource fetches | 0 / 0 |
| Evidence records / event records created | 0 / 0 |
| Parent verification, raw verification, PIT, parser replay | PASS |
| Frozen architecture / Stage 6.1 / Stage 6.2A / Stage 5D changes | 0 / 0 / 0 / 0 |
| Runtime artifacts committed | 0 |

Detailed evidence is in `results/stage6_2b_contract.json` and `results/stage6_2b_test_results.csv`.

## Deferred

Semantic claim splitting, event candidate classification, entity inference, NLP/LLM, sentiment, market causality, exposure mapping, linked-document acquisition, and all additional Event Intelligence functionality remain deferred. No freeze tag was created.
