# Stage 2B Delivery Report

## Outcome

**ENGINEERING STATUS: PASS.** The required two-ticker sanity run passed before the full run. The official full-history D0 compatibility gate reproduced the immutable Stage 2.2.2 Final `T2_63D` control with **0 differences** across signals, orders, trades, fills, quantities, costs, exits, P&L, and daily equity. The full historical walk-forward / pseudo-OOS run then completed for D1–D6, all ten static controls, and four friction levels.

This is historical research. No dynamic policy is selected for live use.

## Reproducibility identity

- Experiment: `S2B_20160101_20260828_005e454666f1`
- Stage 2B source hash: `5cdf4b4060ea093d0c6655c76e8d262f9a33e36f728655fd7fad35ede7d4e673`
- Policy config hash: `7675a643c9cfce30b36596cdd358fef3b8d14640117b3ac8aeed3a384b2ada5b`
- Stage 2.1: `91d3d84760c4b2427d500f0bee0f2dc0ceeb7e4f2e31d51d17a64342777993d5`
- Stage 2.2.1: `8e6514353cc32a5b8bed1212df0c12d76de11d0624e4931fda4028f0be3ed31f`
- Stage 2.2.2 Final: `63345c591b46c656b204236d147993cb283d57fdbccd0246b7cef281d7968730`
- Strategy: `e62dc4e75c056a216cc4bdaa589a95f9553ce40e37aa6690974759b7975ad23c`
- Baseline execution: `9434b39d2d7bbd8203a4674b4acdebfecf898afbc08cf7bc144729ec4b326c2b`
- Frozen data: `2b6a2bb93fcc6c3aa80d2115a002b8cba370f61442edb592ffc9bc95eaa02e35`

The identity excludes absolute Windows paths. All 45 recorded engineering validations passed. Full runtime was 470.5 seconds.

## Research design

- Calibration/development: 2011-08-30 through 2015-12-31, expanding annually using only outcomes resolved before each evaluation year.
- Historical walk-forward / pseudo-OOS: 2016-01-01 through 2026-08-28.
- Every policy starts flat with ₹100,000 in 2016; equity is continuous thereafter and is not reset yearly.
- Accepted candidate artifact: 68,081 rows, including 1,088 BUY/STRONG BUY candidates.
- Official friction: 5 bps slippage plus 5 bps transaction cost per execution leg.

## Official 1.0× results

| Policy | Trades | Ending equity | Return | CAGR | Expectancy R | PF | Max DD | Avg exposure |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| D1 Trail only | 285 | ₹120,093 | 20.09% | 1.73% | 0.085 | 1.254 | -11.83% | 11.01% |
| D2 Break-even trail | 285 | ₹116,768 | 16.77% | 1.47% | 0.070 | 1.217 | -11.75% | 10.89% |
| D3 Partial T1 trail | 285 | ₹114,684 | 14.68% | 1.29% | 0.064 | 1.193 | -11.03% | 9.97% |
| D4 Trend protect | 285 | ₹112,864 | 12.86% | 1.14% | 0.050 | 1.181 | -10.47% | 9.51% |
| D5 Resistance tighten | 287 | ₹114,129 | 14.13% | 1.25% | 0.062 | 1.187 | -11.32% | 9.52% |
| D6 Hybrid | 287 | ₹112,425 | 12.42% | 1.11% | 0.048 | 1.175 | -10.83% | 9.04% |
| Static T2_63D | 225 | ₹106,745 | 6.75% | 0.61% | 0.033 | 1.057 | -20.88% | 22.79% |

All six dynamic variants exceeded static T2_63D on full-period return, expectancy, PF, drawdown, and capital exposure under identical OOS start conditions. That is historical evidence, not proof of future superiority.

The ten static controls are preserved in `stage2b_policy_summary.csv`; their returns ranged from 2.26% (`T1_20D`) to 15.70% (`T2_10D`). No static policy was selected after seeing these results.

## Recent-period and drawdown comparison

For 2024–2026, returns were D1 +0.18%, D2 -1.45%, D3 -0.28%, D4 -1.47%, D5 +0.86%, D6 -0.29%, and static T2_63D -5.22%. The recent subperiod remains weak even where dynamic management reduced the loss. Dynamic maximum drawdowns were -10.47% to -11.83%, versus -20.88% for static T2_63D.

Transparent research classification:

- D1 and D5: **POSITIVE HISTORICAL EVIDENCE**, with positive full-period and recent-period results, but small recent gains.
- D2, D3, D4, and D6: **MIXED / INCONCLUSIVE**, because full-period evidence was positive while 2024–2026 remained negative.

## Management diagnostics

- Average stop revisions ranged from 1.93 to 2.12 per trade; the median was 1 for every policy.
- Break-even was the recorded after-close action 56–67 times in D2–D6.
- T1 partial exits occurred 58 times in D3/D5 and 55 times in D4/D6. Average first-leg realized R was 1.920 (D3/D5) and 1.882 (D4/D6), after separate leg friction.
- D5 and D6 each recorded 41 resistance-based target tightenings. D5 had 37 final dynamic-target exits; D6 also had 37.
- D4 and D6 each recorded 19 completed daily-trend exits. No weekly-trend or stale-trade exit fired in this sample.
- The full logs retain 1,940 exit legs and 8,857 daily management/state rows with direct Signal ID → Trade ID → Exit Leg ID lineage.

## Calibration

Past-only calibration tables cover 2016–2026 with hierarchical backoff and a minimum cohort size of 30. Overall eligible observations expanded from 258 for the 2016 table to 807 for 2026. The overall T1 Q25/median/Q75 range was 6/9/17 sessions for 2016 and 6/10/18 for 2026. Beta-smoothed overall P(T1 before stop) ranged around 35.6%–39.9%; P(T2 before stop) around 29.5%–33.5%. These values are diagnostic and never affect qualification, ranking, sizing, or execution; only the preregistered D6 stale-time condition may consume past-only T1 Q75.

Every populated trade lineage passed `Calibration Data End Date < Entry Date`.

## Friction sensitivity

At 0.5× / 1.0× / 1.5× / 2.0× friction, ending returns were:

| Policy | 0.5× | 1.0× | 1.5× | 2.0× |
|---|---:|---:|---:|---:|
| D1 | 26.69% | 20.09% | 15.16% | 10.21% |
| D2 | 22.33% | 16.77% | 11.96% | 8.43% |
| D3 | 20.05% | 14.68% | 9.85% | 5.35% |
| D4 | 17.99% | 12.86% | 7.59% | 3.41% |
| D5 | 19.46% | 14.13% | 9.18% | 4.86% |
| D6 | 17.57% | 12.42% | 6.76% | 2.89% |

All remained positive at 2.0×, but the degradation is material, particularly for multi-leg policies.

## Exposure-matched NIFTY diagnostics

Prior-session dynamic-exposure / CASH_0 returns were 17.39% (D1), 15.74% (D2), 15.33% (D3), 14.20% (D4), 14.65% (D5), and 13.45% (D6). These are diagnostics, not tradeable replicas. The constant-average-exposure benchmark is explicitly ex-post; the dynamic benchmark uses prior-session exposure for the next session. CASH_RF variants are separately labeled and reflect the 6% cash assumption.

## Files and audit trail

The package contains modular source, fixed config, sanity artifacts, official identity/validation files, exact D0 comparison, candidate/order/trade/exit-leg logs, daily management and position-state logs, policy/year/period/breakdown summaries, calibration tables, exposure diagnostics, cost sensitivity, and one compressed daily equity file per dynamic policy. See `stage2b/results/`.

## Limitations and warning

- Current-universe survivorship bias remains.
- Historical walk-forward is pseudo-OOS, not prospective unseen data.
- Daily OHLC cannot identify intraday sequence; stop-first rules are deliberately conservative.
- The Stage 2.1 holiday-short weekly delay remains.
- Costs are a generic bps model, not security-specific market impact.
- Empirical probabilities are diagnostic and are not sizing inputs.
- **MULTIPLE-HYPOTHESIS / HISTORICAL-SELECTION WARNING:** do not choose a policy solely because it ranked highest on this historical sample.

STAGE 2.2.2 MODIFIED: NO  
STAGE 2.1 SIGNAL RULES CHANGED: NO  
ENTRY RULES CHANGED: NO  
ML IMPLEMENTED: NO  
HISTORICAL WALK-FORWARD USED: YES  
PAPER TRADING IMPLEMENTED: NO
