# Stage 4A.3A Protocol Freeze

The confirmatory policy is **R3_K1**: the product of frozen TRANSFER `ENTRY_FILLED` and conditional `T1_BEFORE_STOP_63` `LOGIT_FULL` scores, ranked descending by score and then ascending by Signal ID, selecting one same-date candidate. Its sole confirmatory comparator is **R0_K1**, ranked by Actionability Score descending, Technical Score descending, and Signal ID ascending.

Secondary policies R1, R2, R4, R5 and every K2 variant cannot substitute for R3_K1. R5 is an execution-efficiency diagnostic. D0 is secondary. There is no probability threshold, calibration, refit, adaptive feature, ML sizing, ML stop, ML target, or ML exit.

Predictions are written once after 15:45 Asia/Kolkata only when the latest stock and NIFTY bars equal the intended Signal Date. Past dates exist only in dry-run storage. Missed sessions are logged, never backfilled. Zero-candidate sessions still receive snapshots. Outcomes are separate append-only events and never modify prediction files.

Final evaluation remains locked until all gates pass: 24 calendar months, 150 BASELINE_PRIMARY candidates, 50 completed D1 trades for each of R0_K1 and R3_K1, 100 resolved entry labels, 60 filled opportunities with resolved T1 outcomes, a valid ledger chain, and no protocol drift. There is no force option.

R3_K1 confirms positive prospective economic utility only if all ten preregistered criteria pass. These include superiority on total return, CAGR and expectancy R; non-inferior profit factor; a positive 2.5% bound from the paired 63-session moving-block bootstrap; at least the 95th percentile of 500 label-blind K1 controls; drawdown no more than two percentage points worse; at least 50 completed trades; ledger integrity; and no protocol drift. Failure keeps Stage 5 blocked.
