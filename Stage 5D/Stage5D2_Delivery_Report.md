# Stage 5D.2 / 5D.2A Delivery Report

## Delivery identity

- Branch: `stage5d2-persistent-ledger`
- Verified Stage 5D.2A implementation commit: `9c9f29b6d0361d418e19eb7ab63faa5349431d86`
- Frozen Stage 5D.1 base tag: `stage5d1-portfolio-allocator-baseline`
- Frozen Stage 5D.1 base commit: `de3b80c5c494a11c1dde7b4abc39481a7493f108`
- Schema version: `STAGE5D2_SCHEMA_V1`

## Storage and integrity

- Database engine: SQLite through Python standard-library `sqlite3`
- File-backed journal mode: WAL
- Foreign-key enforcement: enabled on every connection
- Runtime database: `Stage 5D/data/stage5d.sqlite3` (Git-ignored, not committed)
- Money representation: canonical decimal strings; Python `Decimal` is used for authoritative calculations
- Immutable payload hashing: canonical sorted compact JSON, UTF-8, SHA-256
- Unknown or incomplete schema: fails loudly; no silent migration

Tables created:

1. `ledger_meta`
2. `allocation_runs`
3. `recommendations`
4. `recommendation_events`
5. `user_transactions`
6. `transaction_voids`
7. `opening_positions`
8. `position_state_snapshots`
9. `recommendation_outcome_versions`

## Behavioral contracts

- Immutable recommendations: an existing identity with identical canonical content is idempotent; conflicting content fails. No edit or delete API is provided.
- Allocation idempotency: an allocation run and all child recommendations are written atomically. Exact repeats return `IDEMPOTENT_SUCCESS`; conflicts fail.
- Transaction idempotency: exact repeats under the same idempotency key succeed without duplication; conflicting reuse fails.
- Transaction correction: the original transaction is retained and an append-only void excludes it from derived positions; a corrected transaction is appended separately.
- Position cost basis: `WEIGHTED_AVERAGE_NON_TAX_COST_BASIS`. This is explicitly not tax accounting.
- Pending reservations: `PENDING_ENTRY` reserves remaining quantity times reservation price basis; partial fills reduce the reservation; full fill, cancellation, or expiry removes it.
- Recommendation outcomes: append-only and strictly monotonic per recommendation. Exact duplicate versions are idempotent; conflicting versions fail.
- Standalone transaction durability: public transaction writes own an atomic SQLite transaction and survive immediate close/reopen.
- Fill atomicity: the private no-commit transaction insertion is used inside one outer transaction with the lifecycle event; either both persist or neither persists.
- Chronological replay safety: opening positions and non-void transactions share one deterministic stream ordered by effective date, same-day opening before transaction, then stable sequence.
- Retroactive safety: every new transaction is staged and the complete effective chronology is replayed before commit; any historical negative holding rolls back the write.
- Void chronology safety: a void is staged and complete history is replayed before commit. Unsafe BUY voids roll back, exact retries are idempotent, and a distinct second void is rejected.
- Recommendation linkage: a linked transaction must match recommendation ticker and Signal ID; omitted Signal ID is inherited from the recommendation.
- Pending lifecycle: custom reservation price basis survives partial fills; partial fills without prior pending intent create the remaining reservation; `DECLINED`, `CANCELLED`, `EXPIRED`, and `FILLED` are terminal.
- Typed-column integrity binding: all eight canonical evidence tables verify hashes and typed query columns against canonical payloads, identities, dates, quantities, money, and lineage.
- Allocation child consistency: stored counts, actionable counts, embedded recommendation evidence, IDs, hashes, and child rows must agree; missing child evidence fails integrity and idempotent re-persistence.
- Outcome input validation: only known fields, strict booleans, canonical entry dates, nonnegative integer session counts, finite decimals, and non-empty methodology versions are accepted.
- Recommendation, lifecycle intent, user execution, derived position state, and engine outcome remain separate entities.
- Current market prices are caller-supplied. No live-price download occurs.

## Verification

- Stage 5D.2/5D.2A tests: **103 PASS / 0 FAIL**
- Frozen Stage 5D.1 regression: **80 PASS / 0 FAIL**
- Standalone transaction reopen durability: **PASS**
- Backdated chronology safety: **PASS**
- Void chronology safety: **PASS**
- Recommendation linkage validation: **PASS**
- Pending reservation lifecycle: **PASS**
- Typed-column integrity binding: **PASS**
- Allocation child consistency: **PASS**
- Outcome validation: **PASS**
- Stage 4A.3 changed files: **0**
- Stage 2.2.2 changed files: **0**
- Stage 2B.1 changed files: **0**
- Frozen Stage 5D.1 allocator semantic files changed: **0**
- Runtime SQLite databases tracked by Git: **0**
- ML user-facing influence: **NO**
- Broker integration: **NO**
- Automatic trade execution: **NO**
- Stage 5D.3 daily position monitor implemented: **NO**

Stage 5D.2A hardening is complete and stops here for the final independent Stage 5D.2 freeze audit.
