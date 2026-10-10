# Stock Recommendation Engine 0.8.3 Live Ready — canonical source package

Same single desktop app; version 0.8.3-live-ready.

Manual-review fixes:
- Capital Plan displays only actual eligible BUY rows.
- Editing capital/horizon/target immediately clears stale allocation results.
- Capital Plan build runs in a worker thread to keep the UI responsive.
- Recommendation details are word-wrapped, remain visible, and can open in a full detail dialog.
- New Help / Glossary page explains app-specific technical terms.
- Live Readiness shows exact failed gates plus plain-English reasons.
- Fundamental V2 shadow profile file is cached instead of rescanned for every stock row.
- No model retraining, no broker automation, no Fundamental V2 authority promotion.

Validation:
- Focused Leg 1–8 + Live Pilot + 0.8.3 refinement suite: 96/96 PASS when the protected Stage surfaces are present (the Windows builder creates their authoritative junctions before tests).
- Headless Tkinter automated UI/navigation smoke: PASS.
- Source-only package without those Windows junctions naturally fails the single protected-surface existence assertion; this is environmental, not an app-code regression.

ZIP SHA-256:
`4c99dc4b1dfcbec022f436635dc8789c3e07018d57b4ef728caa8c61873f4fac`

Run EXTRACT_SOURCE.ps1 to reconstruct the exact source ZIP.


Windows build fix (10-Oct-2026): updated stale 0.8.2 version assertions and hardened SQLite backup retention against transient WinError 32 file locks. Production scoring/ranking remains unchanged.
