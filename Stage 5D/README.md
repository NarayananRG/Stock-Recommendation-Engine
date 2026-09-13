# Stage 5D.1 — Personal Decision-Support Allocator

Stage 5D.1B accepts real frozen scanner rows and converts deterministic `STRONG BUY` and `BUY` candidates into portfolio-aware proposed orders. It does not create strategy signals, execute trades, record actual transactions, or use Stage 4A.3 ML scores.

## Frozen rules

- Capital enforcement uses the current market value of open positions plus reserved pending-entry capital. Cost basis is retained separately for reporting.
- Available capital is `max(0, capital ceiling - current position market value - reserved pending capital)`.
- Risk budget is `capital ceiling × 0.75%` per proposed trade.
- Position value is capped at `capital ceiling × 25%` per stock.
- A maximum of five open plus newly proposed positions is allowed.
- Quantities are whole shares; cash may remain unallocated.
- Reducing the ceiling below current exposure never forces a sale. It produces `OVER_NEW_CAP` and blocks new proposals until exposure falls below the ceiling.
- A committed-capital overage caused by existing positions plus reserved pending orders produces `OVER_COMMITTED_CAP`; Stage 5D.1A reports and blocks without cancelling orders.
- Existing tickers and later duplicate candidate tickers cannot receive a proposed allocation. Stage 5D.1B does not pyramid or average into holdings.
- Structured pending-entry reservations supply both committed capital and ticker context. A matching candidate receives `BLOCKED_PENDING_ENTRY`.
- Non-actionable frozen signals retain their source meaning, allocate zero shares, and may carry nullable trade levels.

## Horizons

- `ONE_MONTH`: `STATIC_T2_20D`, 20 sessions, sourced from the frozen Stage 2.2.2 static baseline.
- `THREE_MONTHS`: `D1_TRAIL_ONLY_63D`, 63 sessions, sourced from the frozen Stage 2B.1 dynamic baseline.
- `SIX_MONTHS`: reserved for future work and returns `UNSUPPORTED_NOT_VALIDATED`.

Candidate-supplied holding-session or evidence assertions are ignored. These management policies are historically tested deterministic mappings, not prospective validation or profit guarantees. Stage 5D.1B records the selected policy; a later daily-position monitor must enforce it.

## Profile history

`ProfileStore` writes one immutable JSON file per profile version. A later capital or horizon change creates a new version and leaves all earlier versions and recommendations unchanged. Each allocation has a deterministic, content-addressed `allocation_run_id`; each row has a context-bound `recommendation_id`. Structured pending reservations are included in run identity. Unknown ML metadata and caller-supplied Rank fields are excluded.

## Source adapter

`normalize_source_candidate` explicitly accepts Stage 5D snake-case fields and the full frozen scanner field set. Signal dates and decision dates canonicalize to `YYYY-MM-DD`; a run contains exactly one signal session. Zero-candidate runs require an explicit decision date.

Every row receives a Signal ID derived with the frozen `STAGE_2_1_FROZEN` payload contract. A conflicting supplied Signal ID fails the run. Actionable rows require finite Actionability Score, Technical Score, R:R T1, RS 60D, entry, stop, and target data before any allocation is proposed.

## Frozen priority

Capital priority is calculated directly and never accepts caller rank overrides:

1. `STRONG BUY` before `BUY`
2. Actionability Score descending
3. Technical Score descending
4. R:R T1 descending
5. RS 60D descending
6. Ticker ascending

## Run tests

From the repository root:

```powershell
python "Stage 5D/tests/run_stage5d1_tests.py"
```

The test runner writes `results/stage5d1_test_results.csv` and `results/stage5d1_contract.json`.
