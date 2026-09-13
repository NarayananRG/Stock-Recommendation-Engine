# Stage 5D.1 — Personal Decision-Support Allocator

Stage 5D.1 converts deterministic BUY candidates into portfolio-aware proposed orders. It does not create signals, execute trades, record actual transactions, or use Stage 4A.3 ML scores.

## Frozen rules

- Capital enforcement uses the current market value of open positions. Cost basis is retained separately for reporting.
- Available capital is `max(0, capital ceiling - current position market value - reserved pending capital)`.
- Risk budget is `capital ceiling × 0.75%` per proposed trade.
- Position value is capped at `capital ceiling × 25%` per stock.
- A maximum of five open plus newly proposed positions is allowed.
- Quantities are whole shares; cash may remain unallocated.
- Reducing the ceiling below current exposure never forces a sale. It produces `OVER_NEW_CAP` and blocks new BUY proposals until exposure falls below the ceiling.

## Horizons

- `ONE_MONTH`: up to 21 market sessions. It requires candidate-level validated deterministic holding evidence; otherwise the candidate remains a watch item.
- `THREE_MONTHS`: up to 63 market sessions and compatible with the frozen deterministic strategy maximum.
- `SIX_MONTHS`: reserved for future work and returns `UNSUPPORTED_NOT_VALIDATED`.

Heuristic holding estimates are informational only and are never presented as calibrated probabilities.

## Profile history

`ProfileStore` writes one immutable JSON file per profile version. A later capital or horizon change creates a new version and leaves all earlier versions and recommendations unchanged. Recommendations contain both a stable `recommendation_id` and the `profile_version` used.

## Run tests

From the repository root:

```powershell
python "Stage 5D/tests/run_stage5d1_tests.py"
```

The test runner writes `results/stage5d1_test_results.csv` and `results/stage5d1_contract.json`.
