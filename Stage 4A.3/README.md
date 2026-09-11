# Stage 4A.3 — Prospective Shadow Validation

This directory contains the hardened Phase A protocol infrastructure. It freezes the Stage 4A.2 hypothesis, the seven reconstructed 2026 model components, the R0–R5 same-date ranking rules, the exact frozen signal-close input builder, an immutable prediction ledger, globally chained append-only outcome batches, ledger-derived operational reporting, and the complete locked final evaluator.

No real prospective observation has been collected. Collection is inactive until an independent audit, an immutable protocol tag, and an explicit activation run. ML remains shadow-only and cannot affect trading decisions.

Use `requirements-lock.txt` for the exact model environment. Historical input files are accepted only with `--dry-run --as-of YYYY-MM-DD`, and custom dry-run output must remain below `tests/`. Production mode has no date or input override, runs the exact frozen builder itself, and refuses to operate before activation. `scripts/run_after_close.ps1` is the production snapshot entry point; `stage4a3.outcome_runner` computes later outcomes from immutable snapshots and a hash-verified future-bar archive.

The committed test fixtures are explicitly non-production. `tests/dry_run_hardened` demonstrates the snapshot contract, `tests/SYNTHETIC_OUTCOME_RESOLUTION_FIXTURE` exercises computed Stage 3.1 and Stage 2B.1 outcomes, and `tests/SYNTHETIC_MATURED_PROSPECTIVE_FIXTURE` proves locked/unlocked final evaluation. The real `prospective/snapshots` and `prospective/outcomes` directories remain empty and `prospective/audit/activation_record.json` remains absent.
