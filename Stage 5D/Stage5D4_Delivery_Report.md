# Stage 5D.4 Delivery Report

- Branch: `stage5d4-news-ml-shadow`
- Commit SHA: the immutable pushed branch-head SHA is reported at delivery
- Frozen base tag: `stage5d3-daily-position-monitor-baseline`
- Frozen base commit: `edf48ec2d606b290faab23fae0139d702846f808`
- Stage 5D.4 schema: `STAGE5D4_SCHEMA_V2`

## Scope

Stage 5D.4 adds an immutable decision-overlay layer to the existing Stage 5D SQLite evidence database. It does not modify the frozen allocator, ledger, daily-position monitor, Stage 4A.3 protocol, or any frozen strategy source.

The new owned tables are:

- `stage5d4_meta`
- `stage5d4_news_events`
- `stage5d4_ml_predictions`
- `stage5d4_decision_overlays`

No Stage 5D.2 or Stage 5D.3 schema table was changed.

## Acceptance results

| Gate | Result |
|---|---|
| News overlay | PASS |
| NEWS_PUBLISHED_CUTOFF | PASS |
| NEWS_OBSERVED_CUTOFF | PASS |
| OBSERVED_TIMESTAMP_REQUIRED | PASS |
| Positive-news no-upgrade | PASS |
| Material adverse downgrade | PASS |
| Conservative multiple-event aggregation | PASS |
| Immutable news replay/conflict handling | PASS |
| REAL_STAGE4A3_SNAPSHOT_BINDING | PASS |
| R3_K1_PRIMARY_POLICY_BINDING | PASS |
| R0_K1_COMPARATOR_BINDING | PASS |
| NO_INVENTED_ML_THRESHOLDS | PASS |
| ML_PRODUCTION_INFLUENCE | NO |
| MISSING_VERIFIED_ML_PREDICTION_HANDLED | PASS |
| TYPED_PAYLOAD_INTEGRITY | PASS |
| Model refit | NO |
| Model training | NO |
| Historical ML backfill | NO |
| R0/R1/R2/R3 evidence stored | YES |
| Performance-peeking report | NO |
| Broker integration | NO |
| Automatic execution | NO |
| UI | NO |

## Decision semantics

The official paper decision is the frozen deterministic recommendation plus a conservative news/event risk overlay. Positive news remains visible as supportive context but cannot create or strengthen a BUY. Material MEDIUM adverse evidence produces `REVIEW`; HIGH or CRITICAL adverse evidence produces `WAIT` for BUY candidates. For an existing HOLD, the corresponding severe state is `RISK_HOLD`.

Every included article must explicitly provide both a timezone-aware publication timestamp and a timezone-aware observation timestamp at or before `decision_cutoff_utc`. A missing `observed_at_utc` is rejected and is never inferred from publication time. An article first observed after a historical cutoff remains immutable evidence but cannot influence that historical overlay. The persisted overlay retains event IDs, headlines, sources, timestamps, categories, severities, materiality, deterministic reason codes, and immutable hashes.

ML evidence is accepted only through the Stage 5D-owned read-only snapshot adapter. The adapter loads the real seven-file Stage 4A.3 prospective snapshot, invokes the frozen verification utilities, checks the manifest file hashes and byte counts, recomputes the content and chain hashes, binds the exact protocol commit and model bundle, requires one Signal ID match, validates signal date and ticker lineage, and rejects snapshots created after the decision cutoff.

The stored shadow evidence uses the frozen policies exactly: `R3_K1` is primary and `R0_K1` is the comparator. Scores, same-date ranks, and K1 selections are retained without calling the scores calibrated probabilities. `R3_K1_SELECTED`, `R3_K1_NOT_SELECTED`, and `ML_NOT_AVAILABLE` are display states only. The former generic 0.60/0.40 thresholds and caller-supplied prediction dictionaries have been removed. `ml_influence` is always `NONE`.

After full snapshot verification, zero matching Signal ID rows is handled as `ML_NOT_AVAILABLE` without creating an ML prediction record or changing the official action. Duplicate matching rows and every integrity, identity, lineage, ticker, and future-created-snapshot failure remain hard failures.

Integrity checks now include SQLite `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, typed-column-to-canonical-payload binding for all three Stage 5D.4 evidence tables, official-action binding, ML snapshot/rank/selection binding, and both news cutoffs.

## Research views

- R0: frozen deterministic action
- R1: deterministic action plus news overlay; this is the official paper action
- R2: deterministic action plus ML shadow; research only
- R3: news-adjusted action plus ML shadow; research only

Stage 5D.4 does not aggregate prospective win rates, CAGR, or claims of ML effectiveness.

## Validation

| Suite | Result |
|---|---|
| Stage 5D.4 | PASS — 107/107 |
| Frozen Stage 5D.3 | PASS — 130/130 |
| Frozen Stage 5D.2 | PASS — 129/129 |
| Frozen Stage 5D.1 | PASS — 80/80 |

Frozen-scope audit:

- Stage 4A.3 changes: 0
- Stage 2.2.2 Final changes: 0
- Stage 2B.1 changes: 0
- Frozen Stage 5D.1 semantic changes: 0
- Frozen Stage 5D.2 ledger changes: 0
- Frozen Stage 5D.3 semantic changes: 0

This is deterministic paper-decision support and research evidence. It does not place orders, record fills, record sells, or communicate with a broker.
