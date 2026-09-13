# Stage 5D.1 Delivery Report

Branch: `stage5d-live-decision-support`

Base: `stage4a3-prospective-shadow-protocol-baseline` at `3ff3c0283174589d43883ce75b1dfd87a33613ce`

Stage 5D.1C adds portable canonical frozen-source provenance verification to the completed Stage 5D.1B scanner-parity and lineage hardening. Recommendation contract semantics and allocator behavior are unchanged.

## Rules

- Actionable source signals: immutable `STRONG BUY` and `BUY` set. Other frozen signals retain their meaning, allow nullable trade levels, and receive zero proposed capital.
- Capital enforcement: current market value of open positions plus reserved pending-entry capital, with cost basis retained separately.
- Available capital: `max(0, ceiling - current market value - reserved pending capital)`.
- Risk sizing: `floor((capital ceiling × 0.0075) / (sizing entry price - stop))`.
- Position cap: `floor((capital ceiling × 0.25) / sizing entry price)`.
- Final quantity: the minimum whole-share quantity permitted by cash, risk, position cap, and the five-position limit.
- Cap reduction: never force-sells; `OVER_NEW_CAP` blocks new proposals until market exposure returns below the ceiling.
- Committed-capital overage: `OVER_COMMITTED_CAP` blocks new proposals without force-selling holdings or cancelling pending entries.
- Anti-pyramiding: existing tickers and later duplicate candidate tickers cannot receive proposed allocations.
- Pending entries: structured reservations determine reserved capital and block overlapping orders for the same ticker.
- Frozen priority: `STRONG BUY`, Actionability descending, Technical descending, R:R T1 descending, RS 60D descending, then ticker ascending. Caller Rank is ignored.
- Signal lineage: each row uses the frozen Stage 2.2.2 `STAGE_2_1_FROZEN` Signal-ID semantics; supplied conflicts fail the complete run.
- Session identity: dates canonicalize to `YYYY-MM-DD`; candidates must belong to one Signal Date; zero-candidate runs require an explicit decision date.
- Identity: `allocation_run_id` hashes the complete deterministic decision context, including structured pending reservations; row IDs bind to the run, Signal ID, candidate identity, and stable ordinal. Unknown ML metadata is excluded.
- One month management policy: `STATIC_T2_20D`, 20 sessions, `FROZEN_STAGE2_2_2_STATIC_BASELINE`.
- Three months management policy: `D1_TRAIL_ONLY_63D`, 63 sessions, `FROZEN_STAGE2B_1_DYNAMIC_BASELINE`.
- Six months: `UNSUPPORTED_NOT_VALIDATED`.

Both supported mappings are historically tested deterministic policies, not prospective validation or profit guarantees. Stage 5D.1B records but does not execute the management policy.

## Declarations

Tests passed / failed: **80 / 0**

Exact source ranking parity: **PASS**

Signal-ID parity against imported frozen Stage 2.2.2 function: **PASS**

Canonical Stage 2.2.2 source SHA: `63345c591b46c656b204236d147993cb283d57fdbccd0246b7cef281d7968730`

Artifact-manifest source SHA: `63345c591b46c656b204236d147993cb283d57fdbccd0246b7cef281d7968730`

Canonical source provenance: **PASS**

Canonical date identity: **PASS**

Single-session enforcement: **PASS**

Pending-ticker blocking: **PASS**

ML non-influence: **PASS**

Stage 4A.3 protected changes: **0**

ML used in user-facing selection: **NO**

Real-money execution implemented: **NO**

Persistent actual transaction ledger implemented: **NO**

Stage 5D.2 implemented: **NO**

## Files created

- `.gitignore`
- `README.md`
- `config/user_profile.example.json`
- `stage5d/__init__.py`
- `stage5d/user_profile.py`
- `stage5d/portfolio_state.py`
- `stage5d/horizon.py`
- `stage5d/source_contract.py`
- `stage5d/allocator.py`
- `stage5d/recommendation_contract.py`
- `tests/run_stage5d1_tests.py`
- `results/stage5d1_test_results.csv`
- `results/stage5d1_contract.json`
- `results/stage5d1_source_parity.json`
- `Stage5D1_Delivery_Report.md`
