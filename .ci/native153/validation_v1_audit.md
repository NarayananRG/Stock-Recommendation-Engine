# Validation V1 Audit — basis for 0.14.12 Validation V2

Base: 0.14.11 accepted commit `646c2c8bd0a3c93ed1741f570ce6df248365e5dd`

## Confirmed defects

1. Historical replay is not a genuine historical LIVE_DECISION_V1 replay.
   - The Phase 8.1 implementation uses current production rows only when `session == current_session`.
   - Other sessions receive an empty row set and are classified as PIT incomplete.
   - Portfolio/benchmark metrics can therefore look like performance outputs without a continuous historical decision portfolio.
   - The benchmark path can use a flat starting-capital series rather than actual NIFTY closes.

2. Legacy paper state can contradict the current production engine.
   - The SQLite ledger persists across upgrades.
   - Older DAILY_DECISION entries remain after evidence/model pipeline versions change.
   - Reinstalling does not create a clean prospective cohort.
   - A current BUY can coexist with an older same-date CASH / NO EXECUTABLE BUY journal entry.

3. The old Paper Portfolio has no explicit portfolio-generation/version boundary in the UI.
   - Users cannot clearly distinguish old validation cohorts from a newly started cohort.
   - A new clean forward test needs a new portfolio id and immutable start-run identity.

4. Historical sessions must never reuse current fundamentals or current recommendation rows.
   - Every historical decision must be reconstructed from data available by the historical cutoff.
   - Unreconstructable sessions must be labelled NOT_REPLAYABLE rather than treated as zero-return/no-trade days.

5. Validation must not modify production authority.
   - LIVE_DECISION_V1 remains the only production action authority.
   - Validation consumes frozen production decisions or reconstructs them point-in-time.
   - Validation never changes thresholds, model weights, provider policy, or BUY/WATCH/AVOID rules.

## V2 architecture

- New module: `stock_app/validation_v2.py`
- New SQLite schema/version and table names prefixed `v2_`.
- Legacy Phase 8.1 tables remain untouched and read-only.
- Every V2 portfolio stores:
  - portfolio_id
  - start session
  - start production run id
  - app/model/evidence version
  - starting capital
- Every journal/order stores exact session/run/version provenance.
- Same portfolio/session/run operation is idempotent.
- BUY signal -> PENDING_NEXT_OPEN -> next official open fill.
- EXIT signal -> PENDING_EXIT_NEXT_OPEN -> next official open fill.
- Mark-to-market only from accepted official session close.
- Missing current mark is STALE_MARK, never silently current.
- Historical Replay V2 reconstructs session evidence at its own cutoff and maintains one continuous cash/position/NAV state.
- Historical performance metrics are emitted only for truly replayable windows.
- Benchmark must use actual NIFTY session closes; no flat placeholder benchmark.

## Release acceptance

0.14.12 is not complete until deterministic state-transition tests, PIT anti-lookahead tests,
real browser tests, Windows installer install/reopen, and full existing regression suites are green.
