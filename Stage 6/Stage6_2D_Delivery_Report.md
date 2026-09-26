# Stage 6.2D — Deterministic Candidate-to-Event Materialization

## Delivery status

**PASS** — Stage 6.2D deterministically materializes eligible Stage 6.2C candidates into immutable `STAGE6_EVENT_V1` records through the frozen EventStore. Authority remains `SHADOW_ONLY`.

## Frozen identities

- Stage 6.2C: `stage6-2c-event-candidate-classification-baseline` at `5f1955aa83b02dfbd2bac28916cf64d55e3853c1`
- Stage 6.2B: `stage6-2b-rss-item-extraction-baseline` at `48a1f4f95e3a582abdf0c8d50bb1ead50474e2d4`
- Stage 6.2A: `stage6-2a-event-intelligence-foundation-baseline` at `850809db87b2d63380c532404ca8922bc8807a7b`
- Stage 6 architecture: `stage6-decision-intelligence-architecture-baseline-v2` at `d5bc19c7c2341f56bcaa8c890e0d95979dca878b`
- Stage 5D.5: `stage5d5-live-paper-runner-baseline` at `74b2710f0e19bd403978da81e87f25a3059ace06`
- Materialization schema: `STAGE6_EVENT_MATERIALIZATION_V1`
- Materializer: `STAGE6_2D_EVENT_MATERIALIZER_V1`
- Policy: `S6MATPOL_STAGE6_2D_V1`, version 1, hash `cabf548504dc5e592f3654a0a6cbc2575c7ce8821fb33f41079075e93aa952ca`

## What Stage 6.2D does

- Consumes complete immutable Stage 6.2C classification batches.
- Records exactly one immutable materialization decision for every candidate.
- Materializes only unambiguous `MATCHED` candidates; preserves `NO_MATCH` as `SKIPPED_NO_MATCH` and `AMBIGUOUS` as `SKIPPED_AMBIGUOUS`.
- Creates only EventStore version-1 events using the exact candidate event type and conservative defaults.
- Uses `CANDIDATE`, `UNKNOWN` direction/severity/materiality/horizon, empty entity/exposure fields, and `NO_SUPPORTED_CAUSE_FOUND`.
- Uses `confidence = 0.0` only as a conservative schema placeholder—not a probability or calibrated confidence estimate.
- Binds exact candidate, classification batch, materialization policy, EventStore event version, and source evidence identities and hashes.
- Uses the exact parent evidence retrieval time as event first-known time and the materialization cutoff as event last-updated time.
- Uses the parent evidence Entity Registry snapshot while leaving `entities` empty.
- Preserves both classification and materialization cutoffs for leakage-safe availability semantics.
- Uses deterministic event series keys and separate events per candidate, without cross-candidate merging.
- Recovers safely when EventStore append succeeds before materialization-store persistence and detects orphan Stage 6.2D event series.
- Replays candidate lineage, policy, materialization decisions, and events during full restart integrity checking.
- Remains zero-network and `SHADOW_ONLY`.

## What Stage 6.2D does not do

It does not infer entities, direction, severity, materiality, confidence, or causality; map exposures; merge or corroborate candidate events; create event V2/V3; resolve or retract events; use NLP, LLMs, ML, embeddings, or sentiment; fetch links or documents; rank stocks; make recommendations; trade; call brokers; or modify Stage 5D.

## Validation evidence

| Gate | Result |
|---|---:|
| Stage 6.1A regression | 152 PASS / 0 FAIL |
| Stage 6.1B regression | 68 PASS / 0 FAIL |
| Stage 6.1C regression | 86 PASS / 0 FAIL |
| Stage 6.2A regression | 75 PASS / 0 FAIL |
| Stage 6.2B regression | 68 PASS / 0 FAIL |
| Stage 6.2C regression | 61 PASS / 0 FAIL |
| Stage 6.2D acceptance/adversarial suite | 57 PASS / 0 FAIL |
| Stage 6.0C validator | PASS / 10 schemas |
| Network calls / linked-resource fetches | 0 / 0 |
| Evidence / extraction / candidate writes | 0 / 0 / 0 |
| Event V1 / NO_MATCH skip / AMBIGUOUS skip | PASS / PASS / PASS |
| Candidate / batch / policy / event / evidence binding | PASS |
| PIT / conservative defaults / V1-only boundary | PASS / PASS / PASS |
| Cross-store recovery / orphan detection | PASS / PASS |
| Append-only protection / deterministic replay / restart integrity | PASS / PASS / PASS |
| Frozen architecture / Stage 6.1 / 6.2A / 6.2B / 6.2C / Stage 5D changes | 0 / 0 / 0 / 0 / 0 / 0 |
| Runtime artifacts committed | 0 |

Detailed evidence is in `results/stage6_2d_contract.json` and `results/stage6_2d_test_results.csv`.

## Deferred

Event V2 evolution, cross-candidate event identity, cross-source corroboration, conflict resolution from real candidate streams, entity inference, direction, severity, materiality, confidence, historical context, market causality, exposure mapping, linked-document acquisition, NLP/LLM, and all additional Event Intelligence functionality remain deferred. No tag was created.
