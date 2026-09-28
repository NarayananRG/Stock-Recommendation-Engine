# Stage 6.4C Delivery Report

## Result

**PASS** — Stage 6.4C implements deterministic leakage-safe historical analogue selection on branch `stage6-historical-analogue`.

- Exact development baseline: `74f9a4bf4a9e669e9982fc58ba610934d54fc2f2`
- Stage 6.4B schema/store/processor: `STAGE6_ANALOGUE_FEATURE_SNAPSHOT_V1` / `STAGE6_4B_ANALOGUE_FEATURE_STORE_V1` / `STAGE6_4B_ANALOGUE_FEATURE_FREEZER_V1`
- Stage 6.4B policy/hash: `S6ANFEATPOL_STAGE6_4B_V1` / `ee9b8a5cfb5500d88e9002ffd984d8e37cc690496201fe7913e164f188281f16`
- Stage 6.4B feature contract/hash: `STAGE6_ANALOGUE_FEATURE_CONTRACT_V1` / `4a263fb50e4db4eb44e2e474087cd0cd1e08a68b02298d019ad9d02e8f45484f`
- Stage 6.4C schema/store/processor: `STAGE6_ANALOGUE_SELECTION_V1` / `STAGE6_4C_ANALOGUE_SELECTION_STORE_V1` / `STAGE6_4C_ANALOGUE_SELECTOR_V1`
- Policy/hash: `S6ANSELPOL_STAGE6_4C_V1` / `36dfffc457342314e0907e31bebb7e54bd21747134dbaded7d34b822e6bcc9b2`
- Comparison contract/hash: `STAGE6_ANALOGUE_COMPARISON_CONTRACT_V1` / `115ae49b1ac8cc005ca1bdb876576600603d593ec2e1ed09c2fee4c6d79b1401`
- Metric: `STAGE6_MIXED_DISTANCE_V1`
- Authority: `SHADOW_ONLY`

## Frozen comparison and selection rules

The selector consumes only exact, integrity-verified Stage 6.4B feature snapshots. The caller supplies a non-empty unique candidate-ID list; sorted exact ID/feature-hash/record-hash bindings form `EXPLICIT_STAGE6_4B_FEATURE_SNAPSHOT_SET_V1` and its canonical universe hash. Later additions to the Stage 6.4B database cannot change a frozen selection.

Eligible dates are explicit and never inferred. Candidate cutoff must be strictly earlier than target cutoff; historical as-of date must be inside the frozen range. Target snapshot, target Event ID, non-historical cutoff, outside-range candidate, and non-exact Event type are excluded with retained reason codes.

All 12 top-level features have explicit weight `1.0`. Categorical and descriptive values use exact canonical equality. Finite numeric values with identical units use `abs(a-b)/(abs(a)+abs(b))`, with zero/zero equal to zero. Null on either side, including both-null, receives distance `1.0` without imputation. Unit mismatch receives distance `1.0` without conversion. Return composites use exact 1D/3D/5D/20D horizons; stock and sector composites use the frozen arithmetic means. Named arrays match exact case-folded names over the union; missing names, incompatible units, nulls, and both-empty arrays receive conservative penalties.

Top-level weighted distance is bounded `[0,1]`; similarity is exactly `1-distance`. Maximum distance is `1.0 UNITLESS_DISTANCE`, top-K is 20, and minimum interpretation count is 5. Ranking is distance ascending then feature snapshot ID ascending, with no recency or outcome tie-break. Duplicate Events and duplicate selection-input hashes each retain the best distance then lexicographically smallest feature snapshot ID.

The immutable selection specification binds target, universe, eligible range, rules, Stage 6.4B feature contract, 6.4C policy and comparison contract, weights, metric, threshold, top-K, and minimum count. `selection_spec_hash` is computed before candidate scoring and excludes candidate evaluations. Every supplied candidate remains in the audit record, including rejected candidates. Selected records expose eventual Historical Analogue V2-compatible identity, timestamp, entity, Event, similarity, distance, units, and input snapshot hash.

## PIT and outcome isolation

No current clock, random UUID, insertion time, outcome, or later Event resolution participates. Future returns, MAE, MFE, recovery time, future relative returns, expected return, target price, portfolio results, and Stage 5D outcomes are inaccessible and unattached. The final `STAGE6_HISTORICAL_ANALOGUE_V2` record is deliberately not materialized. No unknown Stage 6.4C commit is fabricated as `code_commit`; processor, policy hash, and comparison-contract hash provide executable identity until the committed implementation can be bound by Stage 6.4D.

## Persistence and dependencies

Append-only SQLite stores metadata, singleton policy/contract, selection records, exact universes, every evaluation, ranked selections, and direct dependencies. UPDATE/DELETE triggers protect every table. Integrity verification checks SQLite/foreign keys/triggers, singletons, canonical JSON, typed columns, target and universe bindings, evaluation coverage, selected-subset consistency, dependencies, hashes, and deterministic replay.

Direct dependencies are only target/candidate Stage 6.4B feature snapshots, the Stage 6.4C policy, and comparison contract. Event, Stage 6.3I, Stage 6.4A, Exposure, Evidence, and registries remain transitive.

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
| Stage 6.0C | PASS, 10 schemas parsed |

Prior regression total is 1,098/1,098; including Stage 6.4C, 1,240/1,240 tests pass.

## Boundary audit

Historical analogue contract blob: `85a2b0d00cacd6a3caea484e3ef3071eb16fe01d`. Market-context contract blob: `a141b221228718b8276b3d05b2f028d21adcfc3f`. Frozen changed files: **0**. Stage 5D changed files: **0**. Runtime artifacts committed: **0**. Network/API calls: **0**. LLM/NLP/ML/OCR/embeddings/semantic similarity: **none**. Trading authority: **false**. Tags: **none**.

## Changed files

Only the additive `stage6_analogue_selection` package, Stage 6.4C fixture, test suite, test evidence, contract artifact, and this report are added.

## Deferred to Stage 6.4D or later

Future price/outcome acquisition; outcome contract/runtime; D+1/D+3/D+5/D+10/D+20; MAE/MFE/recovery; sector/NIFTY-relative outcomes; outcome distributions; final Historical Analogue V2 assembly; expected return; confidence-to-return mapping; target price; ranking; portfolio influence; BUY/SELL/HOLD; trading authority; learned weights/similarity; and ML/NLP/LLM remain deferred. Stage 6.4D must attach outcomes to the already-frozen selected identities without rerunning selection.
