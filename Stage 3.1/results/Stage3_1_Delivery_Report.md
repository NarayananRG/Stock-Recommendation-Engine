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

- Stage 3.1 Experiment ID: `S3_1_20110830_20260828_c5f0a101a427`
- Stage 3.1 code package hash: `f694086c2a1a3526465271f5820afde15cd603c4c292ab9bc5e5fc7f1ef4d260`
- Config hash: `6e8e9acd0c2299f7b0529a8240b272483a7394037a87bbadca53d2a1018cad8f`
- Schema hash: `7e6fb19e0618c70c9ea04300b2825bf674ac14322ab24eb1c958145781a6d2c4`

## Datasets

- Signal rows: 68,081
- Opportunity rows: 13,544
- Filled opportunities: 10,337
- Genuine observed non-fills: 3,203
- Incomplete entry-window censored rows: 4
- Invalid-risk rows: 35
- BASELINE_PRIMARY rows: 1,088
- RESEARCH_EXTENDED rows: 12,456
- D1 applicable rows: 828
- D1 position-day rows: 4,350

## Censoring and applicability

- T1: applicable=10,302, available=10,261, not applicable=3,242, data-end censored=41
- T2: applicable=10,302, available=10,256, not applicable=3,242, data-end censored=46

## Conditional time-to-target semantics

- TIME_TO_T1_SESSIONS: available=5,662, not applicable=7,841, data-end censored=41, applicable=5,703, partition violations=0, status=PASS
- TIME_TO_T2_SESSIONS: available=3,382, not applicable=10,116, data-end censored=46, applicable=3,428, partition violations=0, status=PASS

## Other censoring and applicability

- FWD 10: applicable=10,302, available=10,288, not applicable=3,242, data-end censored=14
- FWD 20: applicable=10,302, available=10,255, not applicable=3,242, data-end censored=47
- FWD 30: applicable=10,302, available=10,244, not applicable=3,242, data-end censored=58
- FWD 45: applicable=10,302, available=10,227, not applicable=3,242, data-end censored=75
- FWD 63: applicable=10,302, available=10,212, not applicable=3,242, data-end censored=90
- D1 shadow: applicable=828, available=828, not applicable=12,716, data-end censored=0

## Parity

- Stage 3 signal parity differences: 0
- Frozen source parity differences: 0
- Opportunity membership differences: 0
- Expected entry semantic changes: 1
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

- First-run/previous hashes available: YES
- Repeated-run hash differences: 0
- EXPERIMENT_ID: first=`S3_1_20110830_20260828_c5f0a101a427`, second=`S3_1_20110830_20260828_c5f0a101a427`, status=PASS
- STAGE3_1_CODE_PACKAGE_HASH: first=`f694086c2a1a3526465271f5820afde15cd603c4c292ab9bc5e5fc7f1ef4d260`, second=`f694086c2a1a3526465271f5820afde15cd603c4c292ab9bc5e5fc7f1ef4d260`, status=PASS
- STAGE3_1_CONFIG_HASH: first=`6e8e9acd0c2299f7b0529a8240b272483a7394037a87bbadca53d2a1018cad8f`, second=`6e8e9acd0c2299f7b0529a8240b272483a7394037a87bbadca53d2a1018cad8f`, status=PASS
- STAGE3_1_SCHEMA_HASH: first=`7e6fb19e0618c70c9ea04300b2825bf674ac14322ab24eb1c958145781a6d2c4`, second=`7e6fb19e0618c70c9ea04300b2825bf674ac14322ab24eb1c958145781a6d2c4`, status=PASS
- signal_state::content_hash: first=`ba090d37ab4a487574e6c4c8e507ba569dca75800defe5c172a8d12e9d23eb61`, second=`ba090d37ab4a487574e6c4c8e507ba569dca75800defe5c172a8d12e9d23eb61`, status=PASS
- signal_state::artifact_hash: first=`7cea6d886b8e60b09d738cb87fc2a6ddc9b21130860bb25137c3acef88ed46df`, second=`7cea6d886b8e60b09d738cb87fc2a6ddc9b21130860bb25137c3acef88ed46df`, status=PASS
- trade_opportunity::content_hash: first=`2ac0b34cf7aac28537f5f163df5bddb6f921c355f79cbebb8a295a9002135986`, second=`2ac0b34cf7aac28537f5f163df5bddb6f921c355f79cbebb8a295a9002135986`, status=PASS
- trade_opportunity::artifact_hash: first=`ad9de8f16bf2991edf194c7abecc631e00e6b3ce7c3c9b19de6e1cfb6f7b22c2`, second=`ad9de8f16bf2991edf194c7abecc631e00e6b3ce7c3c9b19de6e1cfb6f7b22c2`, status=PASS
- d1_position_day::content_hash: first=`7874ff8ab1fc7827198ef5969d407d94173721f96d541ecf43df0018e4a05523`, second=`7874ff8ab1fc7827198ef5969d407d94173721f96d541ecf43df0018e4a05523`, status=PASS
- d1_position_day::artifact_hash: first=`e4ea660e22f6a4847494d406081de399602edea1ffa86ce2df98df45a2e32690`, second=`e4ea660e22f6a4847494d406081de399602edea1ffa86ce2df98df45a2e32690`, status=PASS

## Runtime

- Sanity runtime: 30.54 seconds
- Official runtime: 184.32 seconds
- Deterministic rerun runtime: 188.34 seconds

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
