# Stage 6.8C Delivery Report

## Result

PASS. Stage 6.8C adds a separate, shadow-only prospective observation layer. It does not alter or migrate the active Stage 6.8A enrollment store, rerun activation, change the Stage 6.8B source set, or modify Stage 5D or Stage 4A.3.

## Active-cohort guard

The deterministic cohort fingerprint binds the verified activation record, Stage 6.8A protocol/policy/enrollment hashes, Stage 6.8B policy/contract hashes, the frozen Stage 5D.5 tag and commit, the current tracked Stage 5D subtree, the complete Stage 4A.3 frozen model bundle, its seven serialized model component hashes, model feature hashes, Stage 4A.3 source-package manifest, Stage 6 registry V2 identities, and the exact RBI + SEBI operational source set. Any mismatch fails closed before Stage 6.8C evidence is accepted.

## Recommendation audit envelope

One deterministic envelope is permitted per recommendation whose exact Stage 5D origin run is an enrolled post-activation prospective session. A later prospective case is not required. Stage 5D and the active prospective store are opened read-only/query-only. The envelope binds the immutable recommendation and allocation hashes, portfolio/profile/capital context, independently resolved Stage 4A.3 snapshot/candidate/feature/model/market-data lineage, and only verified Stage 6 context that existed no later than recommendation persistence. Missing context is explicit. A recursive safety validator rejects future/outcome leakage.

## Benchmark checkpoints

The only checkpoint types are D+5, D+20, D+60 and FINAL_EXIT. Production D+N scheduling uses the verified Stage 6.8A enrolled control-session chain strictly after the origin session. The calculator uses a verified immutable market archive, a common stock/NIFTY close interval, canonical Decimal strings, exact point-in-time cutoffs, NIFTY-required comparison, explicit sector unavailability, forward-only D+1 onward MFE/MAE and completed-close maximum drawdown seeded by the decision close. Capture is blocked before 15:45 Asia/Kolkata. Thesis records are accepted only through verified read-only Stage 6 bindings as of cutoff. FINAL_EXIT applies transaction and void evidence point-in-time as of the checkpoint cutoff.

Market observations are classified as `OUTCOME_MEASUREMENT_ONLY_NOT_STAGE6_EVENT_EVIDENCE`. They have no recommendation, ranking, sizing, morning-revalidation, event-corroboration, execution or trading authority.

## Storage and operator

The isolated `STAGE6_8C_PROSPECTIVE_OBSERVATION_STORE_V1` SQLite store contains cohort fingerprints, immutable recommendation envelopes and immutable benchmark checkpoints. Every table has UPDATE/DELETE rejection triggers. Canonical records are hash-bound; exact replay is idempotent and conflicting replay fails. Production paths are restricted to `Stage 6/runtime/prospective_validation`; only tests may explicitly override that boundary.

The separate observation operator supports cohort verification, envelope creation, due-checkpoint inspection, frozen-adapter checkpoint market capture, checkpoint persistence and integrity/status reporting. It does not activate the protocol, download news, create orders, change positions or mutate Stage 5D. The live market-capture action was not run by Codex.

## Independent Audit Corrections

1. Real Stage 4A.3 snapshot resolution now verifies the seven immutable files, frozen snapshot content/hash chain, exact candidate and feature rows, candidate-input and market-data lineage, model bundle, feature identities and protocol identity. Caller-generated descriptors are production-prohibited.
2. Envelope eligibility now binds the enrolled origin prospective session. A later prospective case is explicitly optional and is never retroactively attached.
3. Production D+N scheduling now resolves only from the verified read-only Stage 6.8A session chain, with pinned NSE ordinary-session validation and explicit `NOT_DUE` behavior.
4. Checkpoints now require a file-hashed immutable market archive with provider, ticker, `^NSEI`, session, logical-hash and cutoff provenance. Arbitrary price JSON is production-prohibited.
5. Target-session capture is blocked before 15:45 Asia/Kolkata, including target market observations recorded before the completed-session boundary.
6. MFE and MAE now begin strictly after D0; D0 high/low cannot affect forward excursion. Drawdown remains seeded by the D0 close.
7. Creation and thesis context now require exact query-only Stage 6 store bindings or remain explicitly unavailable. Caller assertions are production-prohibited.
8. FINAL_EXIT now verifies canonical and typed transaction/void rows, trade/effective chronology, and applies voids only when known by the checkpoint cutoff.
9. Observation-store integrity now independently revalidates checkpoint-to-envelope and envelope-to-cohort relationships.

## Final Operational Market-Archive Correction

`STAGE6_8C_CHECKPOINT_MARKET_ARCHIVE_CREATOR_V1` completes the production path from a verified due checkpoint to checkpoint persistence. The operator derives the recommendation ticker and target session from the immutable envelope, Stage 5D origin run and verified Stage 6.8A session chain before acquisition. It blocks non-due checkpoints and target-day attempts before 15:45 Asia/Kolkata without invoking any transport.

The creator calls the frozen `STAGE4A3_FINAL_MARKET_DATA_ACQUIRE_AND_ARCHIVE_V1` implementation in `Stage 4A.3/stage4a3/final_market_data.py`; it does not implement another provider. The resulting create-once archive is stored only below `Stage 6/runtime/prospective_validation/checkpoint_market_data/<recommendation_id>/<checkpoint_type>/`. It binds the envelope, recommendation, checkpoint type, exact verified sessions, ticker, `^NSEI`, provider, acquisition time, frozen adapter, retained Stage 4A.3 source manifest/files, byte hashes, logical market-data hash, classification and canonical record hash.

Exact replay verifies every binding and file and returns `IDEMPOTENT_SUCCESS`; any differing or damaged archive fails with `CHECKPOINT_MARKET_ARCHIVE_CONFLICT` and is never overwritten. `MarketArchiveResolver` independently verifies the creator archive and its retained frozen-source provenance before checkpoint calculation. Market data remains `OUTCOME_MEASUREMENT_ONLY_NOT_STAGE6_EVENT_EVIDENCE`, with zero effect on the RBI/SEBI event-source set, recommendations, models or trading authority.

## Validation

- Stage 6.8C: 170/170 PASS.
- Stage 6.8A: 373/373 PASS.
- Stage 6.8B: 392/392 PASS.
- Full Stage 6 regression chain: 5,908/5,908 PASS.
- Stage 5D: 80/80, 129/129, 130/130, 107/107 and 160/160 PASS.
- Stage 6.0C architecture validator: PASS / 10 schemas.
- Frozen Stage 4A.3 model/source components: verified byte-for-byte by the cohort guard. Existing recorded suites remain 118/118, 26/26, 20/20 and 24/24 PASS.

## Frozen identities

All prior identities remain unchanged. The Stage 4A.3 bundle remains `4631eb8a1d0b34212252df3b1aae180f64ec98ba5e7955a84729df0a471c62da`; source package remains `cc1b7bfc85c77e40f029a5ccff670e531445e5051932dab7e7e8abd2116bdc2f`; Stage 6.8A protocol/policy/enrollment hashes remain `6232ae23df487f2b6fe7b84df971cbee902f3cad91b2da6f66e7d5ca2c8022be`, `d684bb4358dbe5a89f466f6eacaa0a4f759e3477b3002bf0f2e95ef102387f5d`, and `af73aab6e67bef22111d62ed563695ea6fc8d5f0a0234f3de41d1fd773c7fb05`; Stage 6.8B policy/contract hashes remain `582825a16b9ae40821dacb89c7e5711fd16998153557f2fc6315ca75e5088ec9` and `97f9eb9e551d9104291a21f7c9f935390fbd1359a6d472581ff6ce6a612eb9a4`.

The final Stage 6.8C policy hash is `78f0d43da4826896801f030646622fe1324101b592cd178642c67120bdfbfa94`; the final contract hash is `8f7fce02be208cfbe2c0c6e95f5127323b5b871c50ff3fa68a451c418ace093e`.

## Safety boundary

No activation rerun, runtime mutation, live connector, network call, historical backfill, model retraining, model promotion, frozen joblib regeneration, signal/ranking/sizing/threshold change, source-set change, Stage 5D change, Stage 4A.3 change, automated execution, tag, or Priority 4+ work was performed.
