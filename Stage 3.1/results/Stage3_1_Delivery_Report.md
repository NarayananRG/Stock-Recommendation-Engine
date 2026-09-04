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

- Stage 3.1 Experiment ID: `S3_1_20110830_20260828_4bbdb236598d`
- Stage 3.1 code package hash: `8747ee0582a7feddf4282e5801dd11e2c20b7085bf54e6629aafc31fc08165cb`
- Config hash: `fd91e59d9e42eb3374e5ae78dd32ffda29b9eccf71290ced445241c89759f008`
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

- First-run/previous hashes available: YES
- Repeated-run hash differences: 0
- EXPERIMENT_ID: first=`S3_1_20110830_20260828_4bbdb236598d`, second=`S3_1_20110830_20260828_4bbdb236598d`, status=PASS
- STAGE3_1_CODE_PACKAGE_HASH: first=`8747ee0582a7feddf4282e5801dd11e2c20b7085bf54e6629aafc31fc08165cb`, second=`8747ee0582a7feddf4282e5801dd11e2c20b7085bf54e6629aafc31fc08165cb`, status=PASS
- STAGE3_1_CONFIG_HASH: first=`fd91e59d9e42eb3374e5ae78dd32ffda29b9eccf71290ced445241c89759f008`, second=`fd91e59d9e42eb3374e5ae78dd32ffda29b9eccf71290ced445241c89759f008`, status=PASS
- STAGE3_1_SCHEMA_HASH: first=`7e6fb19e0618c70c9ea04300b2825bf674ac14322ab24eb1c958145781a6d2c4`, second=`7e6fb19e0618c70c9ea04300b2825bf674ac14322ab24eb1c958145781a6d2c4`, status=PASS
- signal_state::content_hash: first=`5876e3629cb609eed16f776d035ff9c13e3c6947dee5c2ecb4e846c8b18f74bd`, second=`5876e3629cb609eed16f776d035ff9c13e3c6947dee5c2ecb4e846c8b18f74bd`, status=PASS
- signal_state::artifact_hash: first=`d6bc491d29497f9c8547a8e85de337c437a2a5df6957c42ec4e0267b9a023bc7`, second=`d6bc491d29497f9c8547a8e85de337c437a2a5df6957c42ec4e0267b9a023bc7`, status=PASS
- trade_opportunity::content_hash: first=`3da733b3f1a9fa03c107c960495690290e7fe065901e4f0822c2905ba62d11d5`, second=`3da733b3f1a9fa03c107c960495690290e7fe065901e4f0822c2905ba62d11d5`, status=PASS
- trade_opportunity::artifact_hash: first=`151fc5da4b3c4006c8b7a7c03c9ddfe0b453cd2b070993fda7c24a963008ba91`, second=`151fc5da4b3c4006c8b7a7c03c9ddfe0b453cd2b070993fda7c24a963008ba91`, status=PASS
- d1_position_day::content_hash: first=`8e095d8cfd5bbca523881956b18283d36677e13d58dacee9048cea43252284b6`, second=`8e095d8cfd5bbca523881956b18283d36677e13d58dacee9048cea43252284b6`, status=PASS
- d1_position_day::artifact_hash: first=`36dcebe9d5127e25a93a0d64b8ac896be56db941402ff7c040212b07d6830559`, second=`36dcebe9d5127e25a93a0d64b8ac896be56db941402ff7c040212b07d6830559`, status=PASS

## Runtime

- Sanity runtime: 43.12 seconds
- Official runtime: 243.33 seconds
- Deterministic rerun runtime: 222.03 seconds

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
