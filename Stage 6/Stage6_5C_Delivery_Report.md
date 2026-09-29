# Stage 6.5C Delivery Report

## Result and identity

PASS — Stage 6.5C point-in-time portfolio correlation context is complete on `stage6-portfolio-intelligence`.

- Exact Stage 6.5B baseline: `31527d4c6f61e467306c62607d5d3ab4dd98a9d5`
- Schema: `STAGE6_PORTFOLIO_CORRELATION_CONTEXT_V1`
- Store: `STAGE6_5C_PORTFOLIO_CORRELATION_STORE_V1`
- Processor: `STAGE6_5C_PORTFOLIO_CORRELATION_CALCULATOR_V1`
- Policy: `S6PORTCORRPOL_STAGE6_5C_V1`
- Policy hash: `b03dd26fdf5d8171dd42bb628f80609a833c9c2bce7c0808ca9ea8e0c87321c0`
- Correlation contract: `STAGE6_PORTFOLIO_CORRELATION_CONTRACT_V1`
- Correlation-contract hash: `9e852563a63c8e8ce1f21ebd542a2355b5330b8e0aa2d7b940d350fa399c234e`
- Method: `PEARSON_PAIRWISE_COMPLETE_V1`
- Authority: `SHADOW_ONLY`

## Exact Stage 6.5B boundary

The correlation store requires the Stage 6.5B store integrity check to pass, then consumes exactly one immutable arithmetic record by ID. It verifies its ID/hash, schema, processor, policy ID/hash, arithmetic-contract version/hash, authority, source snapshot ID/hash, source as-of time, portfolio cutoff, currency, and derived open positions. It never recreates arithmetic and has no direct Stage 6.5A, Stage 5D, Entity Registry, Stage 6.4, event, market-context, or historical-analogue dependency.

Direct persisted dependencies are exactly the Stage 6.5B arithmetic record, Stage 6.5C policy, and Stage 6.5C correlation contract.

## Held universe and pair behavior

The held universe is the sorted unique set of `company_entity_id` values in Stage 6.5B `derived_open_positions`. Multiple positions for one company are deduplicated. Pending entries, ticker identity, recommendation identity, sector, and subsector do not create correlation members. With fewer than two companies the pair list is empty; otherwise all unique unordered two-company pairs are emitted in canonical order.

## Immutable PIT return-history manifest

The caller must provide a complete explicit immutable `FIXTURE` or `PIT_RETURN_EXPORT` manifest. Export ID/hash, source schema, dataset ID, as-of time, data cutoff, frequency, unit, lookback, explicit window start, minimum observations, and exactly one series for every held company are required. Caller series and observation ordering is canonicalized before hashing. Missing series remain explicit with empty observations and are never fabricated.

One manifest has one return unit (`PERCENT_RETURN` or `DECIMAL_RETURN`) and one frequency (`DAILY`, `WEEKLY`, or `MONTHLY`). Stage 6.5C performs no conversion, resampling, price download, or live adapter work. Every observation and source-record timestamp must remain within the explicit window/cutoff, the return cutoff cannot exceed the portfolio cutoff, and return as-of cannot exceed the Stage 6.5B source as-of.

## Correlation methodology

Pairs use only exact common `period_end_utc` timestamps, sorted ascending. There is no union, forward/back fill, interpolation, nearest-date match, resampling, or zero fill. `actual_observations` is the exact intersection size.

The caller freezes an integer minimum of at least two before calculation. Below minimum, value is `null` with `INSUFFICIENT_OBSERVATIONS`. A missing member series yields `null` with `MISSING_SERIES` and zero actual observations.

Pearson correlation is implemented directly using means, centered deviations, numerator, sums of squares, square root, and division. Input values enter through `Decimal(str(value))`, and all arithmetic uses fixed precision 50. No NumPy/Pandas defaults or ddof convention is involved. Zero variance yields `null` with `ZERO_VARIANCE`. Valid signed values must remain within [-1, 1]; only drift within frozen tolerance `1E-24` may normalize to the exact boundary. There is no absolute-value transform.

Each final-compatible correlation object contains only members, method, value, `CORRELATION` unit, frequency, lookback, minimum and actual observations, and cutoff. Wrapper audit metadata retains status/null reason, aligned timestamp hash, return unit, source-series hashes, and manifest hash.

## Deliberate boundary

Correlation is descriptive only. There are no high/low labels, thresholds, sign interpretations, position/risk/concentration weights, correlation groups, clusters, factor models, covariance output, beta, NIFTY/sector correlation, correlated-capital amounts, diversification scoring, constraints, replacement logic, portfolio influence, BUY/SELL/HOLD, or trading authority. `STAGE6_PORTFOLIO_CONTEXT_V2` remains `NOT_MATERIALIZED` for Stage 6.5D.

## Persistence and validation

Metadata, policy, contract, correlation records, series, observations, pairs, source bindings, and dependencies are append-only and reject UPDATE/DELETE. Integrity checks cover SQLite, foreign keys, singleton configuration, trigger presence, canonical/typed columns, full series/observation/pair coverage, source bindings, dependencies, upstream Stage 6.5B integrity, deterministic replay, restart behavior, idempotency, export-ID conflicts, and tampering.

- Stage 6.5C: `180/180 PASS`
- Prior Stage 6.1A–6.5B: `1947/1947 PASS`
- Combined: `2127/2127 PASS`
- Stage 6.0C: `PASS / 10 schemas`
- Frozen Portfolio Context blob: `5900278a891dc70c63ce02f69002b5e9dec13799`
- Frozen Historical Analogue blob: `85a2b0d00cacd6a3caea484e3ef3071eb16fe01d`
- Frozen Market Context blob: `a141b221228718b8276b3d05b2f028d21adcfc3f`
- Frozen Stage 5D changed files: `0`
- Frozen Stage 6.1–6.5B changed files: `0`
- Runtime SQLite/WAL/SHM, return exports, downloaded prices, logs, caches, credentials: `0`
- Network/API/market-data/broker calls: `0`
- LLM/NLP/ML/OCR/embeddings/semantic similarity: `none`
- Trading authority: `false`
- Tags created: `0`

The frozen Stage 6.4A suite was run unchanged using the established historical-branch identity procedure and passed `73/73`. No frozen test was edited.

## Files added

- `Stage 6/stage6_portfolio_correlation/__init__.py`
- `Stage 6/stage6_portfolio_correlation/errors.py`
- `Stage 6/stage6_portfolio_correlation/policy.py`
- `Stage 6/stage6_portfolio_correlation/correlation_math.py`
- `Stage 6/stage6_portfolio_correlation/correlation_builder.py`
- `Stage 6/stage6_portfolio_correlation/correlation_validation.py`
- `Stage 6/stage6_portfolio_correlation/correlation_store.py`
- `Stage 6/stage6_portfolio_correlation/portfolio_correlation_policy_v1.json`
- `Stage 6/stage6_portfolio_correlation/portfolio_correlation_contract_v1.json`
- `Stage 6/fixtures/stage6_5c/portfolio_correlation_examples.json`
- `Stage 6/tests/run_stage6_5c_tests.py`
- `Stage 6/results/stage6_5c_contract.json`
- `Stage 6/results/stage6_5c_test_results.csv`
- `Stage 6/Stage6_5C_Delivery_Report.md`

## Deferred

Stage 6.5D owns final `STAGE6_PORTFOLIO_CONTEXT_V2` assembly without recalculating arithmetic or correlation. Correlation interpretation, thresholds, correlated-capital amounts, clustering/groups, diversification scoring, portfolio constraints/influence, candidate replacement, expected-return interaction, persistent-thesis interaction, BUY/SELL/HOLD, trading authority, live return-history adapters, network market-data acquisition, and ML/AI remain deferred.
