# Stage 3.1 — Dataset Semantic Hardening Before ML

Stage 3.1 is a dataset-only hardening layer over the immutable Stage 3 research
artifacts. It does not change the frozen Stage 2.1 entry engine, Stage 2B/2B.1
trade-management logic, strategy thresholds, or any historical numerical target
values that are valid under the clarified semantics. It does not train, tune, or
evaluate an ML model.

## What this stage changes

- Incomplete entry windows at the end of a ticker's available history are marked
  `DATA_END_CENSORED` instead of being treated as ordinary expired entries.
- Target applicability, data-end censoring, and target status are separate fields.
  Non-entered opportunities are `NOT_APPLICABLE`, not censored observations.
- Forward-return labels have canonical, entry-inclusive horizon names. Legacy
  names remain documented aliases for reproducibility.
- Time-to-target values are populated only when their corresponding target is
  reached.
- Feature eligibility is registered per dataset. Raw date/provenance columns are
  retained for audit use but cannot be ML features.
- Walk-forward split validation reports target-specific violation counts rather
  than only a global pass/fail result.

## Frozen inputs

The builder verifies the frozen Stage 2B.1 reference and the published Stage 3
artifact hashes declared in `config/stage3_1_dataset_config.json`. All Stage 3.1
outputs are written under this directory. Earlier stage directories are read-only
inputs and must remain unchanged.

## Required execution order

From the repository root, install `Stage 3.1/requirements.txt` in the intended
Python environment if needed, then run the two-ticker sanity workflow first:

```powershell
python "Stage 3.1/stage3_1/Stock_Alert_Stage3_1_Dataset_Builder.py" --sanity --tickers TCS.NS INFY.NS
```

Proceed only when every validation gate and all 60 assertion-based tests pass:

```powershell
python "Stage 3.1/stage3_1/Stock_Alert_Stage3_1_Dataset_Builder.py"
```

Run the same full command a second time to verify deterministic reproduction of
the official artifacts.

## Output layout

- `output/sanity/` — temporary two-ticker artifacts and validation reports.
- `output/official/` — full Stage 3.1 datasets, registries, diagnostics, manifests,
  parity audits, and validation reports.
- `Stage3_1_Delivery_Report.md` — generated acceptance summary and declarations.

The datasets are research artifacts, not live-trading instructions. Dataset
coverage, the historical ticker universe, source-market-data limitations, and
the assumptions recorded in the configuration remain limitations of this stage.
