# Stage 6.4D Delivery Report

## Result

**PASS** — Stage 6.4D implements leakage-isolated per-analogue future-outcome attachment on `stage6-historical-analogue`.

- Exact Stage 6.4C baseline and selection-engine commit: `ecdbb6cba292ee52a25b3e73bab901eeb1721f87`
- Schema/store/processor: `STAGE6_ANALOGUE_OUTCOME_ATTACHMENT_V1` / `STAGE6_4D_ANALOGUE_OUTCOME_STORE_V1` / `STAGE6_4D_ANALOGUE_OUTCOME_ATTACHER_V1`
- Policy/hash: `S6ANOUTPOL_STAGE6_4D_V1` / `3aa6bc70bfd1a8b29287cd609282d6a5d00c9839aeebaaa09d5761b8ce1d0a24`
- Outcome definition/hash: `STAGE6_ANALOGUE_OUTCOME_DEFINITION_V1` / `2535f09dacd8d67215121d4a60a925885ab53ba8e771e8df355c4c14b12ea85a`
- Authority: `SHADOW_ONLY`

## Selection binding and coverage

The exact integrity-verified Stage 6.4C record is authoritative. Stage 6.4D copies its selection record/hash, selection specification, candidate-universe hash, target identities/cutoff, selected count, selected analogue identities/order/ranks, similarity/distance audit fields, and input hashes. It does not import the comparator or selection builder and never reconstructs, rescores, filters, replaces, or reorders selection. Caller payload coverage must be exactly one-to-one with selected analogue IDs; duplicates, omissions, and unselected IDs fail closed. Empty selection creates a valid immutable `NO_SELECTED_ANALOGUES` set.

## Outcome definition and PIT controls

One attachment set uses exactly one common `PERCENT_RETURN` or `DECIMAL_RETURN` unit, without conversion. Each selected analogue contains D+1, D+3, D+5, D+10, and D+20 stock, sector, and NIFTY measurements. Every measurement is explicitly `AVAILABLE`, `NOT_MATURED`, or `MISSING`. Available labels require a finite explicit value, exact unit, non-empty method, observation-through timestamp, and exact immutable evidence bindings. Null states preserve null and prohibit fabricated evidence or values.

Every available observation is strictly after the frozen historical anchor and not after the target selection cutoff. Every supporting record must be exact `STAGE6_EVIDENCE_V2` with `record_kind=EVIDENCE`, exact ID/hash, passing ingestion-store integrity, and retrieval no later than the target cutoff. Acquisition attempts and later-retrieved evidence fail closed. Raw payloads are never parsed. Explicit adversarial tests reject D+20 observation and evidence retrieval one second after cutoff.

MAE is explicit, finite, in the common return unit, and non-positive. MFE is explicit, finite, and non-negative. Recovery uses `TRADING_SESSIONS` and a non-negative integer. Each uses the same anchor/cutoff/evidence protections. No price-path calculation occurs here.

## Anti-bias and coverage

Positive, negative, extreme, missing, not-matured, and unrecovered outcomes cannot alter membership. All selected analogues remain represented, preventing outcome filtering and survivorship bias. The record reports only available D+horizon/measurement, MAE, MFE, and recovery counts. It calculates no mean, median, percentile, standard deviation, distribution, relative return, expected return, or target price.

## Persistence and dependencies

Append-only SQLite stores singleton metadata/policy/definition, attachment sets, every per-analogue attachment, all measurements, evidence bindings, and direct dependencies. Every table rejects UPDATE and DELETE. Integrity checking verifies SQLite/foreign keys/triggers, canonical JSON, typed columns, exact coverage/ranks, measurements/evidence, hashes, dependencies, and deterministic replay.

Direct dependencies are exactly the Stage 6.4C selection record, Stage 6.4D policy, outcome definition, and each Evidence record used by available labels. Stage 6.4B, Event, Stage 6.3, Stage 6.4A, Exposure, and registries are not direct dependencies.

## Verification

| Suite | Result |
|---|---|
| Stage 6.1A | 152/152 PASS |
| Stage 6.1B | 68/68 PASS |
| Stage 6.1C | 86/86 PASS |
| Stage 6.2A | 75/75 PASS |
| Stage 6.2B | 68/68 PASS |
| Stage 6.2C | 61/61 PASS |
| Stage 6.2D | 57/57 PASS |
| Stage 6.2E | 57/57 PASS |
| Stage 6.2F | 66/66 PASS |
| Stage 6.3A | 39/39 PASS |
| Stage 6.3B | 28/28 PASS |
| Stage 6.3C | 13/13 PASS |
| Stage 6.3D | 27/27 PASS |
| Stage 6.3E | 28/28 PASS |
| Stage 6.3F | 30/30 PASS |
| Stage 6.3G | 31/31 PASS |
| Stage 6.3H | 24/24 PASS |
| Stage 6.3I | 17/17 PASS |
| Stage 6.4A | 73/73 PASS |
| Stage 6.4B | 98/98 PASS |
| Stage 6.4C | 142/142 PASS |
| Stage 6.4D | 153/153 PASS |
| Stage 6.0C | PASS, 10 schemas |

Existing regressions: 1,240/1,240 PASS. Total including Stage 6.4D: 1,393/1,393 PASS.

## Boundary audit

Historical analogue blob: `85a2b0d00cacd6a3caea484e3ef3071eb16fe01d`. Market-context blob: `a141b221228718b8276b3d05b2f028d21adcfc3f`. Frozen changed files: **0**. Stage 5D changes: **0**. Runtime artifacts committed: **0**. Network/API: **0**. LLM/NLP/ML/OCR/embeddings/semantic similarity: **none**. Trading authority: **false**. Tags: **none**.

## Changed files and deferred work

Only the additive `stage6_analogue_outcomes` package, Stage 6.4D fixture, tests, evidence CSV, contract artifact, and report are added. Aggregate distributions, relative returns, final `STAGE6_HISTORICAL_ANALOGUE_V2`, expected return, target price, ranking, portfolio influence, BUY/SELL/HOLD, trading authority, adaptive weights, learned similarity, and AI remain deferred to Stage 6.4E or later. Stage 6.4E must consume the frozen selection and outcome set without rerunning selection.
