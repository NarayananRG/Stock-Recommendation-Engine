# Stage 2B.1 Delivery Report

ENGINEERING STATUS: PASS

Stage 2B.1 audits and reports the accepted Stage 2B post-entry policies. The Stage 2.1 entry engine, Stage 2.2.2 Final baseline, and accepted Stage 2B trading outputs were not modified.

## 1. Files created

- `README.md`
- `requirements.txt`
- `Stage2B_1_Delivery_Report.md`
- `config/stage2b_1_policy_config.json`
- `stage2b/Stock_Alert_Stage2B_1_Dynamic_Management.py`
- `stage2b/policies.py`, `calibration.py`, `validation.py`, `diagnostics.py`, `hashing.py`
- `tests/run_stage2b_1_tests.py`
- `results/Stage2B_1_Delivery_Report.md`
- `results/stage2b_1_calibration_buckets.csv`
- `results/stage2b_1_calibration_predictions.csv.gz`
- `results/stage2b_1_calibration_quality.csv`
- `results/stage2b_1_cost_sensitivity.csv`
- `results/stage2b_1_d0_static_compatibility_differences.csv`
- `results/stage2b_1_d0_static_compatibility_summary.csv`
- `results/stage2b_1_daily_equity_D1_TRAIL_ONLY.csv.gz`
- `results/stage2b_1_daily_equity_D2_BREAK_EVEN_TRAIL.csv.gz`
- `results/stage2b_1_daily_equity_D3_PARTIAL_T1_TRAIL.csv.gz`
- `results/stage2b_1_daily_equity_D4_TREND_PROTECT.csv.gz`
- `results/stage2b_1_daily_equity_D5_RESISTANCE_TIGHTEN.csv.gz`
- `results/stage2b_1_daily_equity_D6_HYBRID_DYNAMIC.csv.gz`
- `results/stage2b_1_daily_management_log.csv.gz`
- `results/stage2b_1_daily_position_state.csv.gz`
- `results/stage2b_1_data_integrity_post_run.csv`
- `results/stage2b_1_data_integrity_pre_run.csv`
- `results/stage2b_1_diagnostic_integration_tests.csv`
- `results/stage2b_1_drawdown_summary.csv`
- `results/stage2b_1_environment_report.json`
- `results/stage2b_1_exit_leg_log.csv.gz`
- `results/stage2b_1_experiment_identity.json`
- `results/stage2b_1_exposure_matched_benchmarks.csv`
- `results/stage2b_1_exposure_summary.csv`
- `results/stage2b_1_opportunity_recycling_summary.csv`
- `results/stage2b_1_order_log.csv.gz`
- `results/stage2b_1_paired_entry_summary.csv`
- `results/stage2b_1_paired_entry_trade_comparison.csv.gz`
- `results/stage2b_1_partial_profit_summary.csv`
- `results/stage2b_1_period_summary.csv`
- `results/stage2b_1_policy_config.json`
- `results/stage2b_1_policy_summary.csv`
- `results/stage2b_1_source_manifest.json`
- `results/stage2b_1_stage2b_acceptance_parity_differences.csv`
- `results/stage2b_1_stage2b_acceptance_parity_summary.csv`
- `results/stage2b_1_stop_management_summary.csv`
- `results/stage2b_1_target_revision_summary.csv`
- `results/stage2b_1_trade_log.csv.gz`
- `results/stage2b_1_trend_exit_summary.csv`
- `results/stage2b_1_unit_test_results.csv`
- `results/stage2b_1_validation_checks.csv`
- `results/stage2b_1_validation_report.txt`
- `results/stage2b_1_yearly_summary.csv`

## 2–10. Reproducibility identity

- Normal repository resolution: `REPO_ROOT / "Stage 2.2.2 Final"` and `REPO_ROOT / "Stage 2B"`; this controlled local benchmark used: explicit --baseline-root.
- Environment: Python 3.12.13; pandas 3.0.1; NumPy 2.3.5; yfinance NOT_INSTALLED (not used in FROZEN mode)
- Stage 2.1 hash: `91d3d84760c4b2427d500f0bee0f2dc0ceeb7e4f2e31d51d17a64342777993d5`
- Stage 2.2.1 hash: `8e6514353cc32a5b8bed1212df0c12d76de11d0624e4931fda4028f0be3ed31f`
- Stage 2.2.2 Final hash: `63345c591b46c656b204236d147993cb283d57fdbccd0246b7cef281d7968730`
- Accepted Stage 2B main hash: `5cdf4b4060ea093d0c6655c76e8d262f9a33e36f728655fd7fad35ede7d4e673`
- Accepted Stage 2B config hash: `7675a643c9cfce30b36596cdd358fef3b8d14640117b3ac8aeed3a384b2ada5b`
- Frozen data content hash: `2b6a2bb93fcc6c3aa80d2115a002b8cba370f61442edb592ffc9bc95eaa02e35`
- Stage 2B.1 package hash: `9bba171b9917b9d125d2487e4afa53f6cc047e0a5ccbe3055ebb3e84363d854e`
- Policy config hash: `1830639ace2e2ddcdb24a899b52e44e3305b3ec297b74a6e620a5ee1d1d93e28`
- Experiment ID: `S2B1_20240101_20260828_b01a0453b0e8`

Individual Stage 2B.1 source hashes:

- `stage2b/calibration.py`: `eb1f0546b30c9cb22e865360e3f1f9f0e8c3ff668fdc11cf51a83df350529b49`
- `stage2b/diagnostics.py`: `5c213e2b8dbae3e9fd76072b921a24a5d2b456074d4880ae85ee319759f32511`
- `stage2b/hashing.py`: `94600f186b2e3023267e69ff4acfb217cf64320cd6629b6d651fb4044ba350c2`
- `stage2b/policies.py`: `387db0262eee23e5a9e3887da858ff5bbfd7b8a28e4783e141d2d34edc83dd94`
- `stage2b/Stock_Alert_Stage2B_1_Dynamic_Management.py`: `35c787f8ab47122a3f61b668c13923865b5b86ebf08faeb0dafaf1bcb054de83`
- `stage2b/validation.py`: `cc511040dce5a2264d36dfc3489842c3264a54d72ff465a84f4e353cbd34f4a9`

Frozen manifest, exact ticker set, file SHA-256, schema, duplicate dates, and date bounds passed both before and after the run. Package and dependency hashes also matched before/after.

## 11–14. Tests and acceptance gates

- Executable/full/hash test results: 163 checks; failures: 0.
- Mandatory sanity run: PASS (this run).
- D0 differences: not run in sanity mode.
- D1–D6 accepted trading differences: not run in sanity mode.

```csv
Type,Status,Count
FULL_RUN_INVARIANT,PASS,24
HASH_GATE,PASS,50
HASH_GATE_ACCEPTED_STAGE2B,PASS,5
INTEGRATION,PASS,68
UNIT,PASS,16
```

```csv
Artifact,Difference Count,Status
not run in sanity mode,0,NOT_RUN
```

## 15. Corrected 2016–2026 D1–D6 results

```csv
Policy,Starting Equity,Ending Equity,Total Return %,CAGR %,Annualized Volatility %,Sharpe RF 6%,Sharpe RF 0%,Sortino RF 6%,Calmar,Max Drawdown %,Trades,Win Rate %,Expectancy R,Profit Factor,Average Holding Days,Average Exposure %,Capacity Rejects,Turnover (Gross Notional / Average Equity),Total Slippage,Total Transaction Costs
D1_TRAIL_ONLY,100000.000000,98679.428778,-1.320571,-0.499318,1.751558,-3.607674,-0.280599,-4.814849,-0.181694,-2.748124,7,28.571429,-0.234388,0.238851,8.000000,1.794904,0,3.295791,114.398064,163.488793
D2_BREAK_EVEN_TRAIL,100000.000000,98704.998883,-1.295001,-0.489610,1.746519,-3.612479,-0.275804,-4.831962,-0.178207,-2.747429,7,28.571429,-0.228245,0.242424,8.000000,1.794513,0,3.295424,114.410861,163.501584
D3_PARTIAL_T1_TRAIL,100000.000000,99809.002183,-0.190998,-0.071962,1.518296,-3.878661,-0.040435,-5.600684,-0.032711,-2.199948,7,28.571429,0.047016,0.888266,8.000000,1.481779,0,3.288910,114.963416,164.053862
D4_TREND_PROTECT,100000.000000,100074.443932,0.074444,0.028025,1.516626,-3.816184,0.026268,-5.518851,0.014465,-1.937459,7,28.571429,0.100459,1.051555,8.000000,1.480114,0,3.286004,115.096269,164.186649
D5_RESISTANCE_TIGHTEN,100000.000000,100391.395559,0.391396,0.147199,1.454220,-3.897689,0.109658,-5.785587,0.089050,-1.652995,7,28.571429,0.165002,1.228967,7.571429,1.420302,0,3.281253,115.254904,164.345204
D6_HYBRID_DYNAMIC,100000.000000,100756.597395,0.756597,0.284225,1.484963,-3.723471,0.200913,-5.661878,0.174294,-1.630722,7,28.571429,0.229570,1.523974,7.571429,1.423199,0,3.309606,116.993608,166.083816
```

## 16. Corrected 2024–2026 results

```csv
Policy,Period,Start Equity (Prior Session),End Equity,Return %,First Session,Last Session
D1_TRAIL_ONLY,2024-2026,100000.000000,98679.428778,-1.320571,2024-01-01,2026-08-28
D2_BREAK_EVEN_TRAIL,2024-2026,100000.000000,98704.998883,-1.295001,2024-01-01,2026-08-28
D3_PARTIAL_T1_TRAIL,2024-2026,100000.000000,99809.002183,-0.190998,2024-01-01,2026-08-28
D4_TREND_PROTECT,2024-2026,100000.000000,100074.443932,0.074444,2024-01-01,2026-08-28
D5_RESISTANCE_TIGHTEN,2024-2026,100000.000000,100391.395559,0.391396,2024-01-01,2026-08-28
D6_HYBRID_DYNAMIC,2024-2026,100000.000000,100756.597395,0.756597,2024-01-01,2026-08-28
```

## 17. D1 versus all static controls

```csv
Policy,Ending Equity,Total Return %,CAGR %,Max Drawdown %,Trades,Average Exposure %,Capacity Rejects
D1_TRAIL_ONLY,98679.428778,-1.320571,-0.499318,-2.748124,7,1.794904,0
T1_10D,100437.303025,0.437303,0.164441,-1.877726,6,1.328970,0
T1_20D,100043.410251,0.043410,0.016344,-2.141489,4,1.405678,0
T1_30D,100588.336659,0.588337,0.221131,-1.872789,4,1.478745,0
T1_45D,100588.336659,0.588337,0.221131,-1.872789,4,1.478745,0
T1_63D,100588.336659,0.588337,0.221131,-1.872789,4,1.478745,0
T2_10D,100045.678677,0.045679,0.017198,-1.877726,6,1.588502,0
T2_20D,99651.785903,-0.348214,-0.131261,-2.141489,4,1.666236,0
T2_30D,97131.061376,-2.868939,-1.090103,-3.833388,4,2.247375,0
T2_45D,97131.061376,-2.868939,-1.090103,-3.833388,4,2.247375,0
T2_63D,97131.061376,-2.868939,-1.090103,-3.833388,4,2.247375,0
```

## 18. D1 versus exposure-matched NIFTY

The first 2016 portfolio date uses only the prior 2015-12-31 NIFTY row. Every alignment source date is at or before the portfolio date; no backfill/future row is used.

```csv
Policy,Benchmark,Average Exposure %,Ending Equity,Total Return %,Benchmark Start Date,First NIFTY Source Date,Latest NIFTY Source Date,Future NIFTY Rows Used,Alignment
D1_TRAIL_ONLY,FULL_NIFTY,100.000000,111193.823706,11.193824,2024-01-01,2024-01-01,2026-08-28,False,EXACT_OR_PRIOR_OBSERVATION_FORWARD_FILL
D1_TRAIL_ONLY,EX_POST_CONSTANT_AVERAGE_EXPOSURE / CASH_0,1.794904,100233.036257,0.233036,2024-01-01,2024-01-01,2026-08-28,False,EXACT_OR_PRIOR_OBSERVATION_FORWARD_FILL
D1_TRAIL_ONLY,EX_POST_CONSTANT_AVERAGE_EXPOSURE / CASH_RF,1.794904,116465.437680,16.465438,2024-01-01,2024-01-01,2026-08-28,False,EXACT_OR_PRIOR_OBSERVATION_FORWARD_FILL
D1_TRAIL_ONLY,PRIOR_SESSION_DYNAMIC_EXPOSURE / CASH_0,1.794904,98643.164337,-1.356836,2024-01-01,2024-01-01,2026-08-28,False,EXACT_OR_PRIOR_OBSERVATION_FORWARD_FILL
D1_TRAIL_ONLY,PRIOR_SESSION_DYNAMIC_EXPOSURE / CASH_RF,1.794904,114618.421566,14.618422,2024-01-01,2024-01-01,2026-08-28,False,EXACT_OR_PRIOR_OBSERVATION_FORWARD_FILL
```

## 19. Friction sensitivity

```csv

```

## 20. Paired-entry fixed-cohort result

Every one of the 4 exact static T2_63D entries was replayed through all six policies at fixed original quantity. Earlier exits do not recycle cash, rerank, allocate, or create positions; these are not portfolio CAGR comparisons.

```csv
Policy,Fixed Cohort Count,Average Baseline R,Average Dynamic R,Mean Delta R,Median Delta R,% Improved,% Worsened,% Unchanged,Total Fixed-Quantity PnL Delta,Average Holding-Time Delta,Interpretation
D1_TRAIL_ONLY,4,-1.072232,-0.545934,0.526298,0.544793,100.000000,0.000000,0.000000,1338.057448,-10.750000,FIXED ENTRY/QUANTITY SHADOW; NO CASH RECYCLING; NOT PORTFOLIO CAGR
D2_BREAK_EVEN_TRAIL,4,-1.072232,-0.535183,0.537049,0.544793,100.000000,0.000000,0.000000,1363.627552,-10.750000,FIXED ENTRY/QUANTITY SHADOW; NO CASH RECYCLING; NOT PORTFOLIO CAGR
D3_PARTIAL_T1_TRAIL,4,-1.072232,-0.535183,0.537049,0.544793,100.000000,0.000000,0.000000,1363.627552,-10.750000,FIXED ENTRY/QUANTITY SHADOW; NO CASH RECYCLING; NOT PORTFOLIO CAGR
D4_TREND_PROTECT,4,-1.072232,-0.441657,0.630575,0.617113,100.000000,0.000000,0.000000,1629.069302,-10.750000,FIXED ENTRY/QUANTITY SHADOW; NO CASH RECYCLING; NOT PORTFOLIO CAGR
D5_RESISTANCE_TIGHTEN,4,-1.072232,-0.535183,0.537049,0.544793,100.000000,0.000000,0.000000,1363.627552,-10.750000,FIXED ENTRY/QUANTITY SHADOW; NO CASH RECYCLING; NOT PORTFOLIO CAGR
D6_HYBRID_DYNAMIC,4,-1.072232,-0.441657,0.630575,0.617113,100.000000,0.000000,0.000000,1629.069302,-10.750000,FIXED ENTRY/QUANTITY SHADOW; NO CASH RECYCLING; NOT PORTFOLIO CAGR
```

## 21. Opportunity-recycling decomposition

```csv
Policy,Static Portfolio Entries,Dynamic Portfolio Entries,Shared Entries,Additional Dynamic Entries,Static Entries Not Taken,Shared Dynamic Entry Net PnL,Dynamic-Only Entry Net PnL,Dynamic-Only Entries From Earlier Same-Ticker Exit (Determinable),Interpretation
D1_TRAIL_ONLY,4,7,4,3,0,-1530.881176,210.309955,3,DESCRIPTIVE OPPORTUNITY-RECYCLING DECOMPOSITION; ENTRY RULES UNCHANGED
D2_BREAK_EVEN_TRAIL,4,7,4,3,0,-1505.311072,210.309955,3,DESCRIPTIVE OPPORTUNITY-RECYCLING DECOMPOSITION; ENTRY RULES UNCHANGED
D3_PARTIAL_T1_TRAIL,4,7,4,3,0,-1505.311072,1314.313255,3,DESCRIPTIVE OPPORTUNITY-RECYCLING DECOMPOSITION; ENTRY RULES UNCHANGED
D4_TREND_PROTECT,4,7,4,3,0,-1239.869322,1314.313255,3,DESCRIPTIVE OPPORTUNITY-RECYCLING DECOMPOSITION; ENTRY RULES UNCHANGED
D5_RESISTANCE_TIGHTEN,4,7,4,3,0,-1505.311072,1896.706631,3,DESCRIPTIVE OPPORTUNITY-RECYCLING DECOMPOSITION; ENTRY RULES UNCHANGED
D6_HYBRID_DYNAMIC,4,7,4,3,0,-1239.869322,1996.466717,3,DESCRIPTIVE OPPORTUNITY-RECYCLING DECOMPOSITION; ENTRY RULES UNCHANGED
```

## 22. Stop diagnostics

```csv
Policy,Total Trades,Average Stop Revisions,Median Stop Revisions,% With No Stop Revision,% With At Least One Stop Revision,Break-Even Trigger Count,Break-Even Trigger %,First Stop Revision Average DaysHeld,First Stop Revision Median DaysHeld,First Stop Revision Average CurrentR,SuperTrend Stop-Revision Count,SwingLow Stop-Revision Count,BreakEven Stop-Revision Count,Raised-Stop Exits,Possible Later-Winner Cut-Off Rate %,Protected-From-Later-Loss Rate %,Counterfactual Label
D1_TRAIL_ONLY,7,2.714286,3.000000,0.000000,100.000000,0,0.000000,1.000000,1.000000,0.008204,4,15,0,7,42.857143,100.000000,POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY
D2_BREAK_EVEN_TRAIL,7,2.714286,3.000000,0.000000,100.000000,2,28.571429,1.000000,1.000000,0.008204,4,13,2,7,42.857143,100.000000,POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY
D3_PARTIAL_T1_TRAIL,7,2.714286,3.000000,0.000000,100.000000,2,28.571429,1.000000,1.000000,0.008204,4,13,2,7,42.857143,100.000000,POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY
D4_TREND_PROTECT,7,2.714286,3.000000,0.000000,100.000000,2,28.571429,1.000000,1.000000,0.008204,4,12,2,6,50.000000,100.000000,POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY
D5_RESISTANCE_TIGHTEN,7,2.571429,3.000000,0.000000,100.000000,2,28.571429,1.000000,1.000000,0.008204,4,12,2,6,33.333333,100.000000,POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY
D6_HYBRID_DYNAMIC,7,2.571429,3.000000,0.000000,100.000000,2,28.571429,1.000000,1.000000,0.008204,4,11,2,5,40.000000,100.000000,POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY
```

## 23. Partial-profit diagnostics

```csv
Policy,Trades,Trades With T1 Partial,Partial Rate %,Average Partial Quantity %,Average First-Leg Realized R,Median First-Leg R,Average Remainder Realized R,Median Remainder R,Average Total Trade R,Total Extra Transaction Cost From Partial Legs,Total Extra Slippage From Partial Legs,Average Holding Sessions After Partial,% Remainder Reaching T2,% Remainder Later Stopped
D3_PARTIAL_T1_TRAIL,7,2,28.571429,48.333333,2.437264,2.437264,0.432567,0.432567,1.395980,12.294615,12.300765,8.500000,0.000000,100.000000
D4_TREND_PROTECT,7,2,28.571429,48.333333,2.437264,2.437264,0.432567,0.432567,1.395980,12.294615,12.300765,8.500000,0.000000,100.000000
D5_RESISTANCE_TIGHTEN,7,2,28.571429,48.333333,2.437264,2.437264,1.258472,1.258472,1.808932,12.294615,12.300765,7.000000,0.000000,50.000000
D6_HYBRID_DYNAMIC,7,2,28.571429,50.000000,2.437264,2.437264,1.258472,1.258472,1.847868,13.122869,13.129433,7.000000,0.000000,50.000000
```

## 24. Target-tightening diagnostics

```csv
Policy,Trades With Target Revision,Total Target Revisions,Average Revisions Per Trade,Average Target Reduction %,Median Target Reduction %,Average Target Reduction R,Final Dynamic-Target Exits,Average R Dynamic-Target Exits,Original T2 Later Reached Count,Original T2 Later Reached %,Counterfactual Label
D5_RESISTANCE_TIGHTEN,2,2,0.285714,1.358570,1.358570,0.563678,1,1.690233,1,100.000000,POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY
D6_HYBRID_DYNAMIC,2,2,0.285714,1.358570,1.358570,0.563678,1,1.690233,1,100.000000,POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY
```

## 25. Trend-exit diagnostics

```csv
Policy,Daily Trend-Exit Count,Weekly Trend-Exit Count,Stale-Exit Count,Average R At Exit,Median R At Exit,Win Rate %,Average Holding Period,Counterfactual Label,5S Average Raw Return %,5S Average MFE %,5S Average MAE %,5S Later T1 Hit %,5S Later T2 Hit %,10S Average Raw Return %,10S Average MFE %,10S Average MAE %,10S Later T1 Hit %,10S Later T2 Hit %,20S Average Raw Return %,20S Average MFE %,20S Average MAE %,20S Later T1 Hit %,20S Later T2 Hit %
D4_TREND_PROTECT,1,0,0,-0.615742,-0.615742,0.000000,2.000000,POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY,-2.457130,0.477634,-3.951907,0.000000,0.000000,-4.041251,0.477634,-4.440256,0.000000,0.000000,-2.092392,2.977664,-4.440256,0.000000,0.000000
D6_HYBRID_DYNAMIC,1,0,0,-0.615742,-0.615742,0.000000,2.000000,POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY,-2.457130,0.477634,-3.951907,0.000000,0.000000,-4.041251,0.477634,-4.440256,0.000000,0.000000,-2.092392,2.977664,-4.440256,0.000000,0.000000
```

## 26. Calibration quality

Past-only pseudo-OOS Brier results are reported overall and by evaluation year; ten probability buckets per target include counts, mean prediction, observed rate, and calibration error.

```csv
Evaluation Year,Target,Predictions,Brier Score,Mean Predicted Probability,Observed Success Rate
OVERALL,T1,15,0.418784,0.286235,0.800000
OVERALL,T2,15,0.315171,0.248777,0.400000
```

```csv
Target,Probability Bucket,Count,Mean Prediction,Observed Success Rate,Calibration Error
T1,"(-0.001, 0.1]",0,,,
T1,"(0.1, 0.2]",0,,,
T1,"(0.2, 0.3]",7,0.221904,0.714286,0.492381
T1,"(0.3, 0.4]",7,0.331307,0.857143,0.525836
T1,"(0.4, 0.5]",1,0.421053,1.000000,0.578947
T1,"(0.5, 0.6]",0,,,
T1,"(0.6, 0.7]",0,,,
T1,"(0.7, 0.8]",0,,,
T1,"(0.8, 0.9]",0,,,
T1,"(0.9, 1.0]",0,,,
T2,"(-0.001, 0.1]",0,,,
T2,"(0.1, 0.2]",7,0.172592,0.714286,0.541693
T2,"(0.2, 0.3]",2,0.261758,0.500000,0.238242
T2,"(0.3, 0.4]",6,0.333333,0.000000,-0.333333
T2,"(0.4, 0.5]",0,,,
T2,"(0.5, 0.6]",0,,,
T2,"(0.6, 0.7]",0,,,
T2,"(0.7, 0.8]",0,,,
T2,"(0.8, 0.9]",0,,,
T2,"(0.9, 1.0]",0,,,
```

## 27. Drawdown duration and recovery

```csv
Policy,Maximum Drawdown %,Peak Date,Trough Date,Recovery Date,Peak-to-Trough Sessions,Recovery Sessions,Longest Underwater Duration Sessions
D1_TRAIL_ONLY,-2.748124,2024-10-17,2026-01-13,,308,,465
D2_BREAK_EVEN_TRAIL,-2.747429,2024-10-17,2026-01-13,,308,,465
D3_PARTIAL_T1_TRAIL,-2.199948,2024-10-17,2026-01-13,,308,,465
D4_TREND_PROTECT,-1.937459,2024-10-17,2026-01-13,,308,,465
D5_RESISTANCE_TIGHTEN,-1.652995,2024-12-19,2026-01-13,,265,,422
D6_HYBRID_DYNAMIC,-1.630722,2025-01-10,2026-01-13,,250,,407
T1_10D,-1.877726,2024-12-19,2026-01-12,,264,,422
T1_20D,-2.141489,2024-09-17,2026-01-12,,328,,486
T1_30D,-1.872789,2024-12-19,2026-01-12,,264,,422
T1_45D,-1.872789,2024-12-19,2026-01-12,,264,,422
T1_63D,-1.872789,2024-12-19,2026-01-12,,264,,422
T2_10D,-1.877726,2024-12-19,2026-01-12,,264,,422
T2_20D,-2.141489,2024-09-17,2026-01-12,,328,,486
T2_30D,-3.833388,2024-10-17,2026-02-04,,323,,465
T2_45D,-3.833388,2024-10-17,2026-02-04,,323,,465
T2_63D,-3.833388,2024-10-17,2026-02-04,,323,,465
```

## 28. Runtime

15.13 seconds.

## 29. Limitations

- Current-universe survivorship bias.
- Historical pseudo-OOS validation is not prospective unseen data.
- Daily OHLC sequencing ambiguity; exact exclusion fields are included for future Stage 3 work.
- Inherited Stage 2.1 holiday-short weekly limitation.
- Generic bps cost model.
- Multiple-hypothesis/history-selection risk; no policy is approved for live trading.
- Exposure-matched benchmarks and post-exit counterfactuals are diagnostic, not causal evidence.

## 30. Unresolved issues

- No blocking historical behavior, accounting, look-ahead, or parity issue remains.
- Accepted D6 semantics gate stale exits on `partial_taken`; the accepted sample produced no historical behavior-change blocker. This was preserved, not optimized.
- Research-only warnings above remain unresolved by design. Stage 3, ML, parameter search, live monitoring, and paper trading were not implemented.

STAGE 2.2.2 FINAL MODIFIED: NO  
STAGE 2B MODIFIED: NO  
STAGE 2.1 SIGNAL RULES CHANGED: NO  
ENTRY RULES CHANGED: NO  
D1-D6 MANAGEMENT RULES CHANGED: NO  
ML IMPLEMENTED: NO  
POLICY OPTIMIZATION PERFORMED: NO  
PAPER TRADING IMPLEMENTED: NO
