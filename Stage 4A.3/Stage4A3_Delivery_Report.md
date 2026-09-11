# Stage 4A.3A Delivery Report

**THIS IS PROTOCOL INFRASTRUCTURE ONLY.**

**NO REAL PROSPECTIVE OBSERVATION HAS BEEN COLLECTED.**

**NO PROSPECTIVE PERFORMANCE RESULT EXISTS YET.**

**NO MODEL WAS SELECTED USING FUTURE DATA.**

No Stage 5 has been implemented. The deterministic trading system remains the operational system; all ML predictions are shadow-only.

## Frozen references and model reconstruction

All five frozen tags resolve to their required commits. The branch merge base is the frozen Stage 4A.2 commit `4e1d852c0cacc6c7d717feb9103c3cf438d044d0`; upstream folders are unchanged. The exact requested Python and library environment was used.

| Mode | Target | Variant | Feature set | Training rows | Positives | Training cutoff | Reference rows | Max probability difference | Parity | Serialized SHA256 |
|---|---|---|---|---:|---:|---|---:|---:|---|---|
| PRIMARY_ONLY | T1_BEFORE_STOP_63 | LOGIT_FULL | FS3_FULL_SIGNAL_STATE | 807 | 308 | label available strictly before 2026-01-01 | 18 | 4.84001727585337e-13 | PASS | ae57b7d2ff86c209ff9b3559ecb6456578520100a6b4f84f0db5ad27df88aa29 |
| PRIMARY_ONLY | T1_BEFORE_STOP_63 | LOGIT_RAW | FS2_RAW_SIGNAL_STATE | 807 | 308 | label available strictly before 2026-01-01 | 18 | 4.96491736612370e-13 | PASS | 511a9d3444ff21881610fb54cb614cb59e7b94e455bba1adc8f3ab76f8484bd2 |
| TRANSFER | ENTRY_FILLED | LOGIT_FULL | FS3_FULL_SIGNAL_STATE | 13226 | 10089 | label available strictly before 2026-01-01 | 311 | 4.998224056862455e-13 | PASS | 32eb8db84c8a6430c1b7bbc742d5256babeb68375b05533c55c2c75f58c626e7 |
| TRANSFER | T1_BEFORE_STOP_63 | LOGIT_FULL | FS3_FULL_SIGNAL_STATE | 9993 | 5530 | label available strictly before 2026-01-01 | 311 | 4.987121826616203e-13 | PASS | 941efb064043e4e86405a0fb4154df8a8653a8dfbc2e54ad3f1a9942bb355bc0 |
| TRANSFER | ENTRY_FILLED | LOGIT_RAW | FS2_RAW_SIGNAL_STATE | 13226 | 10089 | label available strictly before 2026-01-01 | 311 | 4.977129819394577e-13 | PASS | a041607e6d76b35eab7d7eadbbda62be655b0aae2b9d7c0e5da3d577aab275ef |
| TRANSFER | T1_BEFORE_STOP_63 | LOGIT_RAW | FS2_RAW_SIGNAL_STATE | 9993 | 5530 | label available strictly before 2026-01-01 | 311 | 4.970468481246826e-13 | PASS | f5ea7ce10b7879ad789979675fc21101dfc94f243e8e97c2233c5131e6088fc7 |
| TRANSFER | ENTRY_FILLED | RF_FULL | FS3_FULL_SIGNAL_STATE | 13226 | 10089 | label available strictly before 2026-01-01 | 311 | 4.996003610813204e-13 | PASS | 8d9f9f09f8afc1d0f97b7304bfe8b5f64824f5588d4b225009ba790aad8a0f0b |

The maximum difference is below the fixed `1e-12` gate for every component. FS2 contains exactly 92 frozen features; FS3 contains exactly 97. Bundle mutation is detected before scoring.

## Primary hypothesis

PRIMARY CONFIRMATORY POLICY: **R3_K1**

PRIMARY COMPARATOR: **R0_K1**

If R3_K1 does not meet all ten prospective criteria, Stage 5 remains blocked. No secondary substitution is allowed.

## Holdout gate

Final analysis requires every condition below:

- at least 24 calendar months;
- at least 150 BASELINE_PRIMARY candidates;
- at least 50 R0_K1 completed D1 trades;
- at least 50 R3_K1 completed D1 trades;
- at least 100 resolved ENTRY_FILLED labels;
- at least 60 filled opportunities with resolved T1 outcomes;
- ledger chain PASS; and
- protocol integrity PASS.

There is no force, unlock, override, or ignore-minimum option. Before unlock, status output is operational counts only.

## Verification

All 118 explicit tests pass. Two independent complete Phase-A rebuilds had zero behaviorally meaningful differences across 19 compared artifacts. The historical dry run created one three-candidate snapshot only under `tests/dry_run`, confirmed rankings and chain creation, refused mutation/overwrite paths, kept outcomes separate, and kept final analysis locked.

Known limitations remain: fixed current-universe and inherited survivorship limitations, generic costs, daily-OHLC ordering ambiguity, possible provider revisions, no user-facing calibrated probability, frozen-model staleness, and a sample that may take years to mature. The material improvement is that prediction and policy are frozen before future outcomes exist.

## Final declarations

STAGE 2.2.2 MODIFIED: NO  
STAGE 2B MODIFIED: NO  
STAGE 2B.1 MODIFIED: NO  
STAGE 3 MODIFIED: NO  
STAGE 3.1 MODIFIED: NO  
STAGE 4A MODIFIED: NO  
STAGE 4A.1 MODIFIED: NO  
STAGE 4A.2 MODIFIED: NO  

STAGE 4A.2 FROZEN TAG VERIFIED: YES  
STAGE 4A.3 REAL PROSPECTIVE COLLECTION STARTED: NO  
REAL PROSPECTIVE SNAPSHOTS CREATED: 0  
REAL PROSPECTIVE OUTCOMES CREATED: 0  
FROZEN 2026 MODEL BUNDLE BUILT: YES  
HISTORICAL 2026 MODEL PARITY PASSED: YES  
PROSPECTIVE MODEL REFITTING ALLOWED: NO  
PRIMARY CONFIRMATORY POLICY: R3_K1  
PRIMARY COMPARATOR: R0_K1  
SECONDARY POLICY SUBSTITUTION ALLOWED: NO  
INTERIM PERFORMANCE PEEKING ALLOWED: NO  
MINIMUM CALENDAR DURATION: 24 MONTHS  
MINIMUM BASELINE_PRIMARY CANDIDATES: 150  
MINIMUM R0_K1 COMPLETED D1 TRADES: 50  
MINIMUM R3_K1 COMPLETED D1 TRADES: 50  
MINIMUM RESOLVED ENTRY LABELS: 100  
MINIMUM RESOLVED T1-FILLED OUTCOMES: 60  
PRODUCTION ML TRADING ENABLED: NO  
STAGE 5 IMPLEMENTED: NO  
READY FOR INDEPENDENT STAGE 4A.3 PROTOCOL AUDIT: YES
