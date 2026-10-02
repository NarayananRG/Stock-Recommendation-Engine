# Stage 6.8B Delivery Report

`IMPLEMENTATION_STATUS = PASS`

`PROSPECTIVE_COHORT_STATUS = ALREADY_ACTIVE_EXTERNAL_RUNTIME`

`LIVE_PRIMARY_SOURCE_CAPTURE_STATUS = NOT_RUN_BY_CODEX`

Codex did not inspect or mutate the external activation, prospective database, dedicated Stage 5D.5 control database, or any Stage 4A.3 runtime file. All implementation tests used temporary fixture roots and fixture transports.

## Identity

- Branch: `stage6-prospective-shadow-validation`
- Stage 6.8B correction baseline: `944ab3ef833f564d4966c2f6312781d2628e7c90`
- Stage 6.8A parent baseline: `95696d7e616a798d87c81936125bacdb9f441f2e`
- Operations contract: `STAGE6_8B_PROSPECTIVE_OPERATIONS_CONTRACT_V1`
- Operations contract hash: `97f9eb9e551d9104291a21f7c9f935390fbd1359a6d472581ff6ce6a612eb9a4`
- Daily operator: `STAGE6_8B_DAILY_OPERATOR_V1`
- Policy: `S6PROSOPSPOL_STAGE6_8B_V1`
- Policy hash: `582825a16b9ae40821dacb89c7e5711fd16998153557f2fc6315ca75e5088ec9`
- Source coverage schema: `STAGE6_8B_SOURCE_COVERAGE_V1`
- Primary capture schema: `STAGE6_8B_PRIMARY_EVIDENCE_CAPTURE_V2`
- Capture summary store: `STAGE6_8B_CAPTURE_SUMMARY_STORE_V2`
- Pre-session readiness schema: `STAGE6_8B_PRE_SESSION_READINESS_V1`
- Authority: `SHADOW_ONLY`; trading authority: `false`

## Source capability attestation

- Source coverage result: PASS
- Activated V1 operational primary source set: `{SEBI_OFFICIAL_RSS, RBI_OFFICIAL_PRESS_RELEASES_RSS}`
- Operational primary source count: 2
- Source Registry V2: `S6SRCREG_39b7deae3a0e811e7327af2c` / `7d91f4c72365757b6cdfaef0c4027c46bfbdb11c3541c229e828f9ee28d58e90`
- Entity Registry V2: `S6ENTREG_2aed0e083e1186bcade4ede9` / `23438181ad6b3cea20c1bc2f4b3cd4236f5f3a1d5bbfcbb5c8cf0b3d0a2a258f`
- SEBI: PRIMARY_OFFICIAL, VERIFIED, enabled, automation allowed, terms reviewed/allowed, machine accessible, no authentication, free, connector implemented
- RBI: PRIMARY_OFFICIAL, VERIFIED, enabled, automation allowed, terms reviewed/allowed, machine accessible, no authentication, free, connector implemented
- YFINANCE_STAGE6_EVIDENCE_STATUS: `NOT_APPROVED_NOT_REGISTERED`
- Stage 4A.3 yfinance distinction: frozen market-data dependency outside Stage 6 evidence
- Stage 5D yfinance distinction: frozen control dependency outside Stage 6 evidence
- Additional-source gap: `NOT_IMPLEMENTED_IN_ACTIVATED_V1`
- No source expansion result: PASS

Additional primary-source connectors are desirable for a broader future system, but they are not added to the already-active V1 cohort. A broader set requires a new registry version, reviewed connector implementation, deterministic tests, explicit protocol versioning, and a separate prospective activation boundary where applicable.

## Independent Audit Corrections

1. The original readiness aggregation incorrectly counted `QUARANTINED` as usable. `QUARANTINED` remains an exact preserved source status but is now operationally unusable.
2. Only `RETRIEVED` and `PARTIAL` are usable. One usable source produces `PARTIAL`; two produce `AVAILABLE`; zero after an attempted capture produces `FAILED`.
3. Every capture is explicitly bound to a caller-supplied ordinary NSE `target_session_date`; no latest, maximum, or automatic session discovery exists.
4. Capture must start and complete on the target date in IST and strictly before 09:15 IST. A deadline-crossing capture preserves acquired evidence but records `LATE_NOT_ELIGIBLE`.
5. Readiness independently verifies the exact activation schema, activation ID, and activation record hash.
6. Source and entity Registry V2 IDs and hashes are exact; Registry V3 is neither accepted nor created.
7. Capture summaries must contain exactly the frozen SEBI and RBI source set, once each, with no third or fallback source.
8. Prior-date, future-date, wrong-target, and otherwise stale capture summaries fail closed.
9. Cross-activation summaries fail with an explicit activation-binding mismatch.
10. Post-deadline summaries fail closed. The full summary store is opened with SQLite `mode=ro`, enables `query_only`, and verifies metadata, triggers, canonical JSON, record hashes, schema, authority, and trading authority before resolving the exact capture ID.

## Operator commands

- `status`: read-only activation/cohort/control status; absent databases are not created; only `ACTIVE_COLLECTING` and `MINIMUM_WINDOW_REACHED` are emitted.
- `attest-sources`: offline attestation from frozen registry builders and the exact endpoint allowlist.
- `capture-primary-evidence`: requires `--target-session-date` and `--live`; the target must be the current IST date, an ordinary pinned-calendar NSE session strictly after activation, and the operation must begin before 09:15 IST. Only frozen SEBI/RBI connectors are called, at most once each per source invocation except bounded redirects. Failures remain acquisition evidence and never become no-news or safety conclusions.
- `enroll-control`: requires an exact run ID and wraps the Stage 6.8A exact enrollment operation without running Stage 5D.5.
- `pre-session-check`: read-only validation of exact origin/session/pending/calendar/deadline readiness; it generates no proposal or decision.

Normal commands make zero network calls. Only a manually invoked, audited `capture-primary-evidence --target-session-date YYYY-MM-DD --live` command can contact the two approved endpoints. Codex did not run it. Fixture capture proved AVAILABLE, PARTIAL, FAILED, QUARANTINED-as-unusable, late-evidence retention, target/activation/registry/source-set binding, immutable summaries, read-only full-store verification, and full ingestion-store integrity.

## Boundaries and verification

- LLM/NLP/ML/OCR/embeddings/semantic similarity: false
- Broker calls: 0
- Order creation/cancellation and BUY/SELL/FILL authority: prohibited
- Quantity, stop, and target mutation: prohibited
- Stage 5D mutation: prohibited
- Outcome scoring: deferred
- Stage 6.8B: 392/392 PASS
- Previous Stage 6: 5,346/5,346 PASS
- Combined Stage 6: 5,738/5,738 PASS
- Stage 6.0C: PASS / 10 schemas
- Frozen files outside Stage 6.8B changed: 0
- Stage 5D changes: 0
- Stage 4A.3 changes: 0
- Runtime artifacts committed: 0
- Stage 6.8B correction files changed: 11
- Tags created: 0

Outcome attachment/scoring, Stage 6.8C, Stage 6.9, broader connectors, protocol changes, and all production authority remain deferred.
