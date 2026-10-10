# Stock Recommendation Engine 0.8.1 Live Pilot — canonical source package

This directory stores the reconstructed accepted Leg 8 source plus the Live Pilot UI patch as a single canonical source archive.

It is **the same Stock Recommendation Engine application**, not a second application. The executable remains `StockRecommendationEngine.exe`; the version is `0.8.1-live-pilot`.

Source reconstruction order:
1. `stock-engine-leg7-source-with-windows-builder.zip`
2. `LEG8_FINAL_EXE_PATCH_0.8.0.zip`
3. `LEG8_FINAL_HOTFIX_UPDATE_AND_CAPITAL_PLAN.zip`
4. Live Pilot V1 UI/core patch

Source ZIP SHA-256:
`d7498556d214ab012ac38d11745bdee984b803a6a789e76c40319bccbc2091c9`

Local validation performed before upload:
- Python compile: PASS
- Live Pilot + Leg 7/8 focused tests: 25/25 PASS
- Full focused Leg 1–8 + Live Pilot structural suite: 89/89 PASS when Windows-only protected Stage junctions are represented
- Headless Tkinter UI smoke: PASS (exit 0), including the Live Pilot page

Run `EXTRACT_SOURCE.ps1` to reconstruct the source folder from the base64 archive parts.

Inside the extracted source:
- `RUN_LIVE_PILOT_SOURCE_TEST.cmd` launches the same app from source for fast testing.
- `BUILD_LIVE_PILOT_TEST_APP.cmd` builds the Windows `StockRecommendationEngine.exe` test package.
- Fundamental Research V2 stays `SHADOW_ONLY` and cannot change production rank/action.
\n\nBuild-script hotfix (10-Oct-2026): corrected PowerShell booleans in `scripts/build_leg8_final.ps1` from `false` to `$false` for the final manifest fields.\n