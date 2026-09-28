# Stage 6.5B Delivery Report

## Result and identity

PASS — Stage 6.5B deterministic portfolio arithmetic and exposure aggregation is complete on `stage6-portfolio-intelligence`.

- Exact Stage 6.5A baseline: `93b05ded5042423a6fa208cdb29f5961687fdb9c`
- Schema: `STAGE6_PORTFOLIO_ARITHMETIC_V1`
- Store: `STAGE6_5B_PORTFOLIO_ARITHMETIC_STORE_V1`
- Processor: `STAGE6_5B_PORTFOLIO_ARITHMETIC_AGGREGATOR_V1`
- Policy: `S6PORTARITHPOL_STAGE6_5B_V1`
- Policy hash: `dd2dcdcd7cbf00182d9ab62f0eca942fae8246ec570a2004388aa9dd3bdb5d19`
- Arithmetic contract: `STAGE6_PORTFOLIO_ARITHMETIC_CONTRACT_V1`
- Arithmetic-contract hash: `72642f1d50d6d1c78e2c15c23f81cefd88a62bf942d5f7d01bfd113665b7da80`
- Authority: `SHADOW_ONLY`

## Source snapshot binding

The arithmetic store requires the Stage 6.5A source store integrity check to pass, then loads exactly one immutable source snapshot by ID. It verifies the source record hash and the exact Stage 6.5A schema, processor, policy ID/hash, constituent-contract version/hash, authority, export identity/hash, timestamps, currency, capital ceiling, positions, and pending entries. It does not recreate the source snapshot.

Direct persisted dependencies are exactly the consumed Stage 6.5A source snapshot, the Stage 6.5B policy, and the Stage 6.5B arithmetic contract. There is no direct Entity Registry, Stage 5D, Evidence, Stage 6.4, event, market-context, or historical-analogue dependency.

## Deterministic arithmetic

Every numeric source value enters arithmetic through `Decimal(str(value))`. Multiplication, addition, subtraction, division, grouping, and conservation checks use Decimal with precision 50 and no currency quantization. Numbers convert to canonical JSON integers when integral, otherwise to a float from the final Decimal string only at the output boundary. Non-finite inputs or emitted results fail closed.

The formulas are:

- Position market value = quantity × current price.
- Invested capital = sum of open-position market values, or zero without holdings.
- Pending committed capital = sum of explicit pending reservations, or zero without pending entries.
- Committed capital = invested capital + pending committed capital; it is not capped.
- Cash = max(0, capital ceiling − invested capital). Pending reservations do not reduce cash.
- Available capital = max(0, capital ceiling − committed capital).
- Invested overage = max(0, invested capital − capital ceiling).
- Committed overage = max(0, committed capital − capital ceiling).
- Aggregate risk at stop = sum of explicit Stage 6.5A risk-at-stop inputs.

Overage values are descriptive audit facts and cause no sale, cancellation, recommendation, or allocation action.

## Held and pending exposure semantics

Company concentration and sector/subsector exposure use open-position market value only. Multiple held source positions for one company are combined. Company and sector amounts conserve exactly to invested capital; their emitted fractions sum to one within the frozen `1E-12` serialization tolerance.

Only non-null subsectors are grouped. No `UNKNOWN`, `OTHER`, or synthetic subsector is created. `positions_without_subsector_count` and `market_value_without_subsector` make incomplete coverage explicit, and known subsector value plus uncovered value conserves to invested capital.

Pending reservations are separately grouped by company, sector, and known subsector. They affect committed and available capital but are never merged into held company concentration or held sector/subsector exposure.

Derived positions preserve company, ticker, recommendation, nullable thesis, fill IDs, quantity, current-price observation, average cost, explicit risk, sector/subsector, and source-position identity. Final-compatible monetary projections use `unit`.

## Deliberate boundary

Cash is persisted as a valid allocation invariant without creating a cash recommendation. Correlation remains `NOT_EVALUATED`; no return series, covariance, Pearson/Spearman calculation, or correlated group exists. `STAGE6_PORTFOLIO_CONTEXT_V2` remains `NOT_MATERIALIZED`.

There are no portfolio thresholds, concentration labels, diversification classifications, expected-return inputs, replacement rules, admission rules, BUY/SELL/HOLD logic, allocation proposals, Stage 5D runtime reads, broker actions, or production authority.

## Persistence and verification

Metadata, policy, contract, arithmetic records, positions, exposures, pending aggregates, and dependencies are append-only and reject UPDATE/DELETE. Integrity verification covers SQLite, foreign keys, singleton identity, triggers, canonical records, typed columns, complete position/exposure/pending coverage, exact direct dependencies, upstream source integrity, deterministic replay, restart behavior, and tampering.

- Stage 6.5B: `204/204 PASS`
- Prior Stage 6.1A–6.5A: `1743/1743 PASS`
- Combined: `1947/1947 PASS`
- Stage 6.0C: `PASS / 10 schemas`
- Frozen Portfolio Context blob: `5900278a891dc70c63ce02f69002b5e9dec13799`
- Frozen Historical Analogue blob: `85a2b0d00cacd6a3caea484e3ef3071eb16fe01d`
- Frozen Market Context blob: `a141b221228718b8276b3d05b2f028d21adcfc3f`
- Frozen Stage 5D changed files: `0`
- Frozen Stage 6.1–6.5A changed files: `0`
- Runtime SQLite/WAL/SHM artifacts committed: `0`
- `__pycache__` / `.pyc` committed: `0`
- Network/API/market-data/broker calls: `0`
- LLM/NLP/ML/OCR/embeddings/semantic similarity: `none`
- Trading authority: `false`
- Tags created: `0`

The frozen Stage 6.4A suite was run unchanged on its historical branch because its frozen regression includes the documented historical branch-name assertion. It passed `73/73`; no frozen test was edited.

## Files added

- `Stage 6/stage6_portfolio_arithmetic/__init__.py`
- `Stage 6/stage6_portfolio_arithmetic/errors.py`
- `Stage 6/stage6_portfolio_arithmetic/arithmetic.py`
- `Stage 6/stage6_portfolio_arithmetic/policy.py`
- `Stage 6/stage6_portfolio_arithmetic/portfolio_arithmetic_builder.py`
- `Stage 6/stage6_portfolio_arithmetic/portfolio_arithmetic_validation.py`
- `Stage 6/stage6_portfolio_arithmetic/portfolio_arithmetic_store.py`
- `Stage 6/stage6_portfolio_arithmetic/portfolio_arithmetic_policy_v1.json`
- `Stage 6/stage6_portfolio_arithmetic/portfolio_arithmetic_contract_v1.json`
- `Stage 6/fixtures/stage6_5b/portfolio_arithmetic_examples.json`
- `Stage 6/tests/run_stage6_5b_tests.py`
- `Stage 6/results/stage6_5b_contract.json`
- `Stage 6/results/stage6_5b_test_results.csv`
- `Stage 6/Stage6_5B_Delivery_Report.md`

## Deferred

Stage 6.5C owns PIT return-history provenance and reproducible correlation context. Stage 6.5D owns final `STAGE6_PORTFOLIO_CONTEXT_V2` assembly. Portfolio thresholds, diversification thresholds, portfolio influence, expected-return interaction, replacement logic, persistent thesis interaction, BUY/SELL/HOLD, live Stage 5D adapters, broker integration, and AI/ML remain deferred.
