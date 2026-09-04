# Stage 3.1 Delivery Report

ENGINEERING STATUS: **PASS WITH WARNINGS**

Stage 3.1 hardens dataset semantics only. It does not train a model or change trading logic.

## Reference

- Stage 2B.1 tag: `stage2b.1-dynamic-research-baseline`
- Stage 2B.1 commit: `c9cc9f4fcaf2fe81128365be09515fbf9fa67c28`
- Stage 3 reference branch: `stage3-point-in-time-dataset`
- Stage 3 reference commit: `70951a5a05727a605bb579973da6216fb9887e44`
- Stage 3 reference package hash: `1c06cb7e1345b10ea8b2db65aea02d54468c0da7b816bf48575f169fa8f2a23a`

## Identity

- Stage 3.1 Experiment ID: `S3_1_20110830_20260828_6480f9a2ad30`
- Stage 3.1 code package hash: `094747e51a46db0af0392250a5aeaf7ff9b45bb0fa932b47ab3fcc44221e9bae`
- Config hash: `fec3cb02a0254d1d16f6fdcbf2eab9d15412d226b9ff2a0dba813e84705de9fe`
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

## ML safety

- FEATURE_ALLOWED count: 244
- Date-like FEATURE_ALLOWED count: 0
- Target leakage violations: 0
- Unregistered feature violations: 0
- Registry inconsistencies: 0

## Walk forward

- Targets: 22
- Evaluation years: 11
- Training availability violations: 0

## Determinism

- First-run/previous hashes available: YES
- Repeated-run hash differences: 0
- signal_state::content_hash: first=`e2e7b32856928312be99f65bfcc67f736bbab33e1962a6fb9b7a921447b76ac0`, second=`e2e7b32856928312be99f65bfcc67f736bbab33e1962a6fb9b7a921447b76ac0`, status=PASS
- signal_state::artifact_hash: first=`381c1978de997771b027ea2fa19c260e4c6f0fdaf3d68f27bb6f5512aa79b6dd`, second=`381c1978de997771b027ea2fa19c260e4c6f0fdaf3d68f27bb6f5512aa79b6dd`, status=PASS
- trade_opportunity::content_hash: first=`537bd452f72a4dea8c1056ae558bc15e6895e8513277124a8a1dbc30c8c5a591`, second=`537bd452f72a4dea8c1056ae558bc15e6895e8513277124a8a1dbc30c8c5a591`, status=PASS
- trade_opportunity::artifact_hash: first=`13a590284ee7adb6c5290899198814fda1e1b88df0cae880e2689bab8782b32e`, second=`13a590284ee7adb6c5290899198814fda1e1b88df0cae880e2689bab8782b32e`, status=PASS
- d1_position_day::content_hash: first=`c3be50f0345d487a9b4e76f6894a443fc47a481baaf2b0c3f2f4b042560fdf07`, second=`c3be50f0345d487a9b4e76f6894a443fc47a481baaf2b0c3f2f4b042560fdf07`, status=PASS
- d1_position_day::artifact_hash: first=`40057b0f46d1c33d795c465dcc7ffc289e24bedee9140f2657d0e9f7a74ab855`, second=`40057b0f46d1c33d795c465dcc7ffc289e24bedee9140f2657d0e9f7a74ab855`, status=PASS

## Runtime

- Sanity runtime: 23.29 seconds
- Official runtime: 148.43 seconds
- Deterministic rerun runtime: 148.79 seconds

## Scope declarations

STAGE 2.2.2 FINAL MODIFIED: NO

STAGE 2B MODIFIED: NO

STAGE 2B.1 MODIFIED: NO

STAGE 3 REFERENCE MODIFIED: NO

STAGE 1 SIGNAL RULES CHANGED: NO

OPPORTUNITY ELIGIBILITY RULES CHANGED: NO

D1 MANAGEMENT RULES CHANGED: NO

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

ML READY FOR INDEPENDENT AUDIT: YES

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
