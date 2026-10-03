# Next-Generation Research Lane — Audit Priorities 4–8

This additive lane implements offline, modular research infrastructure for point-in-time universes, India execution assumptions, future authoritative-source evidence, calibration governance, and model lifecycle governance.

Its authority is strictly `RESEARCH_ONLY`. It has no active prospective, trading, model-promotion, source-registry, or recommendation authority. The frozen Stage 4A.3, Stage 5D, and Stage 6 active lanes do not import it.

## Honest status

- Priority 4: `ARCHITECTURE_IMPLEMENTED / DATA_INCOMPLETE`. Only explicitly labelled synthetic fixtures are used. Survivorship bias is not claimed solved.
- Priority 5: engine implemented; verified statutory historical schedules are `NOT_CONFIGURED_FOR_PRODUCTION_RESEARCH`.
- Priority 6: candidate registry implemented as `RESEARCH_ONLY_NOT_ACTIVATED`; no live official connector or invented endpoint is included.
- Priority 7: score terminology and deterministic calibration evaluation implemented; small samples are explicitly insufficient.
- Priority 8: registry, gates, snapshots, evaluation, approval, and rollback infrastructure implemented; no real model was trained or promoted.

Run the focused offline suite with:

```powershell
python "NextGen Research/tests/run_nextgen_priority4_8_tests.py"
```

The runner performs zero network calls and writes only the committed results CSV.
