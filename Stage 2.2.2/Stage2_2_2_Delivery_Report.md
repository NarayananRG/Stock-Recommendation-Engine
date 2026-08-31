# Stage 2.2.2 Baseline Hardening Delivery Report

1. Overall status: **PASS**.
2. Run scope: official full universe; 2011-08-30 through 2026-08-28.
3. Stage 2.1 hash gate: `91d3d84760c4b2427d500f0bee0f2dc0ceeb7e4f2e31d51d17a64342777993d5` (exact required hash).
4. Stage 2.2.2 code hash: `80b9ba6e412486dd19390ad2c74c84b20a56afdec0c0a0938fff0f6a213badfb`.
5. Strategy hash: `e62dc4e75c056a216cc4bdaa589a95f9553ce40e37aa6690974759b7975ad23c`.
6. Execution hash: `9434b39d2d7bbd8203a4674b4acdebfecf898afbc08cf7bc144729ec4b326c2b`.
7. Data-content hash: `2b6a2bb93fcc6c3aa80d2115a002b8cba370f61442edb592ffc9bc95eaa02e35`.
8. Manifest-document hash: `f3328f947dda0f1fa993d4c40060bf414bc5ea73745cf9afe20031c9c4da5162`.
9. Portable Experiment ID: `S222_20110830_20260828_e7e6ecf95bca`; stable identity excludes absolute paths and environment versions.
10. Frozen-data policy: missing manifests fail; snapshot creation is explicit and immutable; every file is checked before and after execution.
11. Point-in-time audit: prefix-invariance checks cover daily/rolling indicators, relative strength, resistance source discipline, signals, and weekly mapping.
12. Weekly behavior: Weekly mapping is point-in-time safe for ordinary weeks: Mon-Thu uses the previous W-FRI candle and Friday uses the current completed candle after close. Stage 2.1 does not have an exchange-calendar rule to expose a holiday-short week on its final Thursday; it becomes available the following session. This is conservative (delayed), not forward-looking, and is reported without changing it.
13. Execution validation: independent entry, exit, slippage, transaction-cost, P&L, cash, equity, timing, position, and no-leverage checks are included.
14. Candidate research scope: T1 / maximum 63 sessions / independent opportunity simulation / capacity-free; it is not a portfolio return series.
15. Benchmarks: NIFTY 100% plus constant-average and prior-session dynamic exposure matching under cash=0 and cash=RF assumptions; exposure matches are diagnostic and do not prove causality.
16. Friction sensitivity: 0.5x, 1.0x, 1.5x, and 2.0x of baseline 5+5 BPS; 1.0x is official and signals are not regenerated. Stage 2.2.1 acceptance parity: **PASS**.
17. Environment: Python 3.12.13, pandas 3.0.1, NumPy 2.3.5, yfinance 1.7.0. Runtime 777.960 seconds. This test uses the supplied/current ticker universe and is not a survivorship-bias-free historical index-constituent study.

**STRATEGY RULES CHANGED: NO**
