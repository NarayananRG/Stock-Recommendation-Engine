# Stock Recommendation Engine 0.8.2 Live Ready — canonical source package

This is the same application, upgraded from 0.8.1-live-pilot after manual UI review.

Fixes:
- Opportunities recommended view now contains only executable BUY candidates.
- Dashboard uses the same executable recommendation rule as Opportunities and Live Pilot.
- Capital Plan capital, horizon and desired return are editable.
- Changed Capital Plan inputs refresh the matching combined recommendation run before allocation.
- Capital Plan displays only recommended candidates, not the full analysed universe.
- Capital Plan headers are sortable.
- Selecting a Capital Plan row shows the complete Why explanation.
- 21-session allocation is supported.
- Live Pilot no longer throws on an unavailable official daily refresh; it captures a blocked dry-run snapshot and prevents live execution until readiness passes.
- Fundamental V2 is surfaced as SHADOW_ONLY when the Phase 2A.7 profile file is available. PIT partial data is never falsely relabelled complete.
- Builder searches the source folder, its parent stock-engine repo and the authoritative repo for the V2 shadow profile.

Validation:
- Focused Leg 1–8 + Live Pilot suite: 91/91 PASS.
- Headless Tkinter UI/navigation/input smoke: PASS.
- Production model retraining: NO.
- Broker automation: NO.

ZIP SHA-256:
`c099c25693b72c4ad11a3a6b7a794f47261e618d99b8515e50d912ebebd15bae`

Run `EXTRACT_SOURCE.ps1` to reconstruct the exact source ZIP.
