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
- Experiment ID: `S2B1_20160101_20260828_a681f1f8a9d9`

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
- Mandatory sanity run: PASS.
- D0 differences: 0.
- D1–D6 accepted trading differences: 0.

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
candidate selection,0,PASS
orders and entries,0,PASS
trades and final exits,0,PASS
"exit legs, costs and PnL",0,PASS
stop and target management,0,PASS
equity D1_TRAIL_ONLY,0,PASS
equity D2_BREAK_EVEN_TRAIL,0,PASS
equity D3_PARTIAL_T1_TRAIL,0,PASS
equity D4_TREND_PROTECT,0,PASS
equity D5_RESISTANCE_TIGHTEN,0,PASS
equity D6_HYBRID_DYNAMIC,0,PASS
```

## 15. Corrected 2016–2026 D1–D6 results

```csv
Policy,Starting Equity,Ending Equity,Total Return %,CAGR %,Annualized Volatility %,Sharpe RF 6%,Sharpe RF 0%,Sortino RF 6%,Calmar,Max Drawdown %,Trades,Win Rate %,Expectancy R,Profit Factor,Average Holding Days,Average Exposure %,Capacity Rejects,Turnover (Gross Notional / Average Equity),Total Slippage,Total Transaction Costs
D1_TRAIL_ONLY,100000.000000,120093.408187,20.093408,1.733172,4.001710,-0.998836,0.457432,-1.416473,0.146558,-11.825863,285,25.263158,0.084997,1.253698,6.392982,11.014155,1,114.957486,4197.382854,6483.041137
D2_BREAK_EVEN_TRAIL,100000.000000,116768.158150,16.768158,1.465442,3.979924,-1.071973,0.392267,-1.510977,0.124726,-11.749281,285,24.561404,0.069902,1.216563,6.347368,10.893530,1,114.629282,4125.755016,6366.640305
D3_PARTIAL_T1_TRAIL,100000.000000,114683.691258,14.683691,1.294068,3.735237,-1.190821,0.369338,-1.655813,0.117329,-11.029374,285,25.614035,0.064113,1.193427,6.389474,9.970839,1,114.855278,4047.823262,6247.690377
D4_TREND_PROTECT,100000.000000,112864.050278,12.864050,1.142144,3.591383,-1.282569,0.340082,-1.806317,0.109130,-10.465930,285,25.263158,0.050381,1.180657,6.196491,9.507212,0,114.621442,4020.061219,6199.530108
D5_RESISTANCE_TIGHTEN,100000.000000,114128.788658,14.128789,1.247971,3.679251,-1.222108,0.361791,-1.696058,0.110270,-11.317373,287,25.435540,0.061526,1.187079,5.937282,9.515765,1,115.264721,4021.511364,6214.347214
D6_HYBRID_DYNAMIC,100000.000000,112424.678554,12.424679,1.105127,3.548093,-1.309163,0.333286,-1.839242,0.102032,-10.831214,287,25.087108,0.047807,1.174967,5.745645,9.044192,0,115.144255,3996.369076,6171.709243
```

## 16. Corrected 2024–2026 results

```csv
Policy,Period,Start Equity (Prior Session),End Equity,Return %,First Session,Last Session
D1_TRAIL_ONLY,2024-2026,119729.086894,120093.408187,0.304288,2024-01-01,2026-08-28
D2_BREAK_EVEN_TRAIL,2024-2026,118332.402034,116768.158150,-1.321907,2024-01-01,2026-08-28
D3_PARTIAL_T1_TRAIL,2024-2026,114858.112737,114683.691258,-0.151858,2024-01-01,2026-08-28
D4_TREND_PROTECT,2024-2026,114396.597221,112864.050278,-1.339679,2024-01-01,2026-08-28
D5_RESISTANCE_TIGHTEN,2024-2026,113001.871210,114128.788658,0.997256,2024-01-01,2026-08-28
D6_HYBRID_DYNAMIC,2024-2026,112603.049917,112424.678554,-0.158407,2024-01-01,2026-08-28
```

## 17. D1 versus all static controls

```csv
Policy,Ending Equity,Total Return %,CAGR %,Max Drawdown %,Trades,Average Exposure %,Capacity Rejects
D1_TRAIL_ONLY,120093.408187,20.093408,1.733172,-11.825863,285,11.014155,1
T1_10D,111851.723345,11.851723,1.056659,-12.091843,250,10.656613,4
T1_20D,102264.140129,2.264140,0.210332,-16.830920,241,14.649964,3
T1_30D,109595.545293,9.595545,0.863589,-17.696008,239,16.501704,7
T1_45D,108687.864807,8.687865,0.784898,-16.641714,238,17.640260,7
T1_63D,109120.890844,9.120891,0.822513,-16.321997,237,18.001602,7
T2_10D,115699.385204,15.699385,1.377923,-12.524580,248,11.614007,4
T2_20D,114051.303993,14.051304,1.241519,-18.283337,236,16.750809,2
T2_30D,114928.969737,14.928970,1.314380,-19.637294,231,19.674478,11
T2_45D,109971.976579,9.971977,0.896051,-18.978968,227,21.782298,13
T2_63D,106745.309769,6.745310,0.614467,-20.875180,225,22.785454,12
```

## 18. D1 versus exposure-matched NIFTY

The first 2016 portfolio date uses only the prior 2015-12-31 NIFTY row. Every alignment source date is at or before the portfolio date; no backfill/future row is used.

```csv
Policy,Benchmark,Average Exposure %,Ending Equity,Total Return %,Benchmark Start Date,First NIFTY Source Date,Latest NIFTY Source Date,Future NIFTY Rows Used,Alignment
D1_TRAIL_ONLY,FULL_NIFTY,100.000000,304235.908229,204.235908,2016-01-01,2015-12-31,2026-08-28,False,EXACT_OR_PRIOR_OBSERVATION_FORWARD_FILL
D1_TRAIL_ONLY,EX_POST_CONSTANT_AVERAGE_EXPOSURE / CASH_0,11.014155,114573.753619,14.573754,2016-01-01,2015-12-31,2026-08-28,False,EXACT_OR_PRIOR_OBSERVATION_FORWARD_FILL
D1_TRAIL_ONLY,EX_POST_CONSTANT_AVERAGE_EXPOSURE / CASH_RF,11.014155,197073.503079,97.073503,2016-01-01,2015-12-31,2026-08-28,False,EXACT_OR_PRIOR_OBSERVATION_FORWARD_FILL
D1_TRAIL_ONLY,PRIOR_SESSION_DYNAMIC_EXPOSURE / CASH_0,11.014155,117385.166925,17.385167,2016-01-01,2015-12-31,2026-08-28,False,EXACT_OR_PRIOR_OBSERVATION_FORWARD_FILL
D1_TRAIL_ONLY,PRIOR_SESSION_DYNAMIC_EXPOSURE / CASH_RF,11.014155,201909.721529,101.909722,2016-01-01,2015-12-31,2026-08-28,False,EXACT_OR_PRIOR_OBSERVATION_FORWARD_FILL
```

## 19. Friction sensitivity

```csv
Friction Multiplier,Policy,Ending Equity,Total Return %,CAGR %,Max Drawdown %,Trades,Total Slippage,Total Transaction Costs
0.500000,D1_TRAIL_ONLY,126692.507370,26.692507,2.245170,-10.941802,285,2180.576338,3341.261175
1.000000,D1_TRAIL_ONLY,120093.408187,20.093408,1.733172,-11.825863,285,4197.382854,6483.041137
1.500000,D1_TRAIL_ONLY,115156.304756,15.156305,1.333170,-12.429839,285,6108.469896,9495.270259
2.000000,D1_TRAIL_ONLY,110206.820824,10.206821,0.916252,-13.186833,285,7894.212611,12342.493988
```

## 20. Paired-entry fixed-cohort result

Every one of the 225 exact static T2_63D entries was replayed through all six policies at fixed original quantity. Earlier exits do not recycle cash, rerank, allocate, or create positions; these are not portfolio CAGR comparisons.

```csv
Policy,Fixed Cohort Count,Average Baseline R,Average Dynamic R,Mean Delta R,Median Delta R,% Improved,% Worsened,% Unchanged,Total Fixed-Quantity PnL Delta,Average Holding-Time Delta,Interpretation
D1_TRAIL_ONLY,225,0.033079,0.060158,0.027080,0.406580,60.444444,16.000000,23.555556,6961.988867,-9.062222,FIXED ENTRY/QUANTITY SHADOW; NO CASH RECYCLING; NOT PORTFOLIO CAGR
D2_BREAK_EVEN_TRAIL,225,0.033079,0.052818,0.019739,0.406580,60.444444,16.444444,23.111111,5381.591970,-9.120000,FIXED ENTRY/QUANTITY SHADOW; NO CASH RECYCLING; NOT PORTFOLIO CAGR
D3_PARTIAL_T1_TRAIL,225,0.033079,0.047015,0.013936,0.406580,61.777778,29.333333,8.888889,3950.404010,-9.093333,FIXED ENTRY/QUANTITY SHADOW; NO CASH RECYCLING; NOT PORTFOLIO CAGR
D4_TREND_PROTECT,225,0.033079,0.044944,0.011865,0.478087,61.333333,29.777778,8.888889,3645.559636,-9.168889,FIXED ENTRY/QUANTITY SHADOW; NO CASH RECYCLING; NOT PORTFOLIO CAGR
D5_RESISTANCE_TIGHTEN,225,0.033079,0.049481,0.016402,0.419006,62.222222,28.888889,8.888889,3984.369341,-9.600000,FIXED ENTRY/QUANTITY SHADOW; NO CASH RECYCLING; NOT PORTFOLIO CAGR
D6_HYBRID_DYNAMIC,225,0.033079,0.047410,0.014331,0.479022,61.777778,29.333333,8.888889,3679.524967,-9.675556,FIXED ENTRY/QUANTITY SHADOW; NO CASH RECYCLING; NOT PORTFOLIO CAGR
```

## 21. Opportunity-recycling decomposition

```csv
Policy,Static Portfolio Entries,Dynamic Portfolio Entries,Shared Entries,Additional Dynamic Entries,Static Entries Not Taken,Shared Dynamic Entry Net PnL,Dynamic-Only Entry Net PnL,Dynamic-Only Entries From Earlier Same-Ticker Exit (Determinable),Interpretation
D1_TRAIL_ONLY,225,285,223,62,2,14329.789146,5763.619041,56,DESCRIPTIVE OPPORTUNITY-RECYCLING DECOMPOSITION; ENTRY RULES UNCHANGED
D2_BREAK_EVEN_TRAIL,225,285,223,62,2,12646.248995,4121.909156,56,DESCRIPTIVE OPPORTUNITY-RECYCLING DECOMPOSITION; ENTRY RULES UNCHANGED
D3_PARTIAL_T1_TRAIL,225,285,223,62,2,10907.267338,3776.423920,56,DESCRIPTIVE OPPORTUNITY-RECYCLING DECOMPOSITION; ENTRY RULES UNCHANGED
D4_TREND_PROTECT,225,285,222,63,3,8915.557046,3948.493232,56,DESCRIPTIVE OPPORTUNITY-RECYCLING DECOMPOSITION; ENTRY RULES UNCHANGED
D5_RESISTANCE_TIGHTEN,225,287,223,64,2,10848.638916,3280.149742,58,DESCRIPTIVE OPPORTUNITY-RECYCLING DECOMPOSITION; ENTRY RULES UNCHANGED
D6_HYBRID_DYNAMIC,225,287,222,65,3,9264.116720,3160.561834,58,DESCRIPTIVE OPPORTUNITY-RECYCLING DECOMPOSITION; ENTRY RULES UNCHANGED
```

## 22. Stop diagnostics

```csv
Policy,Total Trades,Average Stop Revisions,Median Stop Revisions,% With No Stop Revision,% With At Least One Stop Revision,Break-Even Trigger Count,Break-Even Trigger %,First Stop Revision Average DaysHeld,First Stop Revision Median DaysHeld,First Stop Revision Average CurrentR,SuperTrend Stop-Revision Count,SwingLow Stop-Revision Count,BreakEven Stop-Revision Count,Raised-Stop Exits,Possible Later-Winner Cut-Off Rate %,Protected-From-Later-Loss Rate %,Counterfactual Label
D1_TRAIL_ONLY,285,2.080702,1.000000,5.964912,94.035088,0,0.000000,1.000000,1.000000,0.048218,184,409,0,223,40.807175,79.820628,POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY
D2_BREAK_EVEN_TRAIL,285,2.101754,1.000000,5.964912,94.035088,66,23.157895,1.000000,1.000000,0.048218,159,374,66,225,41.333333,79.555556,POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY
D3_PARTIAL_T1_TRAIL,285,2.115789,1.000000,5.964912,94.035088,67,23.508772,1.000000,1.000000,0.048218,162,374,67,225,41.333333,79.555556,POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY
D4_TREND_PROTECT,285,2.084211,1.000000,5.964912,94.035088,64,22.456140,1.000000,1.000000,0.045376,160,347,64,209,41.148325,79.425837,POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY
D5_RESISTANCE_TIGHTEN,287,1.965157,1.000000,5.923345,94.076655,59,20.557491,1.000000,1.000000,0.046628,141,346,59,216,39.814815,81.944444,POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY
D6_HYBRID_DYNAMIC,287,1.933798,1.000000,5.923345,94.076655,56,19.512195,1.000000,1.000000,0.043807,139,319,56,200,39.500000,82.000000,POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY
```

## 23. Partial-profit diagnostics

```csv
Policy,Trades,Trades With T1 Partial,Partial Rate %,Average Partial Quantity %,Average First-Leg Realized R,Median First-Leg R,Average Remainder Realized R,Median Remainder R,Average Total Trade R,Total Extra Transaction Cost From Partial Legs,Total Extra Slippage From Partial Legs,Average Holding Sessions After Partial,% Remainder Reaching T2,% Remainder Later Stopped
D3_PARTIAL_T1_TRAIL,285,58,20.350877,48.536768,1.919602,1.833889,2.106778,2.454284,2.020215,325.025445,325.188039,4.896552,74.137931,25.862069
D4_TREND_PROTECT,285,55,19.298246,48.608941,1.882203,1.830877,2.012116,2.453235,1.952975,302.415818,302.567102,5.109091,72.727273,27.272727
D5_RESISTANCE_TIGHTEN,287,58,20.209059,48.557781,1.919602,1.833889,2.130529,2.045797,2.027254,321.900164,322.061194,2.775862,29.310345,6.896552
D6_HYBRID_DYNAMIC,287,55,19.163763,48.633143,1.882203,1.830877,2.034560,2.009053,1.959967,300.403886,300.554163,2.872727,25.454545,7.272727
```

## 24. Target-tightening diagnostics

```csv
Policy,Trades With Target Revision,Total Target Revisions,Average Revisions Per Trade,Average Target Reduction %,Median Target Reduction %,Average Target Reduction R,Final Dynamic-Target Exits,Average R Dynamic-Target Exits,Original T2 Later Reached Count,Original T2 Later Reached %,Counterfactual Label
D5_RESISTANCE_TIGHTEN,41,41,0.142857,2.104706,1.998199,0.605223,37,1.855483,34,91.891892,POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY
D6_HYBRID_DYNAMIC,41,41,0.142857,2.119320,2.036590,0.608718,37,1.851172,34,91.891892,POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY
```

## 25. Trend-exit diagnostics

```csv
Policy,Daily Trend-Exit Count,Weekly Trend-Exit Count,Stale-Exit Count,Average R At Exit,Median R At Exit,Win Rate %,Average Holding Period,Counterfactual Label,5S Average Raw Return %,5S Average MFE %,5S Average MAE %,5S Later T1 Hit %,5S Later T2 Hit %,10S Average Raw Return %,10S Average MFE %,10S Average MAE %,10S Later T1 Hit %,10S Later T2 Hit %,20S Average Raw Return %,20S Average MFE %,20S Average MAE %,20S Later T1 Hit %,20S Later T2 Hit %
D4_TREND_PROTECT,19,0,0,-0.315050,-0.296876,10.526316,2.000000,POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY,1.394130,3.593754,-2.957381,10.526316,10.526316,2.508133,6.082104,-3.641462,15.789474,15.789474,2.711836,8.060156,-4.993448,26.315789,21.052632
D6_HYBRID_DYNAMIC,19,0,0,-0.315050,-0.296876,10.526316,2.000000,POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY,1.394130,3.593754,-2.957381,10.526316,10.526316,2.508133,6.082104,-3.641462,15.789474,15.789474,2.711836,8.060156,-4.993448,26.315789,21.052632
```

## 26. Calibration quality

Past-only pseudo-OOS Brier results are reported overall and by evaluation year; ten probability buckets per target include counts, mean prediction, observed rate, and calibration error.

```csv
Evaluation Year,Target,Predictions,Brier Score,Mean Predicted Probability,Observed Success Rate
OVERALL,T1,754,0.222544,0.402105,0.297082
OVERALL,T2,754,0.188205,0.342378,0.221485
```

```csv
Target,Probability Bucket,Count,Mean Prediction,Observed Success Rate,Calibration Error
T1,"(-0.001, 0.1]",0,,,
T1,"(0.1, 0.2]",9,0.138822,0.000000,-0.138822
T1,"(0.2, 0.3]",82,0.272200,0.243902,-0.028297
T1,"(0.3, 0.4]",211,0.342147,0.303318,-0.038830
T1,"(0.4, 0.5]",450,0.458653,0.311111,-0.147542
T1,"(0.5, 0.6]",2,0.515152,0.000000,-0.515152
T1,"(0.6, 0.7]",0,,,
T1,"(0.7, 0.8]",0,,,
T1,"(0.8, 0.9]",0,,,
T1,"(0.9, 1.0]",0,,,
T2,"(-0.001, 0.1]",6,0.097561,0.166667,0.069106
T2,"(0.1, 0.2]",26,0.127103,0.000000,-0.127103
T2,"(0.2, 0.3]",204,0.259358,0.196078,-0.063280
T2,"(0.3, 0.4]",295,0.364910,0.277966,-0.086944
T2,"(0.4, 0.5]",223,0.420204,0.197309,-0.222895
T2,"(0.5, 0.6]",0,,,
T2,"(0.6, 0.7]",0,,,
T2,"(0.7, 0.8]",0,,,
T2,"(0.8, 0.9]",0,,,
T2,"(0.9, 1.0]",0,,,
```

## 27. Drawdown duration and recovery

```csv
Policy,Maximum Drawdown %,Peak Date,Trough Date,Recovery Date,Peak-to-Trough Sessions,Recovery Sessions,Longest Underwater Duration Sessions
D1_TRAIL_ONLY,-11.825863,2021-11-16,2023-05-23,,375,,1186
D2_BREAK_EVEN_TRAIL,-11.749281,2021-11-16,2023-05-23,,375,,1186
D3_PARTIAL_T1_TRAIL,-11.029374,2021-11-17,2023-05-23,,374,,1185
D4_TREND_PROTECT,-10.465930,2021-11-17,2023-05-23,,374,,1185
D5_RESISTANCE_TIGHTEN,-11.317373,2021-11-17,2023-05-23,,374,,1185
D6_HYBRID_DYNAMIC,-10.831214,2021-11-17,2023-05-23,,374,,1185
T1_10D,-12.091843,2021-11-18,2022-08-22,,188,,1184
T1_20D,-16.830920,2021-11-12,2023-05-23,,377,,1188
T1_30D,-17.696008,2021-11-12,2023-03-02,,325,,1188
T1_45D,-16.641714,2021-11-12,2023-03-13,,331,,1188
T1_63D,-16.321997,2021-11-12,2023-03-28,,342,,1188
T2_10D,-12.524580,2021-11-16,2023-05-23,2024-09-12,375,322.000000,696
T2_20D,-18.283337,2021-11-12,2023-05-23,,377,,1188
T2_30D,-19.637294,2021-11-12,2023-03-02,,325,,1188
T2_45D,-18.978968,2021-11-12,2023-05-23,,377,,1188
T2_63D,-20.875180,2021-11-12,2023-03-28,,342,,1188
```

## 28. Runtime

1330.63 seconds.

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
