# Stock Recommendation Engine 0.8.4 Visual Phase 1

Same single desktop application. Production scoring/ranking is unchanged.

Phase 1 visual intelligence:
- Opportunities single-click preview with read-only official candlestick + volume chart.
- MA20 / MA50 overlays, hover OHLCV, 1M / 3M / 6M / 1Y ranges.
- Double-click / Open full details for complete word-wrapped Why/evidence plus chart.
- Capital Plan Recommended buys + Visual allocation tabs with donut and spend-by-stock charts.
- Portfolio Holdings + Visual allocation tabs with current-value donut and P&L bars.
- Stock chart reads only the selected stock's official local CSV and caches it for responsiveness.
- Help / Glossary includes chart terminology.

Charts have ZERO decision authority.
Fundamental V2 remains SHADOW_ONLY.
No model retraining. No broker automation.

Validation:
- Focused Leg 1–8 + Live Pilot + Phase 1 suite: 102 passed, 1 skipped in Linux with protected Stage surfaces represented.
- Automated Tkinter navigation smoke: PASS.
- Embedded stock/allocation/portfolio chart smoke: PASS.

ZIP SHA-256:
`4e23a25ae25c2c28d3bf7576e677c5345713df49d4a9f7b00ccba55e43c744d8`

Run `EXTRACT_SOURCE.ps1` to reconstruct the exact test source ZIP.
