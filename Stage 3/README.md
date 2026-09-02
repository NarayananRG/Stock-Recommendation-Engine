# Stage 3 — point-in-time research datasets

Stage 3 builds auditable historical datasets from the permanent `stage2b.1-dynamic-research-baseline` tag. It treats Stage 1, Stage 2.2.2 Final, Stage 2B, and Stage 2B.1 as read-only dependencies.

It produces three dataset families:

1. all 68,081 frozen signal states;
2. independently evaluated legitimate trade opportunities, separated into `BASELINE_PRIMARY` and `RESEARCH_EXTENDED` cohorts;
3. an **INDEPENDENT D1 SHADOW MANAGEMENT DATASET** with no portfolio-capacity or cash constraints.

No model is trained. No feature selection, target-driven threshold design, or hyperparameter tuning is performed.

## Reproduce

Use a Python environment with the packages in `requirements.txt`. From the repository root, run the sanity build first:

```powershell
python ".\Stage 3\stage3\Stock_Alert_Stage3_Dataset_Builder.py" --sanity --tickers TCS.NS INFY.NS
```

Only after every sanity gate passes, run the official build:

```powershell
python ".\Stage 3\stage3\Stock_Alert_Stage3_Dataset_Builder.py"
```

The builder fails closed on an immutable hash failure, source parity difference, candidate outcome difference, D1 shadow difference, future leakage, prefix-invariance mismatch, censored-label fabrication, or target leakage into the ML feature allow-list.

## Time semantics

- Signal/opportunity features are as of the completed signal-session close. The earliest action is the next valid session.
- Position-day features are as of the completed management-session close. Future labels begin strictly afterward.
- Pullback-limit entry bars are explicitly ambiguous. Full-bar MFE/MAE is diagnostic only; conservative MFE/MAE excludes the ambiguous entry bar.
- Target/stop collisions use conservative stop-first semantics.
- Every supervised label has a label-availability date and censoring flag.

## Limitations

The supplied current universe is not point-in-time NIFTY membership and is not survivorship-bias-free. Daily OHLC cannot establish intraday order. Historical pseudo-OOS is not prospective unseen data. Sector/index-membership history is not point-in-time. Stage 1 retains the documented holiday-short weekly delay. Costs are a generic basis-point model. No ML model has been validated.
