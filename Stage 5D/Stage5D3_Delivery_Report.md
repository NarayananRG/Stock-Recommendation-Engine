# Stage 5D.3 Delivery Report

- Branch: `stage5d3-daily-position-monitor`
- Commit SHA: the immutable pushed branch-head SHA is reported at delivery (a commit cannot embed its own SHA)
- Base tag: `stage5d2-persistent-ledger-baseline`
- Base commit: `9c688cfe5aa6e9b87154a5661d92885505431235`
- Stage 5D.3 schema: `STAGE5D3_SCHEMA_V1`

## Storage

Stage 5D.3 uses the same SQLite database as Stage 5D.2 without changing any Stage 5D.2 table or its `STAGE5D2_SCHEMA_V1` marker. It adds these owned tables:

- `stage5d3_meta`
- `management_session_runs`
- `management_episodes`
- `daily_market_observations`
- `management_state_versions`

Historical observations, episode identities, daily states, and session runs are immutable and content-hashed. Processing a completed session is atomic. Exact reruns are idempotent; conflicting evidence and earlier-session backfills fail loudly.

## Policy and operational results

| Gate | Result |
|---|---|
| `STATIC_T2_20D` frozen-source parity | PASS |
| `D1_TRAIL_ONLY_63D` frozen-source parity | PASS |
| Stop-first collision semantics | PASS |
| 20-session management | PASS |
| 63-session management | PASS |
| Next-session stop effectiveness | PASS |
| Entry-bar live limitation documented | PASS |
| Sticky exit behavior | PASS |
| Management/transaction separation | PASS |
| Reconciliation detection | PASS |
| Persistence and reopen | PASS |

The live ledger does not contain trustworthy intraday fill ordering. Therefore, an actual user's entry-day full OHLC bar cannot be used to fabricate a same-day stop or target outcome. The entry session counts as bar 1 and is recorded as `ENTRY_BAR_EXECUTION_ORDER_UNRESOLVED`; a D1 after-close trail may still be proposed for the next available processed market session. Synthetic execution contexts exist only in tests to prove frozen research parity.

An exit trigger is strategy evidence, not a user transaction. Stage 5D.3 never writes an automatic `SELL`. A trigger remains `EXIT_TRIGGERED_AWAITING_USER_ACTION`; subsequent sessions remain overdue until recommendation-linked, non-void user sells close the managed quantity. Partial user exits leave the remainder awaiting action.

## Validation

| Suite | Result |
|---|---|
| Stage 5D.3 | PASS — 97/97 |
| Frozen Stage 5D.2 | PASS — 129/129 |
| Frozen Stage 5D.1 | PASS — 80/80 |

Frozen-scope audit:

- Stage 4A.3 changes: 0
- Stage 2.2.2 changes: 0
- Stage 2B.1 changes: 0
- Frozen Stage 5D.1 semantic changes: 0
- Frozen Stage 5D.2 ledger changes: 0

## Explicit exclusions

- ML user-facing influence: NO
- News influence: NO
- Broker integration: NO
- Automatic trade execution: NO
- Intraday monitoring: NO
- Live-data downloading: NO
- Tax accounting replacement: NO

This is deterministic decision-support and research software, not investment advice and not an execution system.
