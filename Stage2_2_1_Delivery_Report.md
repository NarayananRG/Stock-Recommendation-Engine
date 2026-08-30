# Stage 2.2.1 — Reproducible 15-Year Benchmark

## Delivery status

Stage 2.2.1 is complete. The required workflow was followed:

1. The implementation and deterministic execution self-tests were completed first.
2. A two-ticker sanity benchmark (`TCS.NS`, `INFY.NS`, 2024) ran through the full validation and reporting stack.
3. The sanity benchmark produced 22 PASS, 1 WARN, 0 FAIL, and zero pullback buy-limit breaches.
4. Only after that gate passed was the full 2011-08-30 through 2026-08-28 benchmark run.

No Stage 2.1 strategy threshold was changed.

## Reproducibility identity

- Experiment ID: `S221_20110830_20260828_e210057f2894`
- Strategy/config SHA-256: `b2dc08f8e57ea70d6a36372de7ecf55973b2df31ba21790751114c469ae92677`
- Frozen data-manifest SHA-256: `03d9336d738313c29e42ee886423cfa38cf070a550b61ae611fb3fceea482aae`
- Stage 2.1 source SHA-256: `91d3d84760c4b2427d500f0bee0f2dc0ceeb7e4f2e31d51d17a64342777993d5`
- Reference signal-log SHA-256: `af2611561199dee8ef8e443c1864b8a4d41dd5d6aec25379d738602762515dde`
- Full runtime: 310.626 seconds

The frozen manifest covers `^NSEI` plus all 20 configured stocks. Every frozen CSV was verified before and after the run. The portfolio execution consumed freshly regenerated signals from the same frozen OHLC files used for fills and mark-to-market accounting.

## Corrected methodology

The earlier Stage 2.2 benchmark replayed the saved Stage 2.1 signal log while executing against a newer cache. Stage 2.2.1 removes that methodological mismatch. The saved log is now read-only and used only for integrity and parity diagnostics; it is never the official portfolio candidate source.

Pullback fills also enforce true buy-limit semantics: executed entry cannot exceed the planned `Entry High`. Entry-bar target-only touches remain conservatively uncredited when the intraday sequence is unknowable.

## Full validation outcome

The full run produced 22 PASS, 1 WARN, and 0 FAIL checks. Passed checks include:

- frozen manifest and file hashes;
- same dataset for signal generation and execution;
- unchanged Stage 2.1 source during the run;
- reference-log integrity;
- entry strictly after signal date;
- no WATCH trades in primary portfolios;
- positive quantities, cash, capacity, and same-ticker state constraints;
- daily full-equity reconciliation;
- stop/target ordering and T2 above T1;
- pullback fills at or below their buy limit;
- slippage charged once and transaction-cost/net-PnL reconciliation;
- runtime state invariants.

An independent post-run audit separately verified all 21 frozen hashes, all 68,081 candidate rows, all 3,370 portfolio trade rows, all ten daily ledgers, and the common experiment/config/data identity.

## Reference parity warning

Fresh regeneration and the saved reference both contain 68,081 identical ticker/date keys, with no missing or extra rows. There are 57,390 exact row matches and 10,691 rows with at least one difference:

- 2,475 float-only differences;
- 343 signal-label differences;
- 13 BUY/non-BUY portfolio-membership changes;
- additional entry, stop, target, and score differences classified in the parity report.

This is reported as WARN because the saved reference reflects a different historical data/runtime state. It does not invalidate the benchmark's internal consistency: Stage 2.2.1 regenerated and executed from one verified frozen snapshot. The warning is not hidden or converted into a self-reference PASS.

## Portfolio results

| Variant | Ending equity | Net return | CAGR | Trades | Profit factor | Max drawdown |
|---|---:|---:|---:|---:|---:|---:|
| T1 10D | 124,326.01 | 24.33% | 1.46% | 356 | 1.178 | -12.26% |
| T1 20D | 111,234.94 | 11.23% | 0.71% | 341 | 1.072 | -17.18% |
| T1 30D | 114,618.14 | 14.62% | 0.91% | 338 | 1.090 | -17.88% |
| T1 45D | 112,981.19 | 12.98% | 0.82% | 337 | 1.078 | -16.85% |
| T1 63D | 113,796.36 | 13.80% | 0.87% | 336 | 1.082 | -16.45% |
| T2 10D | 127,963.01 | 27.96% | 1.66% | 354 | 1.206 | -12.67% |
| T2 20D | 131,261.53 | 31.26% | 1.83% | 336 | 1.182 | -18.57% |
| T2 30D | 125,196.24 | 25.20% | 1.51% | 328 | 1.141 | -20.12% |
| T2 45D | 120,973.38 | 20.97% | 1.28% | 323 | 1.117 | -19.07% |
| T2 63D | 120,930.93 | 20.93% | 1.28% | 321 | 1.111 | -21.27% |

The strongest absolute-return variant was T2 20D, but the differences among variants should not be treated as proof of future performance.

## NIFTY comparison and interpretation

The same frozen `^NSEI` price series rose from 5,001.00 to 24,175.65:

- NIFTY price-index return: 383.42%;
- NIFTY CAGR: 11.08%;
- NIFTY maximum drawdown: -38.44%;
- NIFTY Sharpe at 6% annual risk-free rate: 0.387.

The best Stage 2.2.1 portfolio returned 31.26% with a 1.83% CAGR. Every strategy variant therefore materially underperformed the NIFTY price index over the measured window. The strategy portfolios had substantially lower volatility and market exposure, but their Sharpe and Sortino ratios are negative when evaluated against a 6% annual risk-free rate because their annualized returns were below that hurdle.

Average gross exposure ranged from approximately 10.9% to 22.0%, and average cash ranged from approximately 78.0% to 89.1%. This low capital deployment is a major reason absolute returns lagged the benchmark. It is a measurement result, not a recommendation to loosen thresholds or increase risk.

## Data limitations

- This is not a survivorship-bias-free historical constituent study; it uses the supplied/current universe.
- The NIFTY comparison is a price-index comparison and excludes dividends.
- `HAL.NS` has history only from 2018 in the supplied snapshot.
- `TMCV.NS` has only 201 candles and was skipped by the unchanged Stage 2.1 minimum-history rule.
- Results are research outputs, not investment advice.

## Principal artifacts

- `Stock_Alert_Stage2_2_1_Reproducible_Benchmark.py` — implementation and CLI.
- `stage2_2_1/data/frozen/manifest.json` — canonical frozen-data manifest.
- `stage2_2_1/results/stage2_2_1_strategy_config.json` — full strategy/execution configuration and identity.
- `stage2_2_1/results/stage2_2_1_validation_report.txt` — full validation report.
- `stage2_2_1/results/stage2_2_1_portfolio_summary.csv` — main portfolio metrics.
- `stage2_2_1/results/stage2_2_1_benchmark_comparison.csv` — portfolio/NIFTY comparison.
- `stage2_2_1/results/stage2_2_1_signal_parity_differences.csv` — row-level parity classifications.
- `stage2_2_1/results/stage2_2_1_portfolio_trade_log.csv` and `stage2_2_1_order_log.csv` — audit ledgers.
- `stage2_2_1/results/stage2_2_1_daily_equity_*.csv` — full-equity daily ledgers for all ten variants.
