# Stage 6.3A — Point-in-Time Exposure Record Foundation

## Result

PASS. Stage 6.3A implements the frozen `STAGE6_EXPOSURE_V2` contract as an additive, fixture-only, immutable exposure store with `SHADOW_ONLY` authority.

The exposure identity is derived only from `company_entity_id`. Each company therefore has one stable exposure series and an append-only, contiguous version history. Version 1 has no predecessor; every later version binds the exact prior record hash. Exact canonical replays are idempotent, while conflicting versions fail closed.

## What Stage 6.3A does

- Implements the frozen `STAGE6_EXPOSURE_V2` record without modifying its schema.
- Creates immutable exposure series per company and appends exposure versions.
- Binds the exact persisted entity-registry snapshot ID, version, and hash.
- Resolves company, sector, optional subsector, and explicit relationships point-in-time.
- Stores explicit quantitative and qualitative assertions supplied by the caller.
- Requires finite quantitative values, approved units, and a non-empty explicit basis.
- Treats qualitative values as labels only; no numeric mapping exists.
- Requires assertion and relationship confidence to be exactly `0.0`. This is a conservative uncalibrated placeholder, not a statement that an exposure is false.
- Enforces assertion and relationship effective/review periods.
- Binds each claim to retrieved, sufficiently authoritative, immutable evidence available by the data cutoff.
- Persists direct ID/hash/type dependencies for evidence and the entity-registry snapshot.
- Protects metadata, series, records, and dependencies from UPDATE and DELETE.
- Replays every stored record deterministically during full integrity checks.
- Remains `SHADOW_ONLY`.

## What Stage 6.3A does not do

- It does not consume Event V3 or any Stage 6.2 event product for mapping.
- It does not automatically map events to companies.
- It does not infer beneficiaries, losers, direction, magnitude, materiality, expected return, or event impact.
- It does not parse documents, extract numbers, use OCR, NLP, LLMs, ML, embeddings, or semantic similarity.
- It does not fetch filings or call any network source.
- It does not score qualitative exposure.
- It does not rank, recommend, size positions, mutate portfolios, call brokers, or trade.
- It has no influence on Stage 5D production decisions.

## Validation evidence

| Suite | Result |
|---|---:|
| Stage 6.1A | 152/152 PASS |
| Stage 6.1B | 68/68 PASS |
| Stage 6.1C | 86/86 PASS |
| Stage 6.2A | 75/75 PASS |
| Stage 6.2B | 68/68 PASS |
| Stage 6.2C | 61/61 PASS |
| Stage 6.2D | 57/57 PASS |
| Stage 6.2E | 57/57 PASS |
| Stage 6.2F | 66/66 PASS |
| Stage 6.3A | 39/39 PASS |
| Stage 6.0C architecture validator | PASS; 10 schemas parsed |

The Stage 6.3A suite covers stable identity, contiguous versioning, exact registry and evidence binding, PIT cutoffs, company/sector/subsector resolution, assertion and relationship contracts, units and basis, confidence placeholder behavior, effective periods, evidence coverage, canonical ordering, append-only triggers, dependency integrity, deterministic replay, tamper detection, zero-network execution, and frozen-boundary checks.

## Boundaries

- Frozen architecture changed files: 0
- Frozen Stage 6.1 changed files: 0
- Frozen Stage 6.2A–6.2F changed files: 0
- Frozen Stage 5D changed files: 0
- Network calls: 0
- LLM calls: 0
- ML: false
- NLP: false
- Trading authority: 0
- Runtime database/raw artifacts committed: 0
- Tag created: none

## Deferred

Event-to-exposure mapping, automatic company impact propagation, sector/macro/commodity/currency/rate/geography transmission, exposure confidence calibration, document extraction, NLP/LLM analysis, market reaction, historical analogues, and portfolio influence are explicitly deferred.
