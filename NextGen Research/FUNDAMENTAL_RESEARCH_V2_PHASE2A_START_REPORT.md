# Fundamental Research V2 — Phase 2A Start Report

## Decision

**PHASE2A_FOUNDATION_STARTED — SHADOW_ONLY**

This branch starts the next research phase identified by Fundamental Research V2 Phase 1 and Deep Audit 1. It does **not** train a model, modify production recommendations, or promote any fundamental signal.

## Frozen evidence carried forward

- Phase 1 decision: `PROMISING_LONG_HORIZON_REVENUE_SIGNAL_NOT_VALIDATED_FOR_PROMOTION`.
- Deep Audit decision: `DO_NOT_PROMOTE_V2_YET`.
- Current official normalized quarterly history in the audit stops at `2024-12-31`.
- Median publication age in the audited replay was approximately 377.49 / 344.71 / 298.74 days at 20 / 63 / 126 sessions.
- The pooled first-decision-after-filing Revenue-YoY high-minus-low mean relative-return spread was `+7.5892 pp` at 20 sessions, with bootstrap 95% interval `[+1.4018 pp, +13.8241 pp]`.
- That signal was not cohort-stable: it was strong in the 2024-03 cohort and approximately absent in 2024-12.

## Phase 2A objective

Build a current, immutable, point-in-time official filing-event history for at least:

- 2025-03-31
- 2025-06-30
- 2025-09-30
- 2025-12-31
- 2026-03-31
- 2026-06-30

NSE is primary; BSE is official secondary. No yfinance fundamental fallback is permitted.

## What this first commit establishes

1. Official NSE/BSE source allow-list and priority.
2. Deterministic `M&M` / `MANDM` canonicalization before feature generation.
3. Original and revision filings retained as separate PIT knowledge events.
4. Publication timestamp is broadcast time for originals and revised time for revisions.
5. Revisions never rewrite the historical knowledge state before their revision timestamp.
6. Standalone/consolidated basis switches block growth unless an explicit bridge is later registered.
7. Accounting-family switches block growth pending taxonomy review.
8. Event-decay buckets are pre-registered as decision-age buckets: 0, 1-5, 6-20, 21-63, 64+.
9. Phase 2A cannot become ready unless current-quarter coverage, timestamp integrity, continuity audit, parser-breadth audit and source-manifest completeness all pass.
10. Even when Phase 2A is ready, model training and promotion remain disabled; readiness only opens the event-decay research leg.

## Focused validation

`44/44 PASS`

The tests cover governance, official-source enforcement, symbol aliases, basis normalization, original/revision timestamp semantics, duplicate handling, as-of selection, filing-to-decision chronology, continuity, event-decay bucketing, coverage gating and production freeze.

## Official-source feasibility verified at phase start

NSE's current corporate-filing pages state that financial results for quarter ended March 2025 onward are available under Integrated Filing - Financials. The Integrated Filing table exposes quarter end, submission type, audited status, consolidated/standalone basis, XBRL, broadcast timestamp, revised timestamp and revision remarks. This is sufficient metadata to implement the PIT event ledger without inferring publication dates.

## Next sub-leg

`PHASE2A.1_OFFICIAL_FILING_METADATA_RECOVERY`

Acquire the target-quarter filing metadata for the governed symbol universe, preserve original/revision rows separately, hash raw responses, run identity/timestamp/basis audits, and emit coverage. Do not compute alpha or train a challenger yet.
