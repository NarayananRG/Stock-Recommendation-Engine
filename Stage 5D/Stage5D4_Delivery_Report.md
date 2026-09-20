# Stage 5D.4 Delivery Report

- Branch: `stage5d4-news-ml-shadow`
- Commit SHA: the immutable pushed branch-head SHA is reported at delivery
- Frozen base tag: `stage5d3-daily-position-monitor-baseline`
- Frozen base commit: `edf48ec2d606b290faab23fae0139d702846f808`
- Stage 5D.4 schema: `STAGE5D4_SCHEMA_V1`

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
| Point-in-time news cutoff | PASS |
| Positive-news no-upgrade | PASS |
| Material adverse downgrade | PASS |
| Conservative multiple-event aggregation | PASS |
| Immutable news replay/conflict handling | PASS |
| Stage 4A.3 frozen protocol integration | PASS |
| ML production influence | NO |
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

Every included article must have a timezone-aware publication timestamp at or before `decision_cutoff_utc`. The persisted overlay retains event IDs, headlines, sources, timestamps, categories, severities, materiality, deterministic reason codes, and immutable hashes.

ML input is accepted only when it carries the exact frozen Stage 4A.3 protocol ID, protocol commit, model-bundle hash, and snapshot signal-date/content-hash lineage; passes its prospective eligibility flag; matches recommendation/signal/ticker lineage; and was produced no later than the decision cutoff. ML classifications and experimental `KEEP`/`FILTER`/`PROMOTE` views are stored for research only. `ml_influence` is always `NONE`.

## Research views

- R0: frozen deterministic action
- R1: deterministic action plus news overlay; this is the official paper action
- R2: deterministic action plus ML shadow; research only
- R3: news-adjusted action plus ML shadow; research only

Stage 5D.4 does not aggregate prospective win rates, CAGR, or claims of ML effectiveness.

## Validation

| Suite | Result |
|---|---|
| Stage 5D.4 | PASS — 80/80 |
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
