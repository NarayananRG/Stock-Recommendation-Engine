# Stage 2.2.2 — Baseline Hardening

This folder contains the Stage 2.2.2 reproducibility and validation release for the Indian swing-trading research system.

- Official window: 2011-08-30 through 2026-08-28
- Validation: PASS WITH WARNINGS (zero failures; one documented conservative holiday-short-week limitation)
- Stage 2.2.1 acceptance parity at 1.0x friction: PASS with zero differences
- Stage 2.1 source SHA-256: `91d3d84760c4b2427d500f0bee0f2dc0ceeb7e4f2e31d51d17a64342777993d5`
- Stage 2.2.2 source SHA-256: `80b9ba6e412486dd19390ad2c74c84b20a56afdec0c0a0938fff0f6a213badfb`
- Strategy rules changed: NO

Large CSVs are stored as exact gzip-compressed files. Files that still exceed the browser transport limit are split into numbered `.part001`, `.part002`, and later pieces. Concatenate the parts in numeric order to reconstruct the `.gz` file, then decompress it normally. `UPLOAD_MANIFEST.csv` records every original filename, byte size, SHA-256 hash, and corresponding uploaded file or parts.

See `Stage2_2_2_Delivery_Report.md` and `stage2_2_2_validation_report.txt` for the full findings and audit status.
