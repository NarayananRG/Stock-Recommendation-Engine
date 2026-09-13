# Stage 5D.1 Delivery Report

Branch: `stage5d-live-decision-support`

Base: `stage4a3-prospective-shadow-protocol-baseline` at `3ff3c0283174589d43883ce75b1dfd87a33613ce`

Stage 5D.1 provides versioned user profiles, current-market-value portfolio accounting, deterministic horizon eligibility, and whole-share risk-aware proposed allocations.

## Rules

- Capital enforcement: current market value of open positions, with cost basis retained separately.
- Available capital: `max(0, ceiling - current market value - reserved pending capital)`.
- Risk sizing: `floor((capital ceiling × 0.0075) / (sizing entry price - stop))`.
- Position cap: `floor((capital ceiling × 0.25) / sizing entry price)`.
- Final quantity: the minimum whole-share quantity permitted by cash, risk, position cap, and the five-position limit.
- Cap reduction: never force-sells; `OVER_NEW_CAP` blocks new proposals until market exposure returns below the ceiling.
- One month: 21 sessions and requires validated candidate-level deterministic holding evidence.
- Three months: 63 sessions, matching the frozen deterministic strategy maximum.
- Six months: `UNSUPPORTED_NOT_VALIDATED`.

## Declarations

Tests passed / failed: **24 / 0**

Stage 4A.3 protected changes: **0 required**

ML used in user-facing selection: **NO**

Real-money execution implemented: **NO**

Persistent actual transaction ledger implemented: **NO — next stage**

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
