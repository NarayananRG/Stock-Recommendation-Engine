# Stage 4A.1 metric correctness review

This compares pre-fix provisional experiment `S4A1_20160101_20260828_312cd2fc8180`
with corrected experiment `S4A1_20160101_20260828_89fadf5b6425`.
The final acceptance status is in `results/stage4a1_validation_report.txt`;
this comparison alone is not a determinism or acceptance certificate.

## Shared contract

Log Loss is exactly
`sklearn.metrics.log_loss(actual, np.clip(probability, 1e-15, 1.0 - 1e-15), labels=[0, 1])`.
All point and bootstrap Log Loss paths use `fixed_log_loss`. Clipping is local
to that metric and never changes saved probabilities. Bootstrap Log Loss uses
the sampled observations, including every repeated occurrence.

Ranking uses probability descending, then Signal ID ascending. Bottom buckets
take the tail of that same canonical order. Repeated observations retain their
integer multiplicities; they are not deduplicated.

Ten regression tests cover ranking identity, ties, the original bottom-bucket
failure, repeated observations, paired samples, exact Log Loss identity,
extreme probabilities, nonmutation, shared bootstrap helper routing, and full
metric identity. The official identity audit contains 1,200 passing metric
comparisons across 50 mode/target/model groups, plus 150 ranking audit rows.
Log Loss and ranking comparisons are exact. Other vectorized metrics permit
only 1e-14 absolute floating-point rounding error, with zero relative tolerance.

## Observed changes

The comparison includes all shared prediction columns, excluding only the
deliberately changed Stage 4A.1 Experiment ID. Saved probabilities, labels,
model metadata, folds represented in predictions, and prediction row counts
are unchanged.

| Block length | Changed Log Loss values | Changed bottom-20% success values | Changed bottom-20% lift values |
| --- | --- | --- | --- |
| 63 | 43 | 71,102 | 71,102 |
| 21 | 47 | 68,797 | 68,797 |
| 126 | 27 | 68,482 | 68,482 |

The largest exported Log Loss difference is approximately 1.000089e-12.
These 117 changes are last-decimal serialization-scale changes in this dataset;
the boundary regression test separately proves the larger originally observed
clipping inconsistency is corrected. No pooled, annual, or era point Log Loss
changed, and no Log Loss bootstrap summary bound or median changed.

Bottom-bucket observation memberships did change, as demonstrated by changed
success rates for identical sampled observations. Across all scopes/models and
three block lengths, 170 bottom-success summary rows and 191 bottom-lift summary
rows have a changed bound or median. These are genuine diagnostic corrections,
not improvements in the learned predictions.

## Research conclusions

ROC AUC, Average Precision, Brier Score, Brier Skill, top-10/top-20 success and
lift, their available bootstrap summaries, and every paired TRANSFER versus
PRIMARY_ONLY delta and confidence interval remain unchanged. All final evidence
classifications are unchanged. Thus neither correction changes the preregistered
research conclusion, although bottom-bucket uncertainty diagnostics change.

No conditional T1 or T2 model meets the preregistered robust-positive definition.
Eight ENTRY_FILLED mode/model combinations and two JOINT_T1 combinations meet
that definition; these must not be presented as robust conditional target
ranking or as a production model selection.

No production ML model has been selected. No ML trading backtest was performed.
Probabilities are not validated as user-facing confidence. This is historical
pseudo-OOS research, not a new untouched holdout.
