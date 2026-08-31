# Stock Recommendation Engine — Stage 2.2.2 Final Static Baseline

This repository layout makes the accepted Indian swing-trading research baseline portable and difficult to invalidate accidentally. Stage 2.2.2 Final reuses the exact accepted Stage 2.1 strategy core and Stage 2.2.1 portfolio helper. It adds dependency hashing, immutable-data gates, broader point-in-time auditing, explicit warning reporting, transport reconstruction, and exact acceptance parity against the preserved Stage 2.2.2 outputs.

This is research software, not investment advice.

## Permanent source gates

- Stage 2.1 source SHA-256: `91d3d84760c4b2427d500f0bee0f2dc0ceeb7e4f2e31d51d17a64342777993d5`
- Accepted Stage 2.2.1 helper SHA-256: `8e6514353cc32a5b8bed1212df0c12d76de11d0624e4931fda4028f0be3ed31f`
- Accepted pre-finalization Stage 2.2.2 source SHA-256: `80b9ba6e412486dd19390ad2c74c84b20a56afdec0c0a0938fff0f6a213badfb`

The final source is `stage2_2_2/Stock_Alert_Stage2_2_2_Final_Baseline.py`. Its hash and portable Experiment ID are printed by each run and stored in every final output.

## Fresh-clone workflow

1. Clone the repository.

   ```powershell
   git clone https://github.com/NarayananRG/Stock-Recommendation-Engine.git
   cd Stock-Recommendation-Engine
   cd "Stage 2.2.2 Final"
   ```

2. Install the exact requirements.

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Reconstruct artifacts transported with lossless gzip compression and/or numbered parts.

   ```powershell
   python scripts/reconstruct_split_files.py
   python scripts/verify_artifacts.py
   ```

   The manifest records both the original artifact and its transport representation. The reconstruction utility validates stored gzip files, finds `.part001`, `.part002`, and later parts, enforces the exact contiguous sequence, joins them in numeric order, decompresses when required, and verifies both byte size and SHA-256. Missing, extra, out-of-order, or corrupt files fail loudly.

4. Run all 21 self-tests.

   ```powershell
   python stage2_2_2/Stock_Alert_Stage2_2_2_Final_Baseline.py --self-test
   ```

5. Run the required two-ticker sanity benchmark.

   ```powershell
   python stage2_2_2/Stock_Alert_Stage2_2_2_Final_Baseline.py --sanity
   ```

6. Only after both gates pass, run the official benchmark.

   ```powershell
   python stage2_2_2/Stock_Alert_Stage2_2_2_Final_Baseline.py
   ```

The official run is locked to 2011-08-30 through 2026-08-28, the exact frozen universe, 5 bps slippage per side, and 5 bps transaction cost per side. A stale or absent self-test/sanity receipt blocks it.

## Repository layout

```text
baseline/stage2_1/                 exact Stage 2.1 source and legacy signal reference
stage2_2_1/                        exact accepted helper, frozen market data, and helper results
stage2_2_2/accepted_results/       immutable accepted Stage 2.2.2 comparison outputs
stage2_2_2/results/                Stage 2.2.2 Final official outputs
stage2_2_2/tests/                  self-test receipts and two-ticker sanity outputs
scripts/reconstruct_split_files.py transport reconstruction with SHA-256 validation
scripts/verify_artifacts.py        repository artifact verification
artifact_manifest.csv              expected sizes and SHA-256 values
```

## Frozen snapshot creation

Ordinary tests and benchmarks never create or overwrite frozen market data. Snapshot-manifest creation runs only with the explicit flag and refuses an existing manifest:

```powershell
python stage2_2_2/Stock_Alert_Stage2_2_2_Final_Baseline.py `
  --create-frozen-snapshot `
  --frozen-data-dir <new-prepared-snapshot-directory>
```

The workflow records the exact yfinance version, validates the manifest document hash, validates every market-data SHA-256, and validates the exact ticker set.

## Interpretation constraints

- Fresh Stage 2.1 regeneration versus the legacy signal reference is a documented `WARN`, not a failure, when there are no missing/extra rows.
- The holiday-short weekly completion behavior is a documented conservative-delay `WARN`; it is not changed here.
- `EX_POST_CONSTANT_AVERAGE_EXPOSURE` uses full-period realized average strategy exposure. It is diagnostic only and is not a deployable point-in-time rule.
- `PRIOR_SESSION_DYNAMIC_EXPOSURE` uses prior-session strategy exposure for the next-session NIFTY allocation, with no same-day look-ahead.
- Exposure controls are diagnostic and do not establish causality.
- Signal IDs continue to be joined to accepted order/trade outputs by Ticker + Signal Date. Direct dataclass lineage is deferred to Stage 2B because trading parity has priority.

**STRATEGY RULES CHANGED: NO**  
**EXECUTION BEHAVIOR CHANGED: NO**  
**STAGE 2B IMPLEMENTED: NO**
