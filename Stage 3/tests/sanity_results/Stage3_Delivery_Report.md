# Stage 3 Delivery Report

ENGINEERING STATUS: **PASS**

Stage 3 constructed point-in-time research datasets only. It did not train or evaluate a predictive model.

## Frozen baseline

- Tag: `stage2b.1-dynamic-research-baseline`
- Commit: `c9cc9f4fcaf2fe81128365be09515fbf9fa67c28`
- Stage 2B.1 experiment: `S2B1_20160101_20260828_a681f1f8a9d9`
- Stage 2B.1 package hash: `9bba171b9917b9d125d2487e4afa53f6cc047e0a5ccbe3055ebb3e84363d854e`
- Immutable baseline hashes verified before and after execution: **PASS**
- STAGE21_CODE_HASH: `91d3d84760c4b2427d500f0bee0f2dc0ceeb7e4f2e31d51d17a64342777993d5`
- STAGE221_CODE_HASH: `8e6514353cc32a5b8bed1212df0c12d76de11d0624e4931fda4028f0be3ed31f`
- STAGE222_FINAL_CODE_HASH: `63345c591b46c656b204236d147993cb283d57fdbccd0246b7cef281d7968730`
- STRATEGY_HASH: `e62dc4e75c056a216cc4bdaa589a95f9553ce40e37aa6690974759b7975ad23c`
- EXECUTION_BASELINE_HASH: `9434b39d2d7bbd8203a4674b4acdebfecf898afbc08cf7bc144729ec4b326c2b`
- DATA_CONTENT_HASH: `2b6a2bb93fcc6c3aa80d2115a002b8cba370f61442edb592ffc9bc95eaa02e35`

## Stage 3 identity

- Experiment ID: `S3_20110830_20260828_bb15e0fa65d2_SANITY`
- Code package hash: `1c06cb7e1345b10ea8b2db65aea02d54468c0da7b816bf48575f169fa8f2a23a`
- Config hash: `1cf258801142c74f33246bed6492ab87adfd1377dcdec0641092098d329e009e`
- Combined schema hash: `34dec9e84e313af34d0b501f66ae6a731cd74f06df94657a2cebacaa5ff820b2`

## Dataset research findings (descriptive only)

- Signal-state rows: 7,356
- Opportunity rows: 1,519
- Filled opportunities: 1,147
- Observed non-filled opportunities: 372
- Entry-censored opportunities: 0
- BASELINE_PRIMARY rows: 130
- RESEARCH_EXTENDED rows: 1,389
- D1 position-day rows: 523
- T1 positive / negative / censored: 633 / 508 / 378
- T2 positive / negative / censored: 421 / 720 / 378
- Fill rate: 75.5102%
- Entry / T1 / T2 censoring rates: 0.0000% / 24.8848% / 24.8848%
- Entry-day ambiguity rate: 48.3213%
- Same-bar ambiguity rate: 0.0000%
- High-missingness feature records: 18
- High-missingness examples: Distance To Support % | Distance To T1 % | Distance To T2 % | Entry High | Entry Low | Initial Risk % | R:R T1 | R:R T2

## Acceptance audits

- Point-in-time prefix audit: PASS
- Signal source parity: PASS
- Candidate outcome parity: PASS
- D1 shadow parity: PASS
- Walk-forward manifest rows / targets / evaluation years: 242 / 22 / 11
- Runtime: 44.02 seconds

## Dataset identities

- `signal_state`: rows=7,356, columns=131, content=`dcb30bad0b5363f4ab325ff107899d694888f83d861bf99d313aa4fdb59688e1`, artifact=`5284a2b5cc645281d30686fc879ab5fb6ccc2d3650e84c30492f26921682f82f`, bytes=2,858,653
- `trade_opportunity`: rows=1,519, columns=236, content=`22cb71f072fd5310b3ee66282c01f39f65f32f83818896693b0380280aeb017c`, artifact=`248c85f62a441491b81f8896e85f424c3bdaf6977f73d7bd76547d9d67e2800a`, bytes=1,058,896
- `d1_position_day`: rows=523, columns=89, content=`3a78e63b3d6f5ab30712bf85facc646ea2ac5b68487833391aa99cd8f0df1154`, artifact=`4577d329964312db9959c80efe5cfc71dd394fe214db599409c261665650b73d`, bytes=150,194

## Required scope declarations

STAGE 2.2.2 FINAL MODIFIED: NO

STAGE 2B MODIFIED: NO

STAGE 2B.1 MODIFIED: NO

STAGE 1 SIGNAL RULES CHANGED: NO

D1 MANAGEMENT RULES CHANGED: NO

ML MODEL TRAINED: NO

FEATURE SELECTION PERFORMED: NO

HYPERPARAMETER TUNING PERFORMED: NO

POINT-IN-TIME DATASET BUILT: YES

WALK-FORWARD SPLIT MANIFEST BUILT: YES

## Known limitations

- Current-universe survivorship bias; the universe is not point-in-time NIFTY membership.
- Historical pseudo-OOS is not prospective unseen data.
- Daily OHLC cannot establish intraday sequence; entry-day and exit-day ambiguity remain explicit.
- Stage 1 retains the known holiday-short weekly delay.
- Costs remain a generic basis-point model.
- D1 evidence and 2024-2026 performance remain historically weak.
- Stage 2B.1 empirical confidence was historically overconfident.
- Sector/index-membership history is not point-in-time.
- No ML model has been validated.
