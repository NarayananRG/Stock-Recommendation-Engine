# Stage 4A.3 — Prospective Shadow Validation

This directory contains Phase A protocol infrastructure only. It freezes the Stage 4A.2 hypothesis, the seven reconstructed 2026 model components, the R0–R5 same-date ranking rules, an immutable prediction ledger, separately chained outcome events, operational-only status reporting, and the locked final analysis gate.

No real prospective observation has been collected. Collection is inactive until an independent audit, an immutable protocol tag, and an explicit activation run. ML remains shadow-only and cannot affect trading decisions.

Use `requirements-lock.txt` for the exact model environment. Historical runs require `--dry-run --as-of YYYY-MM-DD` and are confined to `tests/dry_run`. Production mode has no date override and refuses to operate before activation.
