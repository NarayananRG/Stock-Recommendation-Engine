# NextGen Second Synthetic Challenger Robustness Report

## 1. Executive summary

EXP2 completed as the second and final bounded synthetic challenger experiment.  It evaluates robustness and model-family selection across 10 harder synthetic scenarios, 10 preregistered seeds, two sample-size regimes, and four existing simple model families.  Experiment classification: `SYNTHETIC_ROBUSTNESS_VALIDATED_WITH_LIMITATIONS`.  Family-selection result: `SIMPLE_CHALLENGER_LOGISTIC_PREFERRED`.

## 2. EXP1 dependency

EXP2 starts from EXP1 evidence `NEXTGEN_SYNTHETIC_CHALLENGER_EXP1_68BF5571B15AE4D7` and does not regenerate or overwrite EXP1 artifacts.

## 3. Synthetic-only statement

All EXP2 model training and evaluation use deterministic synthetic panels only.  No NSE, NIFTY, Stage 4A.3, Stage 5D, Stage 6, MCP, live-market, prospective, or restricted official-market dataset was used for training.

## 4. Rights status

Real-data rights remain `LICENSE_REQUIRED`.  Real-data model training remains `BLOCKED`.

## 5. Experiment specification

Specification hash: `b652cefaa6316720cd8ac0a81db70e0e71c13797c93f91e42006078f85a35ace`.  Experiment ID: `NEXTGEN_SYNTHETIC_CHALLENGER_EXP2_B652CEFAA6316720`.

## 6. Scenario definitions

- `NULL_NO_SIGNAL_V2`: No true predictive relationship.
- `STABLE_LINEAR_WEAK`: Persistent modest linear signal.
- `STABLE_NONLINEAR_INTERACTION`: Material nonlinear interactions.
- `GRADUAL_REGIME_DRIFT`: Feature/outcome relation changes gradually through time.
- `ABRUPT_REGIME_BREAK`: Useful relation becomes invalid after a structural break.
- `SPURIOUS_DEVELOPMENT_SIGNAL`: Development-period signal disappears in final test.
- `HIGH_NOISE_LOW_SIGNAL`: Very low signal-to-noise ratio.
- `CROSS_SECTIONAL_RELATIVE_SIGNAL`: Primarily within-session relative signal.
- `CALIBRATION_STRESS`: Ranking useful while calibration is intentionally difficult.
- `REDUNDANT_CORRELATED_FEATURES`: Correlated features represent the same underlying signal.

## 7. Seeds

`[11, 29, 47, 83, 101, 131, 167, 211, 257, 307]`

## 8. Dataset/sample-size design

Sample regimes: `['SMALL_RESEARCH_SAMPLE', 'LARGER_RESEARCH_SAMPLE']`.  Row-level datasets are reproducible from synthetic generator configuration and are not committed.

## 9. Temporal partitioning

Strict chronological TRAIN / VALIDATION / FINAL TEST partitions were used with an embargo.  No shuffled split was used.

## 10. Fixed model configurations

Only deterministic/reference, logistic regression, random forest, and gradient boosting were evaluated.  No hyperparameter search, AutoML, neural network, or final-test tuning was performed.

## 11. Predictive results

Predictive metrics were collected for validation and final test: ROC-AUC, PR-AUC, Brier score, Brier baseline, and Brier skill.  Undefined metrics remain explicit.

## 12. Cross-sectional ranking results

IC, Rank IC, Precision@K, and Top-K synthetic relative-return diagnostics were measured.  These remain synthetic diagnostics, not expected market returns.

## 13. Synthetic economic diagnostics

Top-5/Top-10/Top-20 and percentage Top-K synthetic forward-return diagnostics were computed on synthetic outcomes only.

## 14. Seed stability

The summary artifact reports mean, median, standard deviation, minimum, maximum, interquartile range, valid/undefined run counts, and sign consistency by scenario/sample-size/model.

## 15. Validation→final-test degradation

Conclusion: `DEGRADATION_MEASURED_AND_PENALIZED`.  Degradation was measured for ROC-AUC, Rank IC, Top-5 relative synthetic return, and Brier skill.

## 16. Null false-positive control

Result: `NULL_FALSE_POSITIVE_CONTROL_PASS`.

## 17. Spurious-signal control

Result: `SPURIOUS_SIGNAL_GENERALIZATION_FAILURE_RECOGNIZED`.  Development-period superiority is not credited when final-test generalization fails.

## 18. Regime robustness

Result: `REGIME_SCENARIOS_SHOW_EXPECTED_DEGRADATION`.  Fixed challengers are not dynamically adapted during final test.

## 19. Ranking-vs-classification analysis

Conclusion: `RANKING_AND_CLASSIFICATION_CAN_DISAGREE_BY_SCENARIO`.  EXP2 treats ranking evidence separately from binary classification evidence.

## 20. Calibration analysis

Conclusion: `CALIBRATION_STRESS_SEPARATES_RANKING_FROM_PROBABILITY_QUALITY`.  Useful ranking does not imply trustworthy probabilities.

## 21. Ablation V2

Conclusion: `SIGNAL_FEATURE_REMOVAL_REDUCES_SYNTHETIC_EVIDENCE`.  Mean full-minus-signal-removed Top-5 synthetic relative-return delta: `0.000852`.

## 22. Complexity assessment

The preregistered hierarchy penalizes complexity: LOGISTIC_REGRESSION < RANDOM_FOREST < GRADIENT_BOOSTING.  More complex models require material, repeated, robust incremental value.

## 23. Model-family profiles

- `DETERMINISTIC_REFERENCE`: strengths=['transparent baseline']; weaknesses=['not a challenger']; failure_modes=['misses nonlinear and drift-specific patterns']; complexity=lowest
- `LOGISTIC_REGRESSION`: strengths=['least complex challenger', 'interpretable fixed configuration']; weaknesses=['limited nonlinear capacity']; failure_modes=['interaction-heavy scenarios']; complexity=low
- `RANDOM_FOREST`: strengths=['bounded nonlinear capacity']; weaknesses=['less transparent than logistic']; failure_modes=['spurious development structure']; complexity=medium
- `GRADIENT_BOOSTING`: strengths=['strong nonlinear ranking candidate']; weaknesses=['highest complexity among allowed families']; failure_modes=['overconfident validation under spurious signals']; complexity=highest

## 24. Model-family selection

Selection: `SIMPLE_CHALLENGER_LOGISTIC_PREFERRED`.  This is a research-family selection only and does not authorize real-data training, production promotion, trading, or replacement of any active model.

## 25. Limitations

EXP2 is synthetic-only.  It cannot prove real alpha, real profitability, real-market calibration, or production readiness.

## 26. What EXP2 proves

It proves the controlled synthetic robustness pipeline can compare simple model families under harder deterministic scenarios and produce reproducible compact evidence.

## 27. What EXP2 does NOT prove

It does not prove that any model will make money, should trade, should replace the active model, or is ready for production.

## 28. Rights/provenance status

Rights remain `LICENSE_REQUIRED` and real-data training remains `BLOCKED`.

## 29. Frozen-lane integrity

Stage 4A.3, Stage 5D, and Stage 6 are not modified by EXP2.

## 30. Recommended next research action

Stop synthetic model-family experiments.  If real-data training rights remain blocked, the blocker is rights availability.  If rights become available later, use the selected simple family only as a candidate for a separately authorized first real-data challenger experiment.
