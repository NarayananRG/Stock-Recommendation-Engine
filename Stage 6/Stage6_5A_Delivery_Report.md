# Stage 6.5A Delivery Report

## Result

PASS — Stage 6.5A immutable portfolio constituent source snapshot is complete on `stage6-portfolio-intelligence`.

- Exact Stage 6.4E baseline: `f150608994fbeea3b79d2a078642dee89e4f6a59`
- Schema: `STAGE6_PORTFOLIO_SOURCE_SNAPSHOT_V1`
- Store: `STAGE6_5A_PORTFOLIO_SOURCE_STORE_V1`
- Processor: `STAGE6_5A_PORTFOLIO_SOURCE_FREEZER_V1`
- Policy: `S6PORTSRCPOL_STAGE6_5A_V1`
- Policy hash: `1a9630e451429004d511bc9dab3124d70e2fef28b30adee3935741f30af537f2`
- Constituent contract: `STAGE6_PORTFOLIO_CONSTITUENT_CONTRACT_V1`
- Constituent-contract hash: `20e84549c4a1d5c5a526bad63cd92e798403fa92805e9e4f4af35bbaa062ed0c`
- Authority: `SHADOW_ONLY`
- Stage 5D.5 reference: `74b2710f0e19bd403978da81e87f25a3059ace06`
- Frozen Portfolio Context blob: `5900278a891dc70c63ce02f69002b5e9dec13799`

## Source export and PIT behavior

Stage 6.5A accepts only an explicit caller-supplied immutable `FIXTURE` or `STAGE5D5_PAPER_EXPORT` payload. A Stage 5D export is accepted only when it names the exact frozen Stage 5D.5 commit. The implementation never opens a live Stage 5D database and has no Stage 5D runtime dependency.

Every export binds a non-empty export ID, canonical 64-character export hash, immutable source database identity, source schema version, as-of timestamp, and cutoff timestamp. Cutoff must not exceed as-of. Entity Registry knowledge, prices, risk observations, pending-entry timestamps, and paired source-record timestamps must all be available no later than cutoff.

Each snapshot has exactly one currency (`INR` or `USD`). Capital ceiling, current prices, average costs, risk-at-stop inputs, and pending reservations must use that currency. No FX conversion exists.

## Constituent behavior

Open positions preserve whole-share quantity, explicit current price, explicit average cost, explicit risk-at-stop, recommendation identity, fill identities, nullable thesis identity, sector/subsector identity, source position identity, and paired source-record bindings. Pending entries preserve explicit reserved capital and source provenance. Caller ordering does not affect identity; positions, pending entries, fills, and bindings are canonicalized. Duplicate logical constituents fail closed.

The exact Entity Registry snapshot validates company type, PIT exchange/ticker mapping, sector type, and supplied subsector type. The fixture registry provides an explicit company-to-sector field and no company-to-subsector relation, so Stage 6.5A verifies the sector relation and accepts a null subsector. A supplied subsector without an exact registry-backed company relation fails closed; no relation is invented.

## Persistence and provenance

SQLite persistence is append-only. Metadata, policy, contract, snapshots, positions, pending entries, bindings, and dependencies reject update and delete. Integrity checks cover SQLite and foreign keys, singleton identity, trigger presence, canonical JSON, typed-column equality, constituent/binding coverage, exact Entity Registry and entity-record dependencies, deterministic replay, snapshot identity, and restart integrity.

Exact re-import is `IDEMPOTENT_SUCCESS`. Reuse of a source export ID with changed content is a deterministic conflict. A later export ID creates a new immutable snapshot.

## Deliberate boundary

Stage 6.5A freezes source facts only. It does not calculate market value, invested capital, cash, committed or available capital, aggregate risk, sector/subsector exposure, concentration, correlation, diversification, portfolio score, capital adequacy, replacement decisions, or allocation rules. It does not materialize `STAGE6_PORTFOLIO_CONTEXT_V2` and has no Stage 6.4 historical-analogue dependency.

It cannot submit orders, record fills or sells, cancel recommendations, change stops or quantity, reserve capital, modify profiles or ledgers, call a broker, or exercise BUY/SELL/HOLD authority.

## Verification

- Stage 6.5A: `171/171 PASS`
- Prior Stage 6.1A–6.4E: `1572/1572 PASS` at every frozen suite count
- Combined: `1743/1743 PASS`
- Stage 6.0C: `PASS / 10 schemas`
- Frozen Stage 5D changed files: `0`
- Frozen Stage 6 architecture/contracts/6.1–6.4 changed files: `0`
- Runtime SQLite/WAL/SHM artifacts committed: `0`
- `__pycache__` / `.pyc` committed: `0`
- Network/API/market-data/broker calls: `0`
- LLM/NLP/ML/OCR/embeddings/semantic similarity: `none`
- Trading authority: `false`
- Tags created: `0`

The frozen Stage 6.4A suite contains a historical branch-name assertion in addition to its descendant check. It was executed unchanged on its frozen `stage6-historical-analogue` branch and passed `73/73`; no frozen test was modified.

## Files added

- `Stage 6/stage6_portfolio_source/__init__.py`
- `Stage 6/stage6_portfolio_source/errors.py`
- `Stage 6/stage6_portfolio_source/policy.py`
- `Stage 6/stage6_portfolio_source/portfolio_source_builder.py`
- `Stage 6/stage6_portfolio_source/portfolio_source_validation.py`
- `Stage 6/stage6_portfolio_source/portfolio_source_store.py`
- `Stage 6/stage6_portfolio_source/portfolio_source_policy_v1.json`
- `Stage 6/stage6_portfolio_source/portfolio_constituent_contract_v1.json`
- `Stage 6/fixtures/stage6_5a/portfolio_source_examples.json`
- `Stage 6/tests/run_stage6_5a_tests.py`
- `Stage 6/results/stage6_5a_contract.json`
- `Stage 6/results/stage6_5a_test_results.csv`
- `Stage 6/Stage6_5A_Delivery_Report.md`

## Deferred

Stage 6.5B will own deterministic portfolio arithmetic and exposure aggregation. Stage 6.5C will own PIT correlation context. Stage 6.5D will own final `STAGE6_PORTFOLIO_CONTEXT_V2` assembly. Portfolio constraints, portfolio influence, replacement logic, expected-return interaction, persistent thesis, BUY/SELL/HOLD, live Stage 5D adapters, broker integration, and AI/ML remain deferred.
