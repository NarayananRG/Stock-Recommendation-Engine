# Stage 6.2C — Deterministic Event-Candidate Classification

## Delivery status

**PASS** — Stage 6.2C adds immutable, deterministic event-candidate classification over Stage 6.2B extracted RSS/Atom items. It remains zero-network and `SHADOW_ONLY`; a candidate is not a confirmed event.

## Frozen identities

- Stage 6.2B: `stage6-2b-rss-item-extraction-baseline` at `48a1f4f95e3a582abdf0c8d50bb1ead50474e2d4`
- Stage 6.2A: `stage6-2a-event-intelligence-foundation-baseline` at `850809db87b2d63380c532404ca8922bc8807a7b`
- Stage 6 architecture: `stage6-decision-intelligence-architecture-baseline-v2` at `d5bc19c7c2341f56bcaa8c890e0d95979dca878b`
- Stage 5D.5: `stage5d5-live-paper-runner-baseline` at `74b2710f0e19bd403978da81e87f25a3059ace06`
- Candidate schema: `STAGE6_EVENT_CANDIDATE_V1`
- Classifier: `STAGE6_2C_LITERAL_CLASSIFIER_V1`
- Ruleset: `S6RULESET_STAGE6_2C_V1`, version 1, hash `4f26c762384056f61fce0f5e77c3e907ba583f57d8aed52de21bc8cfe4138791`

## What Stage 6.2C does

- Consumes only immutable `STAGE6_RSS_ITEM_V1` records from complete Stage 6.2B extraction batches.
- Classifies every extracted item and produces exactly one immutable candidate record per item.
- Uses only the frozen three-rule deterministic literal ruleset: explicit RBI rate cut, explicit RBI rate hike, and explicit SEBI regulatory order.
- Produces only `MATCHED`, `NO_MATCH`, or `AMBIGUOUS` classification outcomes and preserves deterministic match traces, ambiguity, and no-match results.
- Uses NFKC normalization, Unicode case folding, non-alphanumeric separation, whitespace collapse, and complete token-sequence matching.
- Directly binds each candidate to the exact extraction ID/hash/type and exact ruleset ID/hash/type.
- Enforces point-in-time classification cutoffs while keeping candidate identity independent of cutoff, allowing later valid batches to reuse the same candidate records.
- Persists the exact canonical ruleset snapshot in a separate append-only SQLite candidate store.
- Replays extraction integrity and the exact classifier/ruleset during full restart integrity verification.
- Remains zero-network and `SHADOW_ONLY`.

## What Stage 6.2C does not do

It does not create Stage 6 events, evidence, or extraction records; fetch links, PDFs, or other resources; infer entities, direction, sentiment, severity, materiality, causality, confidence, or impact; map exposures; call LLMs; use ML; rank stocks; make recommendations; trade; call brokers; or modify Stage 5D.

## Validation evidence

| Gate | Result |
|---|---:|
| Stage 6.1A regression | 152 PASS / 0 FAIL |
| Stage 6.1B regression | 68 PASS / 0 FAIL |
| Stage 6.1C regression | 86 PASS / 0 FAIL |
| Stage 6.2A regression | 75 PASS / 0 FAIL |
| Stage 6.2B regression | 68 PASS / 0 FAIL |
| Stage 6.2C acceptance/adversarial suite | 61 PASS / 0 FAIL |
| Stage 6.0C validator | PASS / 10 schemas |
| Network calls / linked-resource fetches | 0 / 0 |
| Evidence / extraction / event writes | 0 / 0 / 0 |
| Candidate store, ruleset snapshot, dependency bindings | PASS |
| MATCHED / NO_MATCH / AMBIGUOUS semantics | PASS / PASS / PASS |
| Source isolation / token matching / PIT cutoff | PASS / PASS / PASS |
| Append-only protection / classifier replay / restart integrity | PASS / PASS / PASS |
| Frozen architecture / Stage 6.1 / Stage 6.2A / Stage 6.2B / Stage 5D changes | 0 / 0 / 0 / 0 / 0 |
| Runtime artifacts committed | 0 |

Detailed evidence is in `results/stage6_2c_contract.json` and `results/stage6_2c_test_results.csv`.

## Deferred

Candidate-to-event materialization, entity resolution from item text, corroboration across candidate items, semantic claim splitting, NLP/LLM, sentiment, direction, severity, materiality, confidence, market causality, exposure mapping, linked-document acquisition, and all additional Event Intelligence functionality remain deferred. No tag was created.
