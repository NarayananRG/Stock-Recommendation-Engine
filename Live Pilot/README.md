# Live Pilot V1

Purpose: add a controlled ₹1,000 / 21-session live-test shell around the frozen
`0.8.0-leg8` production application without changing prediction logic.

## Authority boundary

- Production recommendation/rank/quantity stays owned by the frozen app.
- Fundamental Research V2 is **SHADOW_ONLY**.
- The live-pilot layer records readiness, provenance, immutable decision snapshots,
  manual execution details, monitoring history, and reproducibility evidence.
- No broker API and no automatic order placement are implemented.

## Current integration status

Core infrastructure is implemented independently of the UI. The production source
folder used for the accepted Leg 8 Windows build was created locally and is not
present on the research branch. Run the read-only discovery script to identify
the exact local UI/runtime integration points before patching `stock_app/main.py`.

## Discovery command

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File ".\Live Pilot\scripts\discover_leg8_app.ps1"
```

## Core test

```powershell
python ".\Live Pilot\tests\run_live_pilot_core_tests.py"
```
