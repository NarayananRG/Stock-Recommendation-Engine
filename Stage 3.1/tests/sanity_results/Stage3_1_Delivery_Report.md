# Stage 3.1 Delivery Report

ENGINEERING STATUS: **PASS WITH WARNINGS**

Stage 3.1 hardens dataset semantics only. It does not train a model or change trading logic.

## Reference

- Stage 2B.1 tag: `stage2b.1-dynamic-research-baseline`
- Stage 2B.1 commit: `c9cc9f4fcaf2fe81128365be09515fbf9fa67c28`
- Stage 3 reference branch: `stage3-point-in-time-dataset`
- Stage 3 reference commit: `70951a5a05727a605bb579973da6216fb9887e44`
- Stage 3 reference package hash: `1c06cb7e1345b10ea8b2db65aea02d54468c0da7b816bf48575f169fa8f2a23a`
- Stage 3.1 pre-metadata-fix reference commit: `515606610f408218b3454e36e11dc262d60ebb8a`
- Current checkout commit at runtime: `515606610f408218b3454e36e11dc262d60ebb8a`
- Final Stage 3.1 commit at runtime: `UNCOMMITTED_HOTFIX_WORKTREE`

## Identity

- Stage 3.1 Experiment ID: `S3_1_20110830_20260828_4bbdb236598d_SANITY`
- Stage 3.1 code package hash: `8747ee0582a7feddf4282e5801dd11e2c20b7085bf54e6629aafc31fc08165cb`
- Config hash: `fd91e59d9e42eb3374e5ae78dd32ffda29b9eccf71290ced445241c89759f008`
- Schema hash: `7e6fb19e0618c70c9ea04300b2825bf674ac14322ab24eb1c958145781a6d2c4`

## Datasets

- Signal rows: 7,356
- Opportunity rows: 1,519
- Filled opportunities: 1,147
- Genuine observed non-fills: 372
- Incomplete entry-window censored rows: 0
- Invalid-risk rows: 6
- BASELINE_PRIMARY rows: 130
- RESEARCH_EXTENDED rows: 1,389
- D1 applicable rows: 105
- D1 position-day rows: 523

## Censoring and applicability

- T1: applicable=1,141, available=1,141, not applicable=378, data-end censored=0
- T2: applicable=1,141, available=1,141, not applicable=378, data-end censored=0

## Conditional time-to-target semantics

- TIME_TO_T1_SESSIONS: available=633, not applicable=886, data-end censored=0, applicable=633, partition violations=0, status=PASS
- TIME_TO_T2_SESSIONS: available=421, not applicable=1,098, data-end censored=0, applicable=421, partition violations=0, status=PASS

## Other censoring and applicability

- FWD 10: applicable=1,141, available=1,141, not applicable=378, data-end censored=0
- FWD 20: applicable=1,141, available=1,141, not applicable=378, data-end censored=0
- FWD 30: applicable=1,141, available=1,141, not applicable=378, data-end censored=0
- FWD 45: applicable=1,141, available=1,141, not applicable=378, data-end censored=0
- FWD 63: applicable=1,141, available=1,141, not applicable=378, data-end censored=0
- D1 shadow: applicable=105, available=105, not applicable=1,414, data-end censored=0

## Parity

- Stage 3 signal parity differences: 0
- Frozen source parity differences: 0
- Opportunity membership differences: 0
- Expected entry semantic changes: 0
- Unexplained entry differences: 0
- Candidate outcome differences: 0
- D1 shadow differences: 0
- Position-day differences: 0
- Stable numerical target differences: 0
- Final feature-value differences: 0
- Final label differences: 0

## Corrected D1 distance metadata

- Stop Distance R classification: CURRENT_MANAGEMENT_STATE
- T1 Distance R classification: CURRENT_MANAGEMENT_STATE
- T2 Distance R classification: CURRENT_MANAGEMENT_STATE
- Registry rows changed: 3

## ML safety

- FEATURE_ALLOWED count: 244
- Date-like FEATURE_ALLOWED count: 0
- Target leakage violations: 0
- Unregistered feature violations: 0
- Registry inconsistencies: 0
- Feature metadata semantic violations: 0

## Reference safety

- Stage 3 reference gate failures: 0
- Stage 3 branch commit check: PASS
- Stage 3 exact-commit directory check: PASS
- Stage 3 artifact/hash gates: PASS

## Walk forward

- Targets: 22
- Evaluation years: 11
- Training availability violations: 0

## Tests

- Total tests: 89
- PASS: 89
- FAIL: 0

## Determinism

- First-run/previous hashes available: NO
- Repeated-run hash differences: 0
- EXPERIMENT_ID: first=`nan`, second=`S3_1_20110830_20260828_4bbdb236598d_SANITY`, status=PASS
- STAGE3_1_CODE_PACKAGE_HASH: first=`nan`, second=`8747ee0582a7feddf4282e5801dd11e2c20b7085bf54e6629aafc31fc08165cb`, status=PASS
- STAGE3_1_CONFIG_HASH: first=`nan`, second=`fd91e59d9e42eb3374e5ae78dd32ffda29b9eccf71290ced445241c89759f008`, status=PASS
- STAGE3_1_SCHEMA_HASH: first=`nan`, second=`7e6fb19e0618c70c9ea04300b2825bf674ac14322ab24eb1c958145781a6d2c4`, status=PASS
- signal_state::content_hash: first=`nan`, second=`a7977baa0a27f8bf3a9e790775f069f9829ca80ffddfde168689e98f0ecb140b`, status=PASS
- signal_state::artifact_hash: first=`nan`, second=`bd5ffaa9751e15d76f03bed414ec3110cd35d174f8bc7e99fbab9dcc4f4d0f4c`, status=PASS
- trade_opportunity::content_hash: first=`nan`, second=`8a0ecb3c99ed9b4d49e0b94abe98f26f20c5d8bb15cb9d3588639efc10923861`, status=PASS
- trade_opportunity::artifact_hash: first=`nan`, second=`55be422b056888e796b955ecf10e356c47188ef75a6d982901ed8337238fe74a`, status=PASS
- d1_position_day::content_hash: first=`nan`, second=`a4a402cf6d680aee6895443c78d2f2b3114d410034fdeaa3fff1027b354b2f87`, status=PASS
- d1_position_day::artifact_hash: first=`nan`, second=`0f9f5fafb8abf5b66f1e670ee177276e44acb335d73b4b0073f28a15c8e49878`, status=PASS

## Runtime

- Sanity runtime: 43.12 seconds
- Official runtime: 0.00 seconds
- Deterministic rerun runtime: 0.00 seconds

## Scope declarations

STAGE 2.2.2 FINAL MODIFIED: NO

STAGE 2B MODIFIED: NO

STAGE 2B.1 MODIFIED: NO

STAGE 3 REFERENCE MODIFIED: NO

STAGE 1 SIGNAL RULES CHANGED: NO

SIGNAL RULES CHANGED: NO

OPPORTUNITY ELIGIBILITY RULES CHANGED: NO

OPPORTUNITY RULES CHANGED: NO

ENTRY EXECUTION RULES CHANGED: NO

ENTRY RULES CHANGED: NO

D1 MANAGEMENT RULES CHANGED: NO

HISTORICAL VALID TARGET VALUES CHANGED: NO

FEATURE VALUES CHANGED: NO

LABEL VALUES CHANGED: NO

ML FEATURE SET CHANGED: NO

ML MODEL TRAINED: NO

FEATURE SELECTION PERFORMED: NO

HYPERPARAMETER TUNING PERFORMED: NO

STRATEGY THRESHOLD TUNING PERFORMED: NO

INCOMPLETE ENTRY WINDOW SEMANTICS FIXED: YES

NOT_APPLICABLE SEPARATED FROM DATA_END_CENSORED: YES

RAW DATE ML FEATURES ALLOWED: NO

FEATURE REGISTRY DATASET-SPECIFIC: YES

FORWARD HORIZON SEMANTICS EXPLICIT: YES

TIME-TO-TARGET CONDITIONAL SEMANTICS EXPLICIT: YES

WALK-FORWARD LABEL AVAILABILITY ENFORCED: YES

TIME_TO_TARGET APPLICABILITY FIXED: YES

FEATURE REGISTRY METADATA TRULY DATASET-SPECIFIC: YES

STAGE 3 EXACT REFERENCE COMMIT VERIFIED: YES

SYNTHETIC D1 CENSOR TEST ADDED: YES

STOP DISTANCE R METADATA FIXED: YES

T1 DISTANCE R METADATA FIXED: YES

T2 DISTANCE R METADATA FIXED: YES

ALL THREE DISTANCE FEATURES CURRENT_MANAGEMENT_STATE: YES

DATE_LIKE FEATURE_ALLOWED COUNT: 0

TARGET LEAKAGE VIOLATIONS: 0

TRAINING AVAILABILITY VIOLATIONS: 0

FINAL STAGE 3.1 READY FOR INDEPENDENT FREEZE AUDIT: YES

FINAL STAGE 3.1 READY FOR FREEZE AUDIT: YES

## Known limitations

- current-universe survivorship bias
- historical pseudo-OOS is not prospective unseen data
- daily OHLC cannot establish intraday sequence
- entry-day intraday-limit ambiguity
- exit-day ambiguity
- holiday-short weekly delay
- generic basis-point cost model
- sector/index membership is not historically point-in-time
- D1 evidence remains historically weak
- recent 2024-2026 performance remains weak
- Stage 2B.1 empirical confidence was historically overconfident
- no ML model has been validated

No Stage 4 model training is authorized or performed.
