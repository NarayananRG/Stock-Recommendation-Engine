# Stage 2.2.2 Final Baseline Delivery Report

1. Files changed: new final source, README/requirements, reconstruction and verification scripts, self-test artifacts, final validation artifacts, and final benchmark outputs. The accepted Stage 2.2.2 results remain in `accepted_results/` unchanged.
2. Stage 2.1 hash: `91d3d84760c4b2427d500f0bee0f2dc0ceeb7e4f2e31d51d17a64342777993d5`.
3. Stage 2.2.1 code hash: `8e6514353cc32a5b8bed1212df0c12d76de11d0624e4931fda4028f0be3ed31f` (accepted helper hash gate).
4. Final Stage 2.2.2 code hash: `63345c591b46c656b204236d147993cb283d57fdbccd0246b7cef281d7968730`; accepted pre-hotfix source hash: `80b9ba6e412486dd19390ad2c74c84b20a56afdec0c0a0938fff0f6a213badfb`.
5. Strategy hash: `e62dc4e75c056a216cc4bdaa589a95f9553ce40e37aa6690974759b7975ad23c`.
6. Execution hash: `9434b39d2d7bbd8203a4674b4acdebfecf898afbc08cf7bc144729ec4b326c2b`.
7. Data-content hash: `2b6a2bb93fcc6c3aa80d2115a002b8cba370f61442edb592ffc9bc95eaa02e35`.
8. Manifest-document hash: `f3328f947dda0f1fa993d4c40060bf414bc5ea73745cf9afe20031c9c4da5162`.
9. Final Experiment ID: `S222_20110830_20260828_abaea4e9641f`; its identity basis includes the Stage 2.2.1 helper hash and excludes absolute paths.
10. Exact environment versions: Python 3.12.13; CPython; pandas 3.0.1; NumPy 2.3.5; yfinance 1.7.0; Windows-11-10.0.26200-SP0.
11. Self-test result: **PASS** (21/21).
12. Sanity-run result: **PASS**; two tickers (TCS.NS and INFY.NS).
13. Validation PASS/WARN/FAIL counts: **42/2/0**; overall **PASS WITH WARNINGS**.
14. Full fresh-signal parity warning counts: generated 68081, reference 68081, exact 57390, rows with any difference 10691, float-only 2475, signal-label mismatches 343, BUY/non-BUY membership changes 13, missing/extra 0; severity **WARN**.
15. Weekly-holiday warning: **WARN** — Weekly mapping is point-in-time safe for ordinary weeks: Mon-Thu uses the previous W-FRI candle and Friday uses the current completed candle after close. Stage 2.1 does not have an exchange-calendar rule to expose a holiday-short week on its final Thursday; it becomes available the following session. This is conservative (delayed), not forward-looking, and is reported without changing it.
16. Point-in-time audit sample coverage: 6 stocks (HAL.NS, HDFCBANK.NS, INFY.NS, LT.NS, TCS.NS, TITAN.NS), 4 eras (2012-2015, 2016-2020, 2021-2023, 2024-2026), 460 field comparisons; genuine mismatch count 0.
17. Exact parity vs current accepted Stage 2.2.2: **PASS** — CANDIDATE=PASS (0 differences); ORDER=PASS (0 differences); TRADE=PASS (0 differences); DAILY_EQUITY=PASS (0 differences); ENDING_SUMMARY=PASS (0 differences).
18. Exposure-matched benchmark results for T2_20D: strategy 31.261535% if available; NIFTY_EX_POST_CONSTANT_AVERAGE_EXPOSURE_CASH_0=33.781948%; NIFTY_EX_POST_CONSTANT_AVERAGE_EXPOSURE_CASH_RF=172.729775%; NIFTY_PRIOR_SESSION_DYNAMIC_EXPOSURE_CASH_0=31.700756%; NIFTY_PRIOR_SESSION_DYNAMIC_EXPOSURE_CASH_RF=168.490544%. Constant-average controls are labeled `EX_POST_CONSTANT_AVERAGE_EXPOSURE`; dynamic controls use prior-session exposure. Diagnostic control; does not establish causality.
19. Friction-sensitivity results for T2_20D: 0.5x=37.916670%; 1.0x=31.261535%; 1.5x=23.991711%; 2.0x=17.933981%. The 1.0x case is 5 bps slippage plus 5 bps transaction cost per side and reuses official signals.
20. Snapshot-creation test result: **PASS**; explicit-only creation, immutable-manifest refusal, yfinance version capture, manifest hash, market-data hashes, and ticker set were tested in a temporary directory.
21. Fresh-clone reproducibility test result: **PASS**; identity hashes and Experiment ID matched across two different temporary paths.
22. Runtime: 443.715 seconds for official full benchmark.
23. Remaining known limitations: This test uses the supplied/current ticker universe and is not a survivorship-bias-free historical index-constituent study. Fresh Stage 2.1 regeneration differs from the legacy reference but has no missing/extra rows. Holiday-short weeks retain the conservative Stage 2.1 delay. Signal IDs remain attached to orders/trades by the accepted post-simulation Ticker + Signal Date join; direct dataclass lineage is deferred to Stage 2B to avoid parity risk.

Overall status: **PASS WITH WARNINGS**.

**STRATEGY RULES CHANGED: NO**  
**EXECUTION BEHAVIOR CHANGED: NO**  
**STAGE 2B IMPLEMENTED: NO**
