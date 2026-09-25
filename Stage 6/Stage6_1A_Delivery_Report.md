# Stage 6.1A Delivery Report

## Outcome

Stage 6.1A implements the immutable ingestion foundation as fixture-only infrastructure. It builds and verifies point-in-time Entity and Source Registry snapshots, stores exact raw fixture bytes content-addressably, records successful evidence and failed acquisition attempts, enforces deterministic idempotency, and independently re-verifies the complete append-only store after restart.

The Stage 6.1A.2 registry-store chain closure result is **PASS**: 152 of 152 Stage 6.1A acceptance and adversarial tests passed. This retains all 142 prior checks and adds 10 targeted persistent-chain checks. The unchanged Stage 6.0C architecture validator also passed, parsing all 10 frozen schemas.

## Frozen identities

- Architecture baseline: `stage6-decision-intelligence-architecture-baseline-v2`
- Architecture commit: `d5bc19c7c2341f56bcaa8c890e0d95979dca878b`
- Production control: `stage5d5-live-paper-runner-baseline`
- Production-control commit: `74b2710f0e19bd403978da81e87f25a3059ace06`
- Authority: `SHADOW_ONLY`

No frozen Stage 6 architecture file and no Stage 5D file was modified.

## Safety boundary

This stage contains **no live source connector**. All source and entity records are deliberately synthetic fixture data. No NSE, BSE, GDELT, Yahoo, broker, or other external request occurred. The package has no network acquisition implementation and its tests independently enforce both a prohibited-import scan and a socket sentinel.

Stage 6.1A has no production decision influence, BUY or SELL authority, stop or target authority, broker execution, or ML decision authority. Stage 5D.5 remains production control. Stage 6.1B—not this delivery—is the first planned official-source connector stage.

## Immutable foundation

- One canonical UTF-8 JSON and SHA-256 implementation is used for registries, evidence, idempotency inputs, and integrity checks.
- Registry snapshot IDs, registry hashes, record hashes, evidence IDs, and acquisition-attempt IDs are deterministic.
- Acquisition rejects any Source or Entity Registry snapshot whose `as_of_timestamp` is later than the evidence observation or failed-attempt cutoff.
- Registry chains enforce non-decreasing as-of chronology, record lineage, and review timestamps no later than their containing snapshot.
- Every registry kind persisted in the ingestion store must begin at V1 with a null predecessor, remain contiguous, and link each snapshot hash to its immediate predecessor; imports and full-store integrity both fail closed on orphaned or gapped chains.
- Runtime validation enforces the applicable frozen Entity Registry, Source Registry, and Evidence contract semantics without changing those contracts.
- Automated capture fails closed unless the source is enabled, verified, automation-allowed, and terms-reviewed as allowed.
- Capture verifies the complete persisted registry chain through the referenced snapshot rather than trusting a standalone later version.
- Historical ticker, alias, entity, and source resolution uses explicit effective periods.
- Registry and record version chains are verified without rewriting earlier snapshots.
- Exact raw bytes use the `STAGE6_1A_RAW_BYTES_CONTENT_HASH` rule and are installed atomically with no-clobber semantics; a concurrent winner is verified and never overwritten.
- Retrieval failures remain `ACQUISITION_ATTEMPT` records; they never become no-news, safe, or neutral evidence.
- SQLite triggers reject updates and deletes from immutable tables.
- A full restart-safe integrity check covers metadata, SQLite integrity, foreign keys, registry chains, canonical JSON, typed columns, raw bytes, evidence links, source/entity bindings, and idempotency coverage.

## Evidence

- Test results: `Stage 6/results/stage6_1a_test_results.csv`
- Machine-readable contract: `Stage 6/results/stage6_1a_contract.json`
- Offline demo: `python -m stage6_ingestion.run_fixture_demo` from the `Stage 6` directory

Runtime SQLite databases, WAL/SHM files, raw payload objects, temporary demo output, Python bytecode, and `__pycache__` directories are excluded by `Stage 6/.gitignore`.
