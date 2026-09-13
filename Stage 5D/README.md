# Stage 5D.1 — Personal Decision-Support Allocator

Stage 5D.1A converts deterministic `STRONG BUY` and `BUY` candidates into portfolio-aware proposed orders. It does not create signals, execute trades, record actual transactions, or use Stage 4A.3 ML scores.

## Frozen rules

- Capital enforcement uses the current market value of open positions plus reserved pending-entry capital. Cost basis is retained separately for reporting.
- Available capital is `max(0, capital ceiling - current position market value - reserved pending capital)`.
- Risk budget is `capital ceiling × 0.75%` per proposed trade.
- Position value is capped at `capital ceiling × 25%` per stock.
- A maximum of five open plus newly proposed positions is allowed.
- Quantities are whole shares; cash may remain unallocated.
- Reducing the ceiling below current exposure never forces a sale. It produces `OVER_NEW_CAP` and blocks new proposals until exposure falls below the ceiling.
- A committed-capital overage caused by existing positions plus reserved pending orders produces `OVER_COMMITTED_CAP`; Stage 5D.1A reports and blocks without cancelling orders.
- Existing tickers and later duplicate candidate tickers cannot receive a proposed allocation. Stage 5D.1A does not pyramid or average into holdings.
- Non-actionable frozen signals retain their source meaning, allocate zero shares, and may carry nullable trade levels.

## Horizons

- `ONE_MONTH`: `STATIC_T2_20D`, 20 sessions, sourced from the frozen Stage 2.2.2 static baseline.
- `THREE_MONTHS`: `D1_TRAIL_ONLY_63D`, 63 sessions, sourced from the frozen Stage 2B.1 dynamic baseline.
- `SIX_MONTHS`: reserved for future work and returns `UNSUPPORTED_NOT_VALIDATED`.

Candidate-supplied holding-session or evidence assertions are ignored. These management policies are historically tested deterministic mappings, not prospective validation or profit guarantees. Stage 5D.1A records the selected policy; a later daily-position monitor must enforce it.

## Profile history

`ProfileStore` writes one immutable JSON file per profile version. A later capital or horizon change creates a new version and leaves all earlier versions and recommendations unchanged. Each allocation has a deterministic, content-addressed `allocation_run_id`; each row has a context-bound `recommendation_id`. Unknown ML metadata is excluded from both identities.

## Source adapter

`normalize_source_candidate` explicitly accepts both Stage 5D snake-case fields and frozen source-style fields such as `Signal`, `Entry Low`, `Entry High`, `Stop Loss`, `Target 1`, and `Target 2`. The actionable set is immutable: `STRONG BUY` and `BUY`.

## Run tests

From the repository root:

```powershell
python "Stage 5D/tests/run_stage5d1_tests.py"
```

The test runner writes `results/stage5d1_test_results.csv` and `results/stage5d1_contract.json`.
