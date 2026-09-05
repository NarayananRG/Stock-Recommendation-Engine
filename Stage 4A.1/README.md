# Stage 4A.1 — Executable-Cohort Robustness Validation

This isolated research stage compares frozen Stage 4A `TRANSFER` predictions with fixed-specification `PRIMARY_ONLY` refits inside the frozen Stage 3.1 `BASELINE_PRIMARY` cohort. It performs chronological classification diagnostics, ranking diagnostics, calibration, paired overlap-aware date-block bootstrap inference, and deterministic reruns.

This experiment is historical pseudo-OOS research. Stage 4A results were already known before Stage 4A.1 was designed. Therefore Stage 4A.1 is a robustness investigation, not a new untouched holdout.

No production model is selected, no probability threshold is optimized, and no ML trading backtest is performed. Probabilities are research outputs and are not validated for user-facing confidence.

Run the executable from the repository root with the bundled Python environment. The official results are retained under `Stage 4A.1/results/`.

The corrected sanity experiment is under `tests/sanity_corrected/`. Its pending
second-official-run check is not an independent full-run acceptance result.
Use the final `results/stage4a1_validation_report.txt` and delivery report for
acceptance status. Earlier `tests/sanity_results/`, if present, is pre-fix
provisional output and must not be used for acceptance.

Log Loss is calculated only through `fixed_log_loss`, using
`np.clip(p, 1e-15, 1.0 - 1e-15)` and sklearn `log_loss(..., labels=[0, 1])`.
Saved probabilities are never clipped. Bootstrap multiplicities are expanded
only for this shared metric calculation. The canonical ranking is probability
descending, then Signal ID ascending; the bottom bucket takes its tail.

The determinism comparison excludes only `Fit Seconds` and `Prediction Seconds`
in the model-fit audit. Its separate runtime audit records the number of raw
timing differences; probabilities, labels, metrics, warnings and all other
behavioral fields remain in the comparison.

Run `tests/run_stage4a1_tests.py --phase preflight --output <test-csv>` first,
then `stage4a1/Stock_Alert_Stage4A1_Executable_Cohort.py --mode sanity
--output-dir <sanity-directory>`, then two separate `--mode official` runs.
Compare them with `--compare-reference <first-directory> --compare-candidate
<second-directory>`. Run the test suite with `--phase final` after comparison.
Use the exact environment versions recorded in the results environment report.
