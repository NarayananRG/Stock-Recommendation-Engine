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

- Stage 3.1 Experiment ID: `S3_1_20110830_20260828_6480f9a2ad30_SANITY`
- Stage 3.1 code package hash: `094747e51a46db0af0392250a5aeaf7ff9b45bb0fa932b47ab3fcc44221e9bae`
- Config hash: `fec3cb02a0254d1d16f6fdcbf2eab9d15412d226b9ff2a0dba813e84705de9fe`
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

- First-run/previous hashes available: NO
- Repeated-run hash differences: 0
- signal_state::content_hash: first=`nan`, second=`32fe10d823791c0b5f80c5c2d558f81e0ad1172233fb6098ee2833f6c9d476e0`, status=PASS
- signal_state::artifact_hash: first=`nan`, second=`6e6be0ee52a2f9a2e0ac7a0df71776006e28748fb610b9ca959f8cce03296d62`, status=PASS
- trade_opportunity::content_hash: first=`nan`, second=`4203b5727b54ccbd53255e5ded97c5a24bbbc27c1a95f7705e9743d9f5cb93c8`, status=PASS
- trade_opportunity::artifact_hash: first=`nan`, second=`1066e2bd4ffa3e43ddf749849b9ac79cf41cdbbe1b8e99bde26730b189f852d4`, status=PASS
- d1_position_day::content_hash: first=`nan`, second=`8492fcebcea3df31767b0407322c83abbf17fd64b5f8588869ce21a1e32c5727`, status=PASS
- d1_position_day::artifact_hash: first=`nan`, second=`1c8003d59f1563efcd9a9c826e83ed3ffeefa2166fe606df40af0ccb28ad9cc0`, status=PASS

## Runtime

- Sanity runtime: 23.29 seconds
- Official runtime: 0.00 seconds
- Deterministic rerun runtime: 0.00 seconds

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
