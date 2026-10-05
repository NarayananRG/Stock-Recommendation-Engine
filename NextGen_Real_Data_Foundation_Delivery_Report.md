# NextGen Research — Real Data & Evidence Foundation

## Result

**PASS WITH EXPLICIT DATA GAPS.** This stage adds research-only, provenance-bound real-data foundations. It does not claim complete historical coverage, solve survivorship bias, activate a source, retrain a model, influence a recommendation, or acquire trading authority.

## Git and isolation

- Branch: `nextgen-research-real-data-foundation`
- Exact parent: `c6e03f9e1ee3cab6600e441ebc7390819716fdb2`
- Parent active-prospective baseline: `875beb75984d869aaf40799e7d7810743722eda0`
- Active Stage 4A.3, Stage 5D, and Stage 6 changed files: **0**
- Reverse dependencies from the active lane into `NextGen Research/`: **0**
- Raw bulk archives, databases, caches, and runtime artifacts committed: **0**
- Authority: `RESEARCH_ONLY`; trading/model/production authority: **NONE**

## Real PIT universe evidence

The immutable source manifest binds an operator-acquired official NSE equity security-master CSV (2,593 rows; SHA-256 `95f0d731f5858f71e876c45377dcefa79bc7a8db1e8161d0c92320252af4aa8f`) and official NSE delisted-company workbook (457 rows; SHA-256 `fcc27d5850f381fa0193003ddbd4d2f7724c770e9082d7fbbad6b97dd87f1664`). Delisting effective dates cover 2002-04-15 through 2026-09-02. The committed fixtures are small sanitized subsets; the full downloads remain ignored.

The real demonstration is `REAL_VERIFIED_CURRENT_SNAPSHOT_PARTIAL_HISTORY`. It uses five sanitized records tied to the 2,593-record archive. Official listing dates are retained when present; first observation is never silently converted into a verified listing date. Delistings affect PIT eligibility. Duplicate official identities fail closed.

Limitations are explicit: `HISTORICAL_SECURITY_MASTER_NOT_AVAILABLE`, `HISTORICAL_INDEX_MEMBERSHIP = DATA_GAP`, historical sector membership `UNKNOWN`, BSE delisting history not ingested, and the NSE delisting workbook is not claimed complete. Survivorship bias fully solved: **NO**.

## India execution schedule

`INDIA_EQUITY_COST_SCHEDULE_V1` has canonical hash `07a13200b53ec82a36d4a100bc8914789d3525539fb83762c5074d85cbe01afa` and starts 2024-10-01. It binds official references for NSE exchange transaction charges, SEBI turnover fees, delivery STT, delivery stamp duty, and GST. It models GST only over explicitly named taxable components. Brokerage is a separate configurable `BROKER_SPECIFIC_COST`, never a universal statutory charge.

Dates outside verified coverage fail with `COST_SCHEDULE_NOT_VERIFIED_FOR_DATE`; current rates are not carried backwards. Historical schedules before the combined verified period remain uncovered. Component calculations use deterministic INR 0.01 research rounding, with the lack of independently verified component-specific statutory precision recorded as a limitation.

## Future authoritative sources

| Source | State | Connector | Parser | PIT semantics and restrictions |
|---|---|---:|---:|---|
| NSE equity security master | `VERIFIED_IMPLEMENTED` | No | Yes | Retrieval observation and official listing date; operator acquisition only |
| NSE delisted companies | `VERIFIED_IMPLEMENTED` | No | Yes | Official effective delisting date and retrieval time; operator acquisition only |
| NSE announcements | `VERIFIED_NOT_IMPLEMENTED_AUTOMATION_RESTRICTED` | No | Offline structure fixture | Exchange-received, dissemination, and broadcast timestamps retained; no anti-bot bypass |
| NSE corporate actions | `VERIFIED_NOT_IMPLEMENTED` | No | No | Effective-date semantics require further verification |
| BSE filings/notices | `VERIFIED_NOT_IMPLEMENTED_AUTOMATION_RESTRICTED` | No | Offline structure fixture | Independently verified BSE publication semantics; no stable machine endpoint assumed |

Parsers normalize factual fields only. They do not invent event direction, investment impact, bullish/bearish conclusions, or expected price movement. Unit tests perform zero live retrievals.

## Frozen-output calibration audit

The audit binds seven actual stored Stage 4A prediction streams to the frozen Stage 4A.3 model bundle `4631eb8a1d0b34212252df3b1aae180f64ec98ba5e7955a84729df0a471c62da`; no predictions were regenerated and no model was retrained.

| Model | N | Positive / negative | Brier | Brier skill | Classification |
|---|---:|---:|---:|---:|---|
| `PRIMARY_ONLY_T1_LOGIT_FULL` | 13 | recorded in audit | — | — | `INSUFFICIENT_EVIDENCE` |
| `PRIMARY_ONLY_T1_LOGIT_RAW` | 13 | recorded in audit | — | — | `INSUFFICIENT_EVIDENCE` |
| `TRANSFER_ENTRY_LOGIT_FULL` | 289 | 229 / 60 | 0.1567277418 | 0.0473029314 | `UNCALIBRATED_MODEL_SCORE` |
| `TRANSFER_T1_LOGIT_FULL` | 185 | 96 / 89 | 0.2281291124 | 0.0861752257 | `UNCALIBRATED_MODEL_SCORE` |
| `TRANSFER_ENTRY_LOGIT_RAW` | 289 | 229 / 60 | 0.1557072430 | 0.0535062124 | `UNCALIBRATED_MODEL_SCORE` |
| `TRANSFER_T1_LOGIT_RAW` | 185 | 96 / 89 | 0.2226175661 | 0.1082530196 | `UNCALIBRATED_MODEL_SCORE` |
| `TRANSFER_ENTRY_RF_FULL` | 289 | 229 / 60 | 0.1429403953 | 0.1311117355 | `UNCALIBRATED_MODEL_SCORE` |

Reliability buckets, calibration slope/intercept, temporal groups, and sufficiently sampled regime groups are emitted in the audit artifact. Positive Brier skill alone does not promote probability terminology. The compatibility terminology audit does not modify any legacy artifact.

## Drift foundation

`MODEL_DRIFT_ASSESSMENT_V1` supports feature and score distribution shifts, calibration degradation, outcome-rate shifts, regime and sector composition shifts, volatility/liquidity shifts, and benchmark-relative deterioration. States are `STABLE`, `POSSIBLE_DRIFT`, `MATERIAL_DRIFT`, and `INSUFFICIENT_DATA`. Thresholds are research configuration and default to `NOT_CONFIGURED_FOR_AUTOMATIC_ACTION`.

Drift may contribute evidence to offline challenger-research eligibility only when sample sufficiency, outcome maturity, and benchmark comparability also pass. A single metric cannot trigger retraining. Automatic training, promotion, or active action authority: **NONE**.

## Artifacts and identities

- Raw-source manifest: `NEXTGEN_REAL_SOURCE_ARCHIVE_MANIFEST_V1`; file SHA-256 `954b744f38f8cbb80be6c078751bc95e5d267efcf5a7f624877f9fb1ace794f6`
- Verified-source registry: `NEXTGEN_VERIFIED_SOURCE_EVIDENCE_V1`; file SHA-256 `24954f80f71dfc4aeba5661e17c624efeb880762d0ad1ce39ba7786ddd088948`
- Real universe record: `PIT_UNIVERSE_SNAPSHOT_V1_eb2a4c43abcaaec3c264cb2a`; record hash `eb2a4c43abcaaec3c264cb2aff1bd2f477d63c646a22e58c665d3878f29a0854`
- Calibration audit: `REAL_CALIBRATION_AUDIT_V1_e83c661b3281a0b90fcbb31c`; record hash `e83c661b3281a0b90fcbb31cf1dc47f448ab9d4d3415f9127f7c533738da0afe`
- Coverage report: `NEXTGEN_DATA_COVERAGE_REPORT_V1`; file SHA-256 `9111991a9483cc908e1f52bf8e15bafd024d1b6fb6f08173901ea516c9773349`
- Foundation manifest: `NEXTGEN_REAL_DATA_FOUNDATION_MANIFEST_V1_060666117ecb2c3fc65dbd8b`; record hash `060666117ecb2c3fc65dbd8b17a454534810900d71820b9e0cd04149ec65ff6b`

## Verification

- Focused real-data tests: **58/58 PASS**
- Existing NextGen foundation regression: **104/104 PASS**
- Stage 6.8C regression: **170/170 PASS**
- Full Stage 6 regression: **5,908/5,908 PASS** across 39 suites
- Stage 5D regression: **606/606 PASS**
- Stage 6.0C validator: **PASS / 10 schemas**
- Test network calls: **0**

Active identities before and after are identical:

- Stage 4A.3 model bundle: `4631eb8a1d0b34212252df3b1aae180f64ec98ba5e7955a84729df0a471c62da`
- Stage 4A.3 source package: `cc1b7bfc85c77e40f029a5ccff670e531445e5051932dab7e7e8abd2116bdc2f`
- Stage 6 V1 source registry: `7d91f4c72365757b6cdfaef0c4027c46bfbdb11c3541c229e828f9ee28d58e90`
- Stage 6.8C policy: `78f0d43da4826896801f030646622fe1324101b592cd178642c67120bdfbfa94`
- Stage 6.8C contract: `8f7fce02be208cfbe2c0c6e95f5127323b5b871c50ff3fa68a451c418ace093e`
- Activation: `S6PROSACT_7a2195d6a80d73508727c088` / `0f3e6f69de267a85d6fd9f1937bc71f926a01fdfad162d18b5c2401275e64336`

## Stop boundary

Active model retrained: **NO**. Challenger trained: **NO**. Challenger promoted: **NO**. Recommendation logic changed: **NO**. New sources activated into Stage 6 V1: **NO**. Live prospective evidence mutated: **NO**. Tag created: **NO**.

The recommended next stage, after independent review, is a bounded evidence-completion stage for dated official security-master/index/sector archives and effective-dated historical fee schedules. Advanced model development must not start until coverage and calibration governance are accepted.
