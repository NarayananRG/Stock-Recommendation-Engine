# Stage 6.3I Delivery Report

## Result

**PASS** — Stage 6.3I adds unified Event-to-company effect normalization and conservative synthesis on the exact Stage 6.3H baseline `af059d6acd8af023056b28f2cad6ba58a7bce6da`. Authority remains `SHADOW_ONLY`.

- Schema: `STAGE6_EVENT_COMPANY_EFFECT_V1`
- Store: `STAGE6_3I_COMPANY_EFFECT_STORE_V1`
- Processor: `STAGE6_3I_COMPANY_EFFECT_SYNTHESIZER_V1`
- Policy: `S6COMEFFPOL_STAGE6_3I_V1`
- Computed policy hash: `3a92f28b24d46a8b7f6ed1ac9a77562355ae751dfce23e23ed4a9ba4dfc21786`

## Scope and routing

Stage 6.3I consumes one exact immutable Stage 6.3F or Stage 6.3H source plus its exact Stage 6.3E Match. `RATE_HIKE`, `RATE_CUT`, `TARIFF_INCREASE`, `TARIFF_REDUCTION`, `WAR_ESCALATION`, and `WAR_DEESCALATION` route only to Stage 6.3F. `CURRENCY_SHOCK`, `OIL_SHOCK`, `GAS_SHOCK`, and `COMMODITY_SHOCK` route only to Stage 6.3H. Wrong-family and unsupported Events fail closed.

- Stage 6.3F source policy: `S6DIRPOL_STAGE6_3F_V1` / `fc9c12455b5a23004523591d641620ee8caaad971be505b80128eba0d679998e`
- Stage 6.3H source policy: `S6PATHEFFPOL_STAGE6_3H_V1` / `727a1bf14fe442cf68cbb6f626c8f122550c53a7be3cf7a1ccfb60dd32848ace`

The normalized units retain the exact source family, source record identity/hash, source path, optional movement item, direction, qualification state, Event identity, and company identity. Stage 6.3I accepts no caller-supplied company conclusion and introduces no new economic interpretation.

## Synthesis

- No eligible units: `NOT_EVALUATED`
- Any incomplete eligible qualification: `INDETERMINATE`
- Any explicit `UNKNOWN`: `INDETERMINATE`
- All `FAVORABLE`: `FAVORABLE`
- All `ADVERSE`: `ADVERSE`
- Conflicting directions or explicit `MIXED`: `MIXED`

There is explicitly no weighting, magnitude, source-count preference, confidence scoring, materiality adjustment, exposure-size estimate, or price/return inference. Upstream result details are replayed and independently cross-checked against the exact upstream descriptive summary.

All stock-direction, market-reaction, magnitude, expected-return, causal-effect, portfolio-influence, and security-ranking states remain `NOT_EVALUATED`; `trading_authority` remains `false`.

## Verification

| Suite | Result |
|---|---|
| Stage 6.1A | 152/152 PASS |
| Stage 6.1B | 68/68 PASS |
| Stage 6.1C | 86/86 PASS |
| Stage 6.2A | 75/75 PASS |
| Stage 6.2B | 68/68 PASS |
| Stage 6.2C | 61/61 PASS |
| Stage 6.2D | 57/57 PASS |
| Stage 6.2E | 57/57 PASS |
| Stage 6.2F | 66/66 PASS |
| Stage 6.3A | 39/39 PASS |
| Stage 6.3B | 28/28 PASS |
| Stage 6.3C | 13/13 PASS |
| Stage 6.3D | 27/27 PASS |
| Stage 6.3E | 28/28 PASS |
| Stage 6.3F | 30/30 PASS |
| Stage 6.3G | 31/31 PASS |
| Stage 6.3H | 24/24 PASS |
| Stage 6.3I | 17/17 grouped scenarios PASS |
| Stage 6.0C | PASS, 10 schemas parsed |

The Stage 6.3I suite covers the 57 requested acceptance controls through 17 grouped scenarios: exact identities and hashes, all ten source routes, every synthesis outcome, incomplete and UNKNOWN behavior, independent summary consistency, canonical identity, idempotency/conflict guard, exact direct dependencies, no transitive evidence duplication, singleton controls, append-only triggers, restart/replay, record/unit/policy/dependency tamper detection, downstream safety, and frozen-boundary/network/AI controls.

## Boundary audit

Frozen architecture, contracts, Stage 6.1, Stage 6.2, Stage 6.3A–6.3H, and Stage 5D changed files: **0**. Runtime artifacts committed: **0**. Network calls: **0**. LLM/NLP/ML/OCR: **none**. Trading authority: **false**. Tags created: **none**.

## Deferred

Multi-Event and multi-day aggregation; path weighting; exposure magnitude; currency exposure size; commodity quantities; supply/demand/production/inventory semantics; sanction and advanced trade-role semantics; hedge effectiveness; pass-through assumptions; movement lifecycle; impact magnitude; observed market reaction; historical analogues; expected return; target price; portfolio influence; security ranking; BUY/SELL/HOLD; trading authority; and NLP/LLM.
