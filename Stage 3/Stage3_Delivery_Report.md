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

- Experiment ID: `S3_20110830_20260828_bb15e0fa65d2`
- Code package hash: `1c06cb7e1345b10ea8b2db65aea02d54468c0da7b816bf48575f169fa8f2a23a`
- Config hash: `1cf258801142c74f33246bed6492ab87adfd1377dcdec0641092098d329e009e`
- Combined schema hash: `2165f7083fce198f60941080a794f4136e522012bd3ac79120d255a14a6332e8`

## Dataset research findings (descriptive only)

- Signal-state rows: 68,081
- Opportunity rows: 13,544
- Filled opportunities: 10,337
- Observed non-filled opportunities: 3,204
- Entry-censored opportunities: 3
- BASELINE_PRIMARY rows: 1,088
- RESEARCH_EXTENDED rows: 12,456
- D1 position-day rows: 4,350
- T1 positive / negative / censored: 5,662 / 4,599 / 3,283
- T2 positive / negative / censored: 3,382 / 6,874 / 3,288
- Fill rate: 76.3385%
- Entry / T1 / T2 censoring rates: 0.0222% / 24.2395% / 24.2764%
- Entry-day ambiguity rate: 52.8057%
- Same-bar ambiguity rate: 0.0960%
- High-missingness feature records: 18
- High-missingness examples: Distance To Support % | Distance To T1 % | Distance To T2 % | Entry High | Entry Low | Initial Risk % | R:R T1 | R:R T2

## Acceptance audits

- Point-in-time prefix audit: PASS
- Signal source parity: PASS
- Candidate outcome parity: PASS
- D1 shadow parity: PASS
- Walk-forward manifest rows / targets / evaluation years: 242 / 22 / 11
- Runtime: 323.29 seconds

## Dataset identities

- `signal_state`: rows=68,081, columns=131, content=`672fd6774e680657849a8186e8f2b6f6b1fc900177df1a46bc2dbb671e77f029`, artifact=`7fda3223b650de51708faa965bb607be8140bc6d50e5cb13fd877f01c0c32049`, bytes=25,857,618
- `trade_opportunity`: rows=13,544, columns=236, content=`50cc88c93d4f5624d500335adf96c323429313375225506d14b26f5d312795cf`, artifact=`abfd428823c0d384b03eaa81132871fe9936cdf4ffbcb7696a060e461ac56f0b`, bytes=8,675,382
- `d1_position_day`: rows=4,350, columns=89, content=`f01a685d82a65261e81e0ab77f7ceca6f5f8f7d93c9267fc8f345f2fbc7b2b39`, artifact=`b4847daf5486b45c35aa242a71121d083978f65e595c57036c9bf3ed11fcfef7`, bytes=1,139,387

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
