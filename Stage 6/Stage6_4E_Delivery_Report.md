# Stage 6.4E Delivery Report

## Result and identity

**PASS** — Stage 6.4E completes the Stage 6.4 architectural deliverable on `stage6-historical-analogue`.

- Development baseline / outcome-attachment implementation: `10860dae29d1d0d3b1f1b595d1aad37e34aed6c9`
- Selection-engine commit: `ecdbb6cba292ee52a25b3e73bab901eeb1721f87`
- Payload/store/processor: `STAGE6_HISTORICAL_ANALOGUE_V2` / `STAGE6_4E_HISTORICAL_ANALOGUE_STORE_V1` / `STAGE6_4E_HISTORICAL_ANALOGUE_AGGREGATOR_V1`
- Policy/hash: `S6ANAGGPOL_STAGE6_4E_V1` / `41dacb0dfa0dcf09d5311b78573a50865372ada0bbf917d9c95e03edc4c0173f`
- Aggregation contract/hash: `STAGE6_ANALOGUE_AGGREGATION_CONTRACT_V1` / `028f3829634793af67c33f7ab041ae8c8732e9d8ea3502c058a478ea9316b981`
- Authority: `SHADOW_ONLY`

The final V2 `code_commit` is exactly the frozen Stage 6.4C selection-engine commit, and `analogue_engine_version` is exactly `STAGE6_4C_ANALOGUE_SELECTOR_V1`. The 6.4E processor, policy/hash, aggregation contract/hash, and 6.4D implementation commit remain in the immutable wrapper rather than altering selection identity.

## Cross-stage binding

The assembler requires integrity PASS from the Stage 6.4C selection store, Stage 6.4D outcome store, and Stage 6.4B feature store. It loads only the exact target Stage 6.4B snapshot. Selection record/hash/specification, target IDs/hashes, selection-input hash, selected count, attachment IDs/ranks, and selected analogue identity fields must agree exactly across stages. Candidate feature snapshots, Event, 6.3, 6.4A, Evidence, and registries are never direct inputs.

The exact target 12-field snapshot is copied without transformation and canonically rehashed. Selected analogue order and every analogue ID, timestamp, entity, Event, similarity, distance, unit, and input snapshot hash remain unchanged by outcomes.

## Deterministic aggregation

Only `AVAILABLE` measurements participate. `NOT_MATURED` and `MISSING` remain absent rather than becoming zero. Values are unweighted; similarity, distance, recency, magnitude, and company attributes never weight results. No trimming, clipping, winsorization, or sign-based filtering occurs.

Each distribution contains count, median, arithmetic `math.fsum` mean, population standard deviation, p10, p25, p75, p90, minimum, maximum, and unit. Quantiles use frozen linear interpolation with `index=(n-1)*p`. Empty distributions contain count zero and null statistics; singleton standard deviation is zero.

Stock, MAE, MFE, and recovery distributions use their already-attached values. Recovery remains `TRADING_SESSIONS`. Sector/NIFTY relative values are paired stock-minus-reference values only when both inputs are available. The final measurement is their unweighted median under `MEDIAN_PAIRED_RELATIVE_RETURN_V1`; no pair produces null. Immutable wrapper audit metadata preserves stock and paired counts per horizon.

## Final validation and persistence

The final payload is validated deterministically against the closed frozen `STAGE6_HISTORICAL_ANALOGUE_V2` field/type/hash contract, including additional-property rejection, required fields, horizons, distributions, measurements, deterministic content-addressed ID, and record hash. Stage 6.4E metadata is kept outside the closed payload.

Append-only SQLite stores singleton metadata/policy/contract, final wrapper/payload, coverage audit, and exact dependencies. All tables reject UPDATE and DELETE. Integrity checks verify triggers, SQLite/foreign keys, upstream records, cross-stage agreement, schema, statistics, coverage, IDs/hashes, dependencies, and deterministic replay.

Interpretation readiness is `INSUFFICIENT_SELECTED_ANALOGUES` below the frozen minimum, otherwise `SELECTED_ANALOGUE_REQUIREMENT_SATISFIED`. Incomplete outcomes do not suppress or fabricate the final immutable record.

## Verification

Stage 6.4E: **179/179 PASS**. Existing regressions: **1,393/1,393 PASS**. Total: **1,572/1,572 PASS**. Stage 6.0C: **PASS / 10 schemas**.

Individual counts: 152, 68, 86, 75, 68, 61, 57, 57, 66, 39, 28, 13, 27, 28, 30, 31, 24, 17, 73, 98, 142, 153, 179 — all PASS.

## Boundary audit

- Historical analogue blob: `85a2b0d00cacd6a3caea484e3ef3071eb16fe01d`
- Market-context blob: `a141b221228718b8276b3d05b2f028d21adcfc3f`
- Frozen changed files: **0**
- Stage 5D changes: **0**
- Runtime artifacts committed: **0**
- Network/API calls: **0**
- LLM/NLP/ML/OCR/embeddings/semantic similarity: **none**
- Trading authority: **false**
- Tags: **none**

Only the additive `stage6_historical_analogue` package, Stage 6.4E fixture, tests, results, contract artifact, and this report are added.

Expected return, probability of gain, target price, ranking, portfolio influence, BUY/SELL/HOLD, trading authority, learned weighting/similarity, and AI remain deferred. Stage 6.5 is not started.
