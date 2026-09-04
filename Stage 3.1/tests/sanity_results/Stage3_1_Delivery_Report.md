# Stage 3.1 Delivery Report

ENGINEERING STATUS: **PASS WITH WARNINGS**

Stage 3.1 hardens dataset semantics only. It does not train a model or change trading logic.

## Reference

- Stage 2B.1 tag: `stage2b.1-dynamic-research-baseline`
- Stage 2B.1 commit: `c9cc9f4fcaf2fe81128365be09515fbf9fa67c28`
- Stage 3 reference branch: `stage3-point-in-time-dataset`
- Stage 3 reference commit: `70951a5a05727a605bb579973da6216fb9887e44`
- Stage 3 reference package hash: `1c06cb7e1345b10ea8b2db65aea02d54468c0da7b816bf48575f169fa8f2a23a`
- Stage 3.1 pre-hotfix reference commit: `fc2d45888a8c80fdf724accb676e6748c1abcf08`
- Current checkout commit at runtime: `fc2d45888a8c80fdf724accb676e6748c1abcf08`
- Final Stage 3.1 commit at runtime: `UNCOMMITTED_HOTFIX_WORKTREE`

## Identity

- Stage 3.1 Experiment ID: `S3_1_20110830_20260828_c5f0a101a427_SANITY`
- Stage 3.1 code package hash: `f694086c2a1a3526465271f5820afde15cd603c4c292ab9bc5e5fc7f1ef4d260`
- Config hash: `6e8e9acd0c2299f7b0529a8240b272483a7394037a87bbadca53d2a1018cad8f`
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

- Total tests: 73
- PASS: 73
- FAIL: 0

## Determinism

- First-run/previous hashes available: NO
- Repeated-run hash differences: 0
- EXPERIMENT_ID: first=`nan`, second=`S3_1_20110830_20260828_c5f0a101a427_SANITY`, status=PASS
- STAGE3_1_CODE_PACKAGE_HASH: first=`nan`, second=`f694086c2a1a3526465271f5820afde15cd603c4c292ab9bc5e5fc7f1ef4d260`, status=PASS
- STAGE3_1_CONFIG_HASH: first=`nan`, second=`6e8e9acd0c2299f7b0529a8240b272483a7394037a87bbadca53d2a1018cad8f`, status=PASS
- STAGE3_1_SCHEMA_HASH: first=`nan`, second=`7e6fb19e0618c70c9ea04300b2825bf674ac14322ab24eb1c958145781a6d2c4`, status=PASS
- signal_state::content_hash: first=`nan`, second=`93e30ee312f13c219573aeffd6df713452f4d4c12dbfceabfa6c1e4b9784f132`, status=PASS
- signal_state::artifact_hash: first=`nan`, second=`58eccae40efcee9aba345e0af80877909ede9ad1fe551a36bade6d7b22bc6c7d`, status=PASS
- trade_opportunity::content_hash: first=`nan`, second=`cdba644620a58f4b3a3dca207715da1a709735fb212de8cccf8f9b89d1d5bee4`, status=PASS
- trade_opportunity::artifact_hash: first=`nan`, second=`0bdea9f80fe51310c5505cc62146ef7ccb1e898a59a8fab9961dbfa58d3f609e`, status=PASS
- d1_position_day::content_hash: first=`nan`, second=`3fe2312817f151a58a904c938c706f548b3dec3075847a968980bf94f02bc7d3`, status=PASS
- d1_position_day::artifact_hash: first=`nan`, second=`e818d4e95e05afb603caee39bc13e83ba9d82c05c372dcffec9c55f511ba5b98`, status=PASS

## Runtime

- Sanity runtime: 30.54 seconds
- Official runtime: 0.00 seconds
- Deterministic rerun runtime: 0.00 seconds

## Scope declarations

STAGE 2.2.2 FINAL MODIFIED: NO

STAGE 2B MODIFIED: NO

STAGE 2B.1 MODIFIED: NO

STAGE 3 REFERENCE MODIFIED: NO

STAGE 1 SIGNAL RULES CHANGED: NO

OPPORTUNITY ELIGIBILITY RULES CHANGED: NO

ENTRY EXECUTION RULES CHANGED: NO

D1 MANAGEMENT RULES CHANGED: NO

HISTORICAL VALID TARGET VALUES CHANGED: NO

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

DATE_LIKE FEATURE_ALLOWED COUNT: 0

TARGET LEAKAGE VIOLATIONS: 0

TRAINING AVAILABILITY VIOLATIONS: 0

FINAL STAGE 3.1 READY FOR INDEPENDENT FREEZE AUDIT: YES

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
