# Validation V1 Audit

Audited production base: `dbed4c56b6264f86a34167f14d7b3e278b334a43` (0.14.10)

Audited object: the final packaged engine reconstructed in workflow order through native151. The audit covered `stock_app/phase81_validation.py`, all Phase 8.1 overlays, LIVE_DECISION_V1 integration, API routes, post-close integration, SQLite state, and the Validation frontend.

## Conclusion

Validation V1 is not suitable for performance claims. Its paper ledger is not safely separated by lifecycle/version, and its historical replay is a current-session snapshot viewer with fabricated flat portfolio and benchmark series. V1 data is preserved as `LEGACY_VALIDATION_V1`, read-only, and excluded from V2 performance.

## Historical Replay defects

1. `phase81_historical_replay` supplies real decision rows only when `session == current_session`; every earlier session receives an empty row list.
2. It does not reconstruct technical, fundamental, valuation, or universe evidence at each historical cutoff.
3. It does not run LIVE_DECISION_V1 for historical sessions.
4. It does not maintain a continuous historical cash/order/position state.
5. It creates no historical fills or exits and passes an empty trade list to metrics.
6. `session_summary` assigns starting capital as portfolio NAV on every session, irrespective of trades or marks.
7. Benchmark NAV is hard-coded to the same flat starting-capital series; no NIFTY 50 history is read.
8. Returns, excess return, drawdown, win rate, average trade values, exposure, and BUY frequency are emitted as numeric zero when evidence is absent. These values are indistinguishable from genuine zero performance.
9. `capital_deployed` and `cash_retained` are per-session summaries, not continuous portfolio accounting.
10. Session discovery scans dates from filesystem path names rather than deriving an accepted official trading calendar.
11. The requested 6M label can be shown even when only one session is replayable.
12. The replay identifier is deterministic for period/config/version and `insert or replace` overwrites earlier results with the same key.
13. No actual benchmark completeness gate exists, so excess-return metrics remain visible with invalid benchmark evidence.
14. The V1 PIT status name (`PIT_VALID_WITH_MISSING_OPTIONAL_DATA`) does not match the required coverage contract (`PIT_VALID_WITH_OPTIONAL_GAPS`).
15. No per-session coverage table records market, fundamental, valuation, universe, router-run, and replayability statuses.
16. No explicit survivorship-bias classification is emitted for use of the current universe.
17. No cache key contract prevents future evidence from entering an earlier cutoff.

## Paper Portfolio defects

1. `load_portfolio()` silently selects the most recently created V1 portfolio and presents it as active; there is no explicit active/previous lifecycle.
2. Portfolio IDs are derived only from starting session and capital. Starting again with the same values silently reuses the old ledger.
3. Existing V1 ledgers can survive upgrades and coexist with contradictory newer production decisions.
4. A new start does not bind the portfolio to a starting production run ID, app version, evidence pipeline version, or router hash.
5. The `schema_meta` row is overwritten on each connection and does not provide a safe V1-to-V2 migration boundary.
6. V1 and new records share the same tables; there is no structural barrier against accidental promotion.
7. Official-data acceptance is represented by a broad `gate.ready` check rather than an auditable expected-session/latest-session/freshness triple stored with the decision.
8. Paper decisions do not persist app version and evidence pipeline version on every journal event.
9. Orders persist only a partial thesis and do not persist a stable evidence snapshot/hash contract.
10. Fill journal event names are vague (`FILLED`, `CLOSED`, `HELD`) instead of explicit `BUY FILLED`, `EXIT FILLED`, and `HOLD`.
11. Position fields use legacy names (`entry_signal_date`, `entry_fill_date`, `last_valuation_session`) and do not expose the required mark and thesis-health contract consistently.
12. Realized P&L is written to a closed position/event but is not accumulated into portfolio `state.realized_pnl`.
13. Daily mark-to-market updates only positions that appear in the recommendation row set. Missing rows leave stale values, while the V1 UI does not identify each stale mark.
14. Portfolio NAV history can be written before held positions are marked, making same-session journal and NAV semantics inconsistent.
15. The session duplicate guard ignores production run ID but returns the earliest decision event without proving that fills, marks, and monitoring were committed as one session transaction.
16. The journal canonicalizer hides duplicate V1 rows in the UI instead of exposing their provenance.
17. Closed positions are returned together with current positions; the V1 UI counts and renders the full list as current holdings.
18. The V1 UI does not display portfolio ID, starting production run, engine version, evidence version, current mark session, thesis health, pending capital, or read-only previous portfolios.
19. No confirmation is required before starting/reusing a paper ledger.
20. There is no crash-injection test proving rollback after a fill journal write.

## Integration and UI defects

1. Opening Validation automatically runs the misleading historical replay and immediately renders fabricated numeric metrics.
2. Missing metrics are formatted as zero via `value || 0`.
3. No portfolio-vs-NIFTY series chart exists.
4. No execution-assumption disclosure is prominent in the replay result.
5. No trustworthy requested-range versus replayable-range disclosure exists.
6. Post-close duplicate execution calls paper processing again; safety depends on scattered per-event keys rather than a single atomic session commit.
7. Validation logic is spread across string overlays, which makes the packaged implementation difficult to reason about and susceptible to later overrides.

## V2 disposition

- All V1 tables remain untouched and readable.
- V1 portfolios are classified `LEGACY_VALIDATION_V1`, read-only, and excluded from V2 performance.
- V2 uses separate versioned tables, one explicit active portfolio, atomic session commits, deterministic idempotency keys, immutable run/evidence provenance, next-open execution, actual marks, and evidence-gated replay metrics.
- `stock_app/live_decision_v1.py` SHA-256 before and after V2 integration is asserted identical.
