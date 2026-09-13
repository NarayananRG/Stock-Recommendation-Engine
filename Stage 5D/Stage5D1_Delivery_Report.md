# Stage 5D.1 Delivery Report

Branch: `stage5d-live-decision-support`

Base: `stage4a3-prospective-shadow-protocol-baseline` at `3ff3c0283174589d43883ce75b1dfd87a33613ce`

Stage 5D.1A hardens deterministic-source integration, allocation identity, portfolio commitments, horizon-policy mapping, and whole-share proposed allocations.

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
- Identity: `allocation_run_id` hashes the complete deterministic decision context; row IDs bind to the run, candidate identity, and stable ordinal. Unknown ML metadata is excluded.
- One month management policy: `STATIC_T2_20D`, 20 sessions, `FROZEN_STAGE2_2_2_STATIC_BASELINE`.
- Three months management policy: `D1_TRAIL_ONLY_63D`, 63 sessions, `FROZEN_STAGE2B_1_DYNAMIC_BASELINE`.
- Six months: `UNSUPPORTED_NOT_VALIDATED`.

Both supported mappings are historically tested deterministic policies, not prospective validation or profit guarantees. Stage 5D.1A records but does not execute the management policy.

## Declarations

Tests passed / failed: **51 / 0**

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
- `stage5d/allocator.py`
- `stage5d/recommendation_contract.py`
- `tests/run_stage5d1_tests.py`
- `results/stage5d1_test_results.csv`
- `results/stage5d1_contract.json`
- `Stage5D1_Delivery_Report.md`
