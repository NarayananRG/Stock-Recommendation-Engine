# Stage 6 — Decision Intelligence Master Architecture

## Purpose and authority boundary

Stage 6 is a future, persistent decision-intelligence layer that observes and explains evidence around the frozen Stage 5D.5 production-control system. Stage 6.0 defines architecture, schemas, and policies only. It has no data acquisition, trading logic, broker connection, UI, or production decision authority. Every Stage 6 decision is `SHADOW_ONLY`.

The immutable production reference is tag `stage5d5-live-paper-runner-baseline`, commit `74b2710f0e19bd403978da81e87f25a3059ace06`. Stage 6 may reference exported identifiers and outcomes from that baseline but must never import mutable state into, write to, or alter Stage 5D.5. A future integration must use an append-only boundary adapter with explicit identity and hash checks.

## Roadmap and module boundaries

| Stage | Boundary | Planned output | Authority |
|---|---|---|---|
| 6.0 | Architecture and contracts | Schemas, policies, validation | SHADOW_ONLY |
| 6.1 | Free-source ingestion | Immutable source registry and raw evidence envelopes | SHADOW_ONLY |
| 6.2 | Event intelligence | Corroborated, conflict-preserving structured events | SHADOW_ONLY |
| 6.3 | Exposure graph | PIT-effective company/sector/exposure relationships | SHADOW_ONLY |
| 6.4 | Historical analogue engine | Leakage-safe outcome distributions and relative returns | SHADOW_ONLY |
| 6.5 | Portfolio intelligence | Concentration, correlation, risk-at-stop, cash context | SHADOW_ONLY |
| 6.6 | Persistent thesis and dynamic management | Versioned thesis reviews and proposals | SHADOW_ONLY |
| 6.7 | Morning revalidation | Pre-session entry revalidation proposals | SHADOW_ONLY |
| 6.8 | Prospective shadow validation | Immutable comparisons against Stage 5D.5 | SHADOW_ONLY |
| 6.9 | Promotion gates | Component-specific evidence and authority review | NO AUTOMATIC PROMOTION |
| 7 | User interface | Human review and audit presentation | Defined later |

Each module consumes only versioned contracts, emits immutable identified records, and cannot reach around the boundary to mutate another module's records. Two foundation registries precede all acquisition: the **Entity Registry** supplies PIT-effective company, instrument, sector, geography, commodity, currency, person, regulator, and group identities; the **Versioned Source Registry** supplies the authority, access, licensing, availability, and review state that applied at acquisition time. Acquisition preserves raw evidence; interpretation links to evidence IDs; exposure mapping links to evidence; analogues consume PIT snapshots; thesis and portfolio modules consume those identified outputs; shadow decisions cite every dependency.

## Data flow

1. The Entity Registry resolves stable entities, dated aliases, ticker mappings, and corporate relationships at the historical cutoff without overwriting prior versions.
2. The Versioned Source Registry describes the authority, access, licensing, automation permission, latency, availability, cost, and verification state that applied at the acquisition cutoff.
3. Ingestion eventually captures immutable evidence with separate publication, observation, and retrieval timestamps plus raw-payload and record hashes. Each evidence envelope cites both the entity-resolution version and source-registry version. Stage 6.0/6.0A does not perform ingestion.
4. Event intelligence classifies evidence, retains contradictions, and uses `CONFIRMED_CAUSE`, `PLAUSIBLE_CONTRIBUTOR`, `CORRELATED_MARKET_MOVE`, or `NO_SUPPORTED_CAUSE_FOUND` rather than inventing causality.
5. The exposure graph maps an event through macro, commodity, currency, rate, geography, sector, and company channels using dated, sourced assertions.
6. PIT market context records timestamped, explicitly unit-labelled stock, sector, NIFTY, volume, volatility, technical, commodity, currency, rate, and regime observations.
7. The analogue engine freezes its code identity, feature contract, selection inputs, universe, dates, exclusions, weights, thresholds, similarity method, and selected analogue identities before attaching future outcome labels. Outcomes never participate in selection.
8. Persistent theses retain the entry rationale, risks, initial/current levels, Stage 5D.5 fill references, invalidation conditions, reproducible input identities, and immutable change history. Daily review asks: **What materially changed since entry or the prior session?**
9. Portfolio intelligence evaluates holdings, pending entries, sector/subsector/correlation exposure, risk at stop, capital commitments, concentration, and explicit cash with unambiguous measurement units.
10. Shadow decisions cite exact input IDs and hashes, code identity, registry versions, evidence, context, analogue, thesis, portfolio state, reason codes, and explanation. They cannot affect Stage 5D.5.
11. Prospective validation compares frozen Stage 6 outputs to the official Stage 5D.5 control without rewriting either history.

The foundational flow is:

`Entity Registry + Versioned Source Registry → Raw Evidence → Event Intelligence → Exposure Graph + Market Context → Historical Analogues → Persistent Thesis + Portfolio Context → Shadow Decision`

Stage 6.1 must not ingest evidence until an entity-registry identity is available, a source-registry version is frozen for the acquisition, and the raw evidence envelope can reference both versions. No connector may infer an undated alias, silently reuse a later ticker mapping, or retroactively rewrite source authority.

## Evidence, PIT, and immutability

External facts require a source, authority level, original reference, publication time, observation time, content hash, entity binding, and retrieval status. When all timestamps are known, `publication <= observed <= retrieved`. Unknown time is explicit; it is never reconstructed silently. Corrections and later revisions are new linked versions, not overwrites.

Raw evidence should be content-addressed and append-only where practical. Interpretations, exposure assertions, contexts, theses, and decisions use stable IDs, as-of timestamps, schema versions, and immutable version histories. Historical evaluation must reproduce exactly what was knowable at each decision cutoff and must exclude future articles, filings, revisions, and prices.

## Event and transmission model

The event taxonomy is enumerated in `contracts/event.schema.json`. A global event is evaluated through explicit transmission channels:

`global event → macro/commodity/currency effect → sector effect → company exposure → observed market reaction → thesis impact`

Rules such as “war = sell”, “oil up = sell”, or “tariff = sell” are prohibited. Direction depends on exposure, time horizon, magnitude, existing price response, sector context, corroboration, and portfolio state. Conflicting evidence remains visible and unresolved until justified evidence supports a versioned conclusion.

## Persistent holdings and low churn

Existing holdings are not displaced merely because another candidate ranks slightly higher. A holding persists unless its own thesis materially weakens or is invalidated, or an explicit future portfolio constraint requires a proposal. Cash is a first-class valid allocation. Stage 6.0 defines no production percentages, replacement rules, or action thresholds.

## Failure behavior and audit trail

Missing source identity, failed hashes, invalid timestamp order, unsupported schema versions, ambiguous entity binding, stale exposures, PIT violations, unresolved required evidence, or missing dependency records fail closed for the affected shadow output. Discovery-only or unverified evidence cannot independently force an action. Failures are recorded; absence of evidence is never converted into reassuring evidence of absence.

Every future shadow decision must be reconstructable from immutable input IDs and hashes, contract versions, code/model identity, as-of cutoff, reason codes, and output hash. Logs must distinguish acquisition failure, no evidence found, contradictory evidence, unavailable context, and intentionally withheld interpretation.

## Production relationship

Stage 5D.5 remains the official production-control decision. Stage 6 cannot create or cancel a BUY, change quantity, stop, or target, sell, reduce, or replace a position. Passing tests does not change authority. Promotion is component-specific and requires the gates in `policy/Promotion_Gates.md`; no component may be promoted if it materially worsens safety.
