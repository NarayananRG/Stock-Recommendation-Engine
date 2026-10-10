# Stock Recommendation Engine 0.8.5 Ultra UI

Complete desktop-shell redesign inspired by modern investment/basket dashboards while preserving the frozen production engine.

What changed
- Persistent dark sidebar, modern command bar, card/KPI layout and responsive panes.
- Dashboard rebuilt as a decision workspace.
- Opportunities rebuilt as discovery + selected-stock intelligence workspace.
- Read-only candlestick/volume chart with MA20/MA50, hover OHLCV and 1M/3M/6M/1Y ranges.
- Capital Plan rebuilt around allocation analytics, deployment donut, ranked position bars and recommendation-only basket.
- Portfolio rebuilt around composition and P&L analytics.
- Today and Live Pilot redesigned around action/readiness cards.
- Searchable plain-English Help & Glossary.
- Capital Plan uses a web-like scrollable body so charts and basket rows stay usable on shorter desktop windows.

Authority / safety
- Core production engine modules are unchanged from 0.8.4: allocation.py, combined.py, engine.py, fundamentals.py, historical.py, lifecycle.py, monitoring.py, portfolio.py and storage.py are byte-identical.
- live_pilot.py changes only the expected app-version gate from 0.8.4 to 0.8.5.
- Production scoring/ranking unchanged.
- BUY/WATCH/AVOID authority unchanged.
- Portfolio allocator policy unchanged.
- Fundamental V2 remains SHADOW_ONLY.
- No model retraining.
- No broker automation.
- Visuals have zero decision authority.

Validation
- Focused Leg 1-8 + Live Pilot + UI suite: 107/107 PASS.
- Python compileall: PASS.
- Headless Tkinter navigation/input smoke: PASS.

ZIP SHA-256:
`915425e7027fd6145298e3e467b678e6f5998a895d85c4c18a9cfec033df7edc`

Run EXTRACT_SOURCE.ps1 to reconstruct the exact source ZIP.
