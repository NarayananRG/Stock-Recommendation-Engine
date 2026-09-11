# Stage 4A.2 Delivery Report

## Status and scope

Engineering status: **PASS WITH WARNINGS**.

This experiment was designed after Stage 4A and Stage 4A.1 results were observed. It is a pre-registered follow-up robustness/economic-utility study, not a new untouched historical holdout.

No model was trained, recalibrated, tuned, or selected. The experiment used only frozen pseudo-OOS predictions, fixed same-date K values of 1 and 2, the frozen D1 `TRAIL_ONLY` engine as primary, and frozen D0 `STATIC_COMPAT` as sensitivity. Results are historical research, not a live or paper-trading recommendation.

Experiment ID: `S4A2_20160101_20260828_022dc86ab7df`

Stage 4A.2 package hash: `0da2a240880b70701f87067c6d355cff7607de9a86dd60d0d42a8fdbbfd39b33`

## Primary D1 results

Bootstrap columns are paired policy-minus-R0_K terminal-return deltas from the primary 63-session moving-block bootstrap. Random percentile is within the same-K label-blind random-selection distribution.

| Policy | K | Trades | Return % | CAGR % | Max DD % | Expectancy R | PF | Avg exposure % | Δ return vs R0 | Bootstrap 2.5% | Median | 97.5% | Random percentile | 2024–26 Δ return | Classification |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| R0_K1 | 1 | 249 | 15.05 | 1.32 | -8.51 | 0.073 | 1.223 | 9.59 | — | — | — | — | 23.4% | — | Control |
| R1_K1 | 1 | 241 | 16.86 | 1.47 | -9.83 | 0.083 | 1.263 | 9.53 | +1.81 | -9.38 | +1.60 | +14.14 | 37.6% | +2.70 | WEAK POSITIVE ECONOMIC UTILITY |
| R2_K1 | 1 | 240 | 18.71 | 1.62 | -10.17 | 0.096 | 1.289 | 9.57 | +3.66 | -6.82 | +3.56 | +16.41 | 55.2% | +2.80 | WEAK POSITIVE ECONOMIC UTILITY |
| R3_K1 | 1 | 249 | 22.41 | 1.92 | -9.97 | 0.111 | 1.329 | 9.64 | +7.36 | -3.78 | +7.64 | +21.73 | 81.8% | +2.19 | WEAK POSITIVE ECONOMIC UTILITY |
| R4_K1 | 1 | 249 | 19.97 | 1.72 | -10.41 | 0.102 | 1.297 | 9.61 | +4.91 | -5.35 | +4.95 | +17.48 | 64.2% | +1.95 | WEAK POSITIVE ECONOMIC UTILITY |
| R5_K1 | 1 | 250 | 16.29 | 1.43 | -12.16 | 0.074 | 1.236 | 9.49 | +1.24 | -12.23 | +1.23 | +15.79 | 32.6% | +2.03 | Diagnostic only |
| R0_K2 | 2 | 275 | 22.09 | 1.89 | -10.20 | 0.095 | 1.294 | 10.65 | — | — | — | — | 84.0% | — | Control |
| R1_K2 | 2 | 276 | 19.99 | 1.72 | -12.32 | 0.086 | 1.267 | 10.71 | -2.10 | -10.70 | -2.03 | +5.68 | 49.2% | +0.20 | NO ECONOMIC UTILITY |
| R2_K2 | 2 | 277 | 19.39 | 1.68 | -12.36 | 0.082 | 1.259 | 10.71 | -2.69 | -11.03 | -2.64 | +4.84 | 37.6% | +0.25 | NO ECONOMIC UTILITY |
| R3_K2 | 2 | 278 | 17.93 | 1.56 | -12.27 | 0.076 | 1.240 | 10.59 | -4.15 | -12.60 | -4.16 | +3.11 | 15.6% | +0.19 | NO ECONOMIC UTILITY |
| R4_K2 | 2 | 279 | 19.85 | 1.71 | -12.75 | 0.085 | 1.259 | 10.64 | -2.24 | -8.59 | -2.26 | +4.17 | 46.8% | +0.21 | NO ECONOMIC UTILITY |
| R5_K2 | 2 | 280 | 20.69 | 1.78 | -11.35 | 0.088 | 1.270 | 10.85 | -1.40 | -4.59 | -1.26 | +1.34 | 59.6% | +0.21 | Diagnostic only |

`ALL_BASELINE_PRIMARY` reproduced the frozen D1 reference exactly: 285 trades, ₹120,093.4081866442 ending equity, and +20.093408% total return. D0 reproduced 225 trades, ₹106,745.3097689061 ending equity, and +6.745310% total return.

## Random same-gate controls

| K | Metric | 2.5% | Median | 97.5% |
|---:|---|---:|---:|---:|
| 1 | Total Return % | 10.03 | 18.03 | 27.78 |
| 1 | Expectancy R | 0.048 | 0.087 | 0.135 |
| 1 | Profit Factor | 1.155 | 1.272 | 1.407 |
| 2 | Total Return % | 16.04 | 20.03 | 24.17 |
| 2 | Expectancy R | 0.067 | 0.086 | 0.103 |
| 2 | Profit Factor | 1.213 | 1.263 | 1.314 |

No R1–R4 policy reached the preregistered 95th percentile for total return. The highest was R3_K1 at 81.8%. The 500 seeds per K are label-blind selection references, not independent market histories.

## Selection attribution

K=1 produced meaningful membership changes: R1–R4 replaced 62–67 rule-selected Signal IDs. Their ML-only filled-trade mean Net R exceeded the corresponding rule-only set, especially R3 and R4, but this diagnostic does not overcome the bootstrap and random-control failures. K=2 changed only 12–15 selected Signal IDs, and the rule-only filled trades had higher mean Net R than the ML-only trades for every R1–R4 K=2 comparison.

No post-hoc filter was applied.

## Fill model economic diagnostic

| Comparison | Fill-rate Δ | Trade-count Δ | Exposure Δ | Capital-reject Δ | Return Δ | Expectancy Δ |
|---|---:|---:|---:|---:|---:|---:|
| R5_K1 − R0_K1 | +0.17 pp | +1 | -0.10 pp | 0 | +1.24 pp | +0.0014 R |
| R5_K2 − R0_K2 | +0.68 pp | +5 | +0.20 pp | 0 | -1.40 pp | -0.0064 R |

The frozen fill model modestly improved entry capture, most clearly at K=2, but that improvement did not improve profitability at K=2 and was not statistically persuasive at K=1.

**Higher fill probability is not equivalent to higher expected profitability.**

## D1 versus static D0

The sign of each R1–R4 return delta versus its same-K R0 comparator was the same under D1 and D0: positive for all K=1 policies and negative for all K=2 policies. No result is flagged `EXIT-POLICY DEPENDENT` by sign reversal. The magnitude remains sensitive to exit policy, and D0 is a sensitivity analysis rather than part of the formal robust criterion.

## Exposure-matched diagnostic

The added exposure-matched summary uses only prior-session (`t-1`) exposure, caps the scale at 1, and never uses same-day exposure. For every R1–R5/K policy, actual ML return was below its prior-session exposure-matched R0 comparator; differences ranged from -3.44 percentage points (R3_K1) to -8.38 percentage points (R5_K2). This is diagnostic only and does not enter the evidence classification.

## Realized PnL and target diagnostics

Daily `Realized PnL` is now the frozen trade ledger's Net PnL aggregated on true Exit Date, with zero on sessions without an exit. Equity and Daily Return were not changed, and all daily realized values reconcile exactly to closed-trade Net PnL.

D1 exposes full-bar MFE but no authoritative within-bar target-before-stop event. Its fields are therefore labelled `T1 Price Touched` and `T2 Price Touched`, with semantics `FULL_BAR_PRICE_TOUCH_NON_CONSERVATIVE_STOP_FIRST_AMBIGUITY`; they are not presented as conservative target success. D0 uses the authoritative frozen STOP_FIRST outcome labels and retains reached semantics. Diagnostic counts did not change: across the 13 named policies, D1 totals remain T1=698 and T2=474, while D0 totals remain T1=1,049 and T2=787. Only the semantic labels were corrected.

## Research questions

1. **Does T1 ML ranking improve economics over rule ranking?** Point estimates improve for R1/R2 at K=1, but not at K=2 and not with robust uncertainty evidence.
2. **Does JOINT_T1 ranking improve economics?** R3/R4 improve K=1 point estimates; R3_K1 is strongest, but it is not robust and both ranks underperform at K=2.
3. **Are improvements credible under 63-session uncertainty?** No. Every paired terminal-return 2.5% bound is below zero.
4. **Do they beat label-blind random same-K selection?** No policy reaches the required 95th total-return percentile.
5. **Do results persist in 2024–2026?** All R1–R4 recent deltas are non-negative, but recent trade expectancy is modest and the overall system remains weak in this period.
6. **Do results survive D0 sensitivity?** The direction survives: K=1 positive, K=2 negative. This does not make the result robust.
7. **Does fill prediction improve execution efficiency?** Modestly, especially for R5_K2 (+0.68 percentage-point fill rate and five trades).
8. **Does fill efficiency improve profitability?** Not consistently; R5_K2 has lower return and expectancy than R0_K2.
9. **Is evidence sufficient to justify an ML-hybrid backtest stage?** No. The frozen rankings do not demonstrate robust positive economic utility under the preregistered standards.

No policy meets `ROBUST POSITIVE ECONOMIC UTILITY`. The observed K=1 benefit appears potentially target-ranking driven, but it is not distinguishable from overlap-aware uncertainty or same-gate random selection. The overall conclusion is **NO DEMONSTRATED ROBUST ECONOMIC UTILITY**.

## Determinism and validation

Two complete official experiments were run. All 30 behavioral/research artifacts compared under stable keys have zero logical differences. Nonnumeric and integer fields match exactly; float differences are checked at an absolute tolerance of 1e-6 and the largest observed raw difference was below 1.0e-9. Behavioral logical differences: **0**.

The initial output-manifest byte difference was non-behavioral: Run 1 contained the separately generated unit-test CSV at manifest creation time, while clean Run 2 did not. The final manifest was rebuilt after all deliverables, and the difference is explicitly excluded from behavioral determinism.

Executable tests: **173 passed, 0 failed**.

## Limitations and warnings

- Current-universe survivorship bias and non-point-in-time historical membership limitations remain.
- This is historical pseudo-OOS research; Stage 4A and Stage 4A.1 had already been inspected, so Stage 4A.2 is not untouched.
- Generic cost and slippage assumptions remain.
- Daily OHLC ordering, entry-day ambiguity, and exit-day ambiguity remain.
- Recent deterministic weakness and the limited executable-cohort sample remain important.
- ML probability calibration remains inadequate.
- Conditional T1 evidence is weak, not robust; conditional T2 evidence is not robust.
- No prospective paper trading has occurred; prospective paper trading is still required later.

## Final declarations

STAGE 2.2.2 FINAL MODIFIED: NO  
STAGE 2B MODIFIED: NO  
STAGE 2B.1 MODIFIED: NO  
STAGE 3 MODIFIED: NO  
STAGE 3.1 MODIFIED: NO  
STAGE 4A MODIFIED: NO  
STAGE 4A.1 MODIFIED: NO  

STAGE 4A.1 FROZEN TAG VERIFIED: YES  

ML MODEL TRAINED IN STAGE 4A.2: NO  
FROZEN OOS PREDICTIONS USED: YES  
BASELINE_PRIMARY DEFINITION CHANGED: NO  
FEATURE SELECTION PERFORMED: NO  
HYPERPARAMETER SEARCH PERFORMED: NO  
PROBABILITY THRESHOLD SEARCH PERFORMED: NO  
PROBABILITY CALIBRATION PERFORMED: NO  

DAILY K VALUES TESTED: 1,2  
OTHER K VALUES TESTED: NO  
T2 ML USED FOR RANKING: NO  
ML POSITION SIZING USED: NO  
ML STOP CHANGES USED: NO  
ML TARGET CHANGES USED: NO  
ML EXIT CHANGES USED: NO  

D1 FROZEN PORTFOLIO ENGINE USED: YES  
D0 STATIC SENSITIVITY USED: YES  
LABEL_BLIND RANDOM CONTROLS USED: YES  
RANDOM SEEDS PER K: 500  
63_SESSION ECONOMIC BLOCK BOOTSTRAP USED: YES  
BOOTSTRAP REPLICATES: 2000  
BOOTSTRAP SEED: 42  

ML TRADING STRATEGY DEPLOYED: NO  
MODEL SELECTED FOR PRODUCTION: NO  
STAGE 5 IMPLEMENTED: NO  
LIVE RECOMMENDATION GENERATED: NO  

READY FOR INDEPENDENT STAGE 4A.2 AUDIT: YES

CORE ECONOMIC RESULTS CHANGED: NO
EXPECTED: NO

CANDIDATE MEMBERSHIP CHANGED: NO
EXPECTED: NO

PORTFOLIO RETURNS CHANGED: NO
EXPECTED: NO

RANDOM CONTROL RESULTS CHANGED: NO
EXPECTED: NO

BOOTSTRAP ECONOMIC RESULTS CHANGED: NO
EXPECTED: NO

EVIDENCE CLASSIFICATION LABELS CHANGED: YES
REALIZED PNL DIAGNOSTIC CORRECTED: YES
T1/T2 DIAGNOSTIC SEMANTICS VERIFIED: YES
NO POLICY MEETS ROBUST POSITIVE ECONOMIC UTILITY: YES
READY FOR FINAL INDEPENDENT STAGE 4A.2 FREEZE AUDIT: YES
