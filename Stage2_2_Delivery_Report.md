# Stage 2.2 — Realistic Portfolio Backtester

## Delivery status

Stage 2.2 is implemented and the complete benchmark ran from **2011-08-30 through 2026-08-28**.

- Synthetic tests: **PASS**
- Two-ticker short integration: **PASS**
- Full portfolio validation: **PASS** (15/15 checks)
- Full cached rerun: **300.30 seconds**
- Candidate source for the benchmark: **saved Stage 2.1 reference replay**

The frozen Stage 2.1 `FeatureEngine` and `FrozenStrategy` are imported unchanged. Stage 2.2 changes portfolio selection, order state, execution, accounting, reporting, and validation only.

## Bugs and methodological defects fixed

1. Added per-ticker `FLAT → PENDING_ORDER → OPEN_POSITION → FLAT` state. Duplicate pending/open signals are logged and ignored; pyramiding is prohibited.
2. Restricted primary entries to `BUY` and `STRONG BUY`. WATCH/WAIT/AVOID states remain research candidates only.
3. Replaced exit-order compounding with chronological cash, positions, close mark-to-market, daily equity, peaks, and daily drawdown.
4. Separated execution slippage from transaction costs so each is charged exactly once.
5. Added five-position capacity and deterministic same-day ranking.
6. Added risk, cash, and 25%-of-equity position sizing constraints with integer quantities and recorded binding constraints.
7. Added conservative daily-OHLC rules: gap-through execution, stop-first collisions, and no target credit on an intraday pullback-fill bar.
8. Isolated all ten T1/T2 and 10/20/30/45/63-session portfolio variants.
9. Added year, period, stock, setup, regime, score-band, score-matrix, candidate, order, trade, and data-availability reports.
10. Added hard portfolio, accounting, cost, signal-state, date, price-level, and parity validation.

## Full benchmark portfolio summary

| Variant | Ending equity | Net return | Trades | Win rate | Expectancy | Profit factor | Max drawdown |
|---|---:|---:|---:|---:|---:|---:|---:|
| T1_10D | ₹117,449.95 | 17.45% | 357 | 46.50% | 0.0637R | 1.1300 | -12.49% |
| T1_20D | ₹108,731.70 | 8.73% | 340 | 40.88% | 0.0270R | 1.0567 | -17.06% |
| T1_30D | ₹112,253.89 | 12.25% | 338 | 39.94% | 0.0534R | 1.0762 | -18.00% |
| T1_45D | ₹114,566.24 | 14.57% | 337 | 39.76% | 0.0602R | 1.0884 | -16.96% |
| T1_63D | ₹115,648.07 | 15.65% | 336 | 39.88% | 0.0650R | 1.0938 | -16.57% |
| T2_10D | ₹122,233.83 | 22.23% | 355 | 45.92% | 0.0759R | 1.1660 | -12.83% |
| T2_20D | ₹126,896.84 | 26.90% | 335 | 39.10% | 0.0937R | 1.1599 | -18.61% |
| T2_30D | ₹120,227.76 | 20.23% | 327 | 35.78% | 0.0797R | 1.1156 | -20.05% |
| T2_45D | ₹120,215.38 | 20.22% | 322 | 34.16% | 0.0804R | 1.1144 | -18.98% |
| T2_63D | ₹120,510.51 | 20.51% | 320 | 33.44% | 0.0850R | 1.1109 | -21.25% |

These are nominal results before tax and inflation. No strategy variant should be selected from these in-sample results alone.

## Important diagnostics

- T2_20D had the highest ending equity, but only **+26.90% over roughly 15 years**; this is a thin economic edge despite a positive expectancy.
- Performance weakened over time. T2_20D period returns were +13.76% (2011–2015), +8.92% (2016–2020), +2.93% (2021–2023), and **-0.50% (2024–2026)**.
- T1_63D was also negative in 2024–2026 (-0.98%); T2_63D was -3.77%.
- `STRONG BULL` and `BULL` portfolio entries were positive, while `NEUTRAL` was negative across the highlighted variants.
- Breakouts were much stronger than pullbacks but had only **22 trades per highlighted variant**, so the sample is small.
- T2_20D’s strongest stock contributions included INFY and M&M; ICICIBANK, SUNPHARMA, TCS, and SBIN were negative. This is diagnostic and is not a basis for in-sample stock removal.
- Candidate research still shows WATCH outperforming BUY, confirming that score/action labels are not monotonically calibrated. Thresholds were not changed.

## Reference replay and reproducibility warning

The exact Python/yfinance environment that produced Stage 2.1 is no longer available locally. The current runtime regenerated the same 68,081 ticker-date rows but differed from the saved reference on 8,208 rows at the configured floating tolerance, including 342 signal labels. The count itself changed between fresh provider downloads, demonstrating upstream data/runtime instability.

Therefore the completed portfolio benchmark explicitly used the supplied `stage2_1_signal_log_15y.csv` as the immutable point-in-time candidate source. Its full candidate-set parity is 68,081/68,081 with zero mismatches. Current regeneration drift is retained in `stage2_2_signal_parity_differences.csv`; it is not hidden.

## Unresolved assumptions

- Opening-gap exits free capacity for that session; capacity from unknown-time intraday exits is not reused until the next session.
- A marketable pullback limit order that gaps below its planned zone fills at the better open. It is rejected if that execution invalidates stop/target ordering.
- Candidate research uses T1 with a 63-session maximum and normalized R-based profit factor.
- R:R research bands are `<1.5`, `1.5–1.99`, `2.0–2.49`, `2.5–2.99`, and `3.0+`.
- Daily mark-to-market uses the close without hypothetical liquidation cost; costs are realized only at actual entry/exit.
- The supplied/current stock universe is not a survivorship-bias-free historical index-membership dataset.

## Output files

Source:

- `Stock_Alert_Stage2_2_Realistic_Portfolio_15Y.py`

Core reports:

- `stage2_2_candidate_signal_log.csv`
- `stage2_2_candidate_outcome_summary.csv`
- `stage2_2_signal_type_summary.csv`
- `stage2_2_score_band_summary.csv`
- `stage2_2_score_matrix.csv`
- `stage2_2_order_log.csv`
- `stage2_2_portfolio_summary.csv`
- `stage2_2_portfolio_trade_log.csv`
- `stage2_2_yearly_summary.csv`
- `stage2_2_period_summary.csv`
- `stage2_2_stock_summary.csv`
- `stage2_2_setup_summary.csv`
- `stage2_2_regime_summary.csv`
- `stage2_2_data_availability.csv`
- `stage2_2_signal_parity_differences.csv`
- `stage2_2_validation_checks.csv`
- `stage2_2_validation_report.txt`
- `stage2_2_methodology_notes.txt`

Daily equity:

- `stage2_2_daily_equity_T1_10D.csv`
- `stage2_2_daily_equity_T1_20D.csv`
- `stage2_2_daily_equity_T1_30D.csv`
- `stage2_2_daily_equity_T1_45D.csv`
- `stage2_2_daily_equity_T1_63D.csv`
- `stage2_2_daily_equity_T2_10D.csv`
- `stage2_2_daily_equity_T2_20D.csv`
- `stage2_2_daily_equity_T2_30D.csv`
- `stage2_2_daily_equity_T2_45D.csv`
- `stage2_2_daily_equity_T2_63D.csv`

## Interpretation

Stage 2.2 finds a small positive historical edge under realistic portfolio constraints, but not a strong or stable one. The recent period is weak, candidate labels remain poorly calibrated, breakout evidence is based on a small sample, and the universe has survivorship bias. The system is not ready for strategy optimization, machine learning, or real-money use. The appropriate next research action is to review Stage 2.2 diagnostics and design an out-of-sample/walk-forward evaluation plan without changing the frozen thresholds yet.
