# Stage 4A — Chronological ML Classification Baselines

Stage 4A tests whether the frozen Stage 3.1 signal-time feature state contains reproducible historical predictive information for entry fill, conditional T1 success, and conditional T2 success. It also composes fill and conditional probabilities for research-only joint T1/T2 evaluation.

This is a fixed historical walk-forward / pseudo-OOS experiment. It is not a trading backtest, production model, live recommendation engine, or claim of true unseen prospective validation.

## Frozen design

- Source: permanent `stage3.1-point-in-time-ml-dataset-baseline` tag at `ac62c35f2a47bc862e406030b81f93da17c75d74`.
- Evaluation: expanding target-specific availability folds for 2016 through 2026-08-28.
- Feature sets: `FS1_RULE_SUMMARY`, `FS2_RAW_SIGNAL_STATE`, and `FS3_FULL_SIGNAL_STATE`, derived only from the Stage 3.1 registries.
- Models: training-prior dummy; fixed L2 logistic baselines; fixed Random Forest baseline.
- No tuning, feature selection, class rebalancing, probability-threshold optimization, D1 training, or ML trading P&L.

## Reproduction

Use Python 3.12.14 and the exact packages in `requirements.txt`, then run from the repository root:

```powershell
$py = "C:\path\to\python.exe"
& $py ".\Stage 4A\stage4a\Stock_Alert_Stage4A_ML_Baselines.py" --mode sanity --output-dir ".\Stage 4A\tests\sanity_results"
& $py ".\Stage 4A\tests\run_stage4a_tests.py" --mode sanity --results-dir ".\Stage 4A\tests\sanity_results"
& $py ".\Stage 4A\stage4a\Stock_Alert_Stage4A_ML_Baselines.py" --mode official --output-dir ".\Stage 4A\results"
```

The complete official experiment must be run a second time into a separate directory and compared with `--compare-reference` and `--compare-candidate`. The checked-in `stage4a_determinism_check.csv` records the exact comparison.

## Interpretation

Engineering acceptance and predictive performance are deliberately separate. Weak AUC, Brier skill, lift, or recent performance is a valid research finding and must not be repaired by changing this pre-registered experiment.
