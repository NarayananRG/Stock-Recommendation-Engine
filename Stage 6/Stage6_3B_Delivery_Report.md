# Stage 6.3B — Event-to-Exposure Binding Foundation

## Result

PASS. Stage 6.3B adds a separate immutable `STAGE6_EVENT_EXPOSURE_BINDING_V1` store with `SHADOW_ONLY` authority. It binds caller-selected assertions from an exact Exposure version to an exact Event version. It performs verification and persistence only; it does not select or interpret the relationship.

Policy `S6EXPBINDPOL_STAGE6_3B_V1` permits only `CANDIDATE` events, the `EXPLICIT_ASSERTION_SELECTION` basis, and the explicitly supplied channels MACRO, COMMODITY, CURRENCY, RATE, GEOGRAPHY, SECTOR, and COMPANY_EXPOSURE. Its canonical hash is `93763d67799ac033691426a4fcbda0120a45605f76e416737e3dc900287851c5`.

## What Stage 6.3B does

- Binds exact immutable Event and Exposure versions and hashes.
- Binds explicitly selected Exposure assertions by canonical assertion hash.
- Persists exact assertion references and their supporting evidence union.
- Copies and binds the exact Exposure entity-registry snapshot.
- Stores one caller-supplied explicit transmission channel without inferring it.
- Enforces Event, Exposure, evidence, and selected-assertion PIT at the binding cutoff.
- Persists exact ID/hash/type dependencies for Event, Exposure, registry, policy, and evidence.
- Provides deterministic identities, canonical records, idempotent replay, append-only triggers, and full restart integrity.
- Records semantic compatibility, directional effect, and causal effect as `NOT_EVALUATED`.
- Remains `SHADOW_ONLY`.

## What Stage 6.3B does not do

- It does not choose companies, assertions, or channels automatically.
- It does not infer benefit, harm, stock direction, price reaction, expected return, magnitude, impact score, beneficiary, or loser.
- It does not propagate through corporate relationships or sectors.
- It does not modify Event transmission channels or Exposure records.
- It does not use semantic similarity, NLP, LLMs, ML, embeddings, OCR, or external data.
- It does not rank, recommend, size positions, mutate portfolios, call brokers, or trade.
- It has no Stage 5D production influence.

## Validation

| Suite | Result |
|---|---:|
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
| Stage 6.0C | PASS; 10 schemas parsed |

Frozen architecture, Stage 6.1, Stage 6.2, Stage 6.3A, and Stage 5D changed-file counts are zero. Network, LLM, ML, NLP, and trading actions are zero. Runtime artifacts committed are zero. No tag was created.

## Deferred

Semantic compatibility rules, automatic exposure/company discovery, sector/corporate/macro/commodity/currency/rate/geography propagation, direction, magnitude, beneficiary/loser classification, market reaction, historical analogues, portfolio influence, and NLP/LLM remain deferred.
