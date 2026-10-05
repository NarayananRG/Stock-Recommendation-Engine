# NextGen Research — Restricted Window Closure Delivery Report

This report records the immutable research outcome for the 2024-10-01 through
2026-10-01 restricted window. It is a governance record, not legal advice, and
does not grant model, recommendation, trading, or broker authority.

1. **Overall result:** PASS — technical data readiness is complete; model-training usage rights remain pending.
2. **Branch:** `nextgen-research-restricted-window-closure`.
3. **Commit SHA:** reported from Git after the delivery commit; a commit cannot truthfully embed its own SHA.
4. **Parent SHA:** `19c5d0823c30947c5fdeec3bba4e7738cd343436` (exact).
5. **Siemens lifecycle:** RESOLVED — `DUMMYSIEMS` was nontradable, `ENRIN` listed 2025-06-19, temporarily exited 2025-06-27, and entered through the regular review effective 2025-09-30.
6. **ABLBL lifecycle:** RESOLVED — `DUMMYABFRL` was nontradable, `ABLBL` listed 2025-06-23, temporarily exited 2025-06-27, and entered through the regular review effective 2025-09-30.
7. **Tata Motors lifecycle:** RESOLVED — `DUMMYTATAM` was nontradable, `TMCV` listed 2025-11-12, and the temporary index treatment exited effective 2025-11-17; the `TMPV` predecessor identity is retained.
8. **Vedanta lifecycle:** RESOLVED — all four official dummy mappings are independently bound to `VAML`, `VEDPOWER`, `VOGL`, and `VISL`, with listing and exit dates.
9. **Remaining unresolved lifecycle events:** 0.
10. **Index dummy classification:** `INDEX_ACCOUNTING_PLACEHOLDER_NONTRADABLE`; a dummy is never a model candidate.
11. **Investable-universe rules:** historical membership, actual NSE-listed tradability, stable identity, real market history, resolved action state, and completed lookback are all mandatory.
12. **Maximum feature lookback:** 60 trading sessions.
13. **Warm-up policy:** the first 60 real post-listing sessions are excluded; synthetic pre-listing and dummy-price splicing are prohibited.
14. **Restricted identity coverage:** complete for the investable universe; missing and ambiguous investable identities are both 0.
15. **Historical symbols resolved:** 620 investable symbols are retained in the survivorship population; 609 non-dummy market symbols have source-bound observations.
16. **Predecessor/successor chains resolved:** 7.
17. **Restricted survivorship:** `COMPLETE_FOR_RESTRICTED_INVESTABLE_UNIVERSE`; unknown investable identity share is 0.0%.
18. **Price normalization V2:** `COMPLETE_PIT_SAFE_WITH_RESETS`; future action knowledge is prohibited.
19. **Corporate-action continuity:** `COMPLETE_VERIFIED`; unresolved blocking actions are 0.
20. **Momentum readiness:** `PIT_SAFE_FOR_ELIGIBLE_SECURITIES`.
21. **Volatility readiness:** `PIT_SAFE_FOR_ELIGIBLE_SECURITIES`.
22. **Technical readiness:** `PIT_SAFE`.
23. **Liquidity readiness:** `FULL_LIQUIDITY_AVAILABLE`.
24. **Benchmark readiness:** technically complete for 497 sessions; usage rights are separately gated.
25. **Complete technical-data readiness:** `TECHNICALLY_READY_WITH_RESTRICTED_PERIOD` with no failed technical gates.
26. **Panel provenance sources:** 497 source files from the official NSE public historical-report archive, each with date, row count, and SHA-256.
27. **Public-report row count:** 1,579,133.
28. **MCP-derived row count:** 0.
29. **MCP usage-right status:** model training is prohibited without separate permission; no MCP rows are used.
30. **Public-report usage-right status:** `MODEL_TRAINING_RIGHTS_NOT_ESTABLISHED` / `PERMISSION_REQUIRED`.
31. **Benchmark usage-right status:** `LICENSE_REQUIRED`, assessed independently for NIFTY 50 and NIFTY 500.
32. **Model-training rights status:** `LICENSE_REQUIRED`; the gate remains closed.
33. **V1 preserved:** PASS, SHA-256 `70b603aecd427e9947d4fbf4a68b9eb6f32ff2c1151a930049300d343c5ba6b4`.
34. **V2 preserved:** PASS, SHA-256 `7ec465cdf4178593d48dc7b89b690b581cd31ce97f06b505c04158da0244b1fb`.
35. **V3 preserved:** PASS, SHA-256 `67cf2cafee7d7beab308440f8bc4b9c6d1df85bd8608d9b540074211a600ce74`.
36. **V4 preserved:** PASS, SHA-256 `f85e4af7ee5ab832da15a3be1b356c659e5cbe0adac3dfd4b2fc5d36205b7b57`.
37. **V5 preserved:** PASS, SHA-256 `fc67f9d02804a3cc1bdfb04237ad37fdfe4229c4850f980eb22317bbd2f51b49`.
38. **V6 status:** `TECHNICALLY_READY_RIGHTS_PENDING`.
39. **V6 failed gates:** technical gates `[]`; model-training usage-right gate is false.
40. **Restricted period:** 2024-10-01 through 2026-10-01, 24 months, 497 trading sessions.
41. **Decision V1 preserved:** PASS, SHA-256 `afba30e325b6924286e0f8e2bcc7edcf2b9f779fb2f4ac966333d29e925a2c3d`.
42. **Decision V2 preserved:** PASS, SHA-256 `f573b8b28ecb5fa15db36be2e8dc4b655ed22134fed7a073cfe3d4b045090dd1`.
43. **Decision V3:** `LICENSE_REQUIRED_FOR_MODEL_TRAINING`.
44. **Paid historical constituent data technically needed:** NO.
45. **Separate permission/licence required for model training:** YES, for intended use of NSE market data and NSE Indices benchmark data.
46. **Files created:** 25 delivery files under `NextGen Research/` (implementation, acquisition/build scripts, test suite, report, and result artifacts).
47. **Files modified:** 1 — `NextGen Research/restricted_window/__init__.py`.
48. **Raw bulk files committed:** 0.
49. **Focused tests:** 140/140 PASS.
50. **Regressions:** restricted window 128/128; free reconstruction 131/131; authoritative data 83/83; other NextGen 247/247; Stage 6.8C 170/170; Stage 5D 606/606; Stage 6.0C PASS / 10 schemas.
51. **Active-lane changed-file count:** 0 across `Stage 4A.3/`, `Stage 5D/`, and `Stage 6/`.
52. **Active model trained:** NO.
53. **Challenger trained:** NO.
54. **Model promoted:** NO.
55. **Recommendation logic changed:** NO.
56. **Prospective runtime changed:** NO.
57. **Tags created:** 0.
58. **Remote SHA verification:** performed after push and reported with the final Git delivery result.
59. **Recommended next stage:** obtain written NSE/NSE Indices permission or licence scope for model-training use; only after that gate is satisfied should a separately authorized simple challenger stage begin.

Authority remains `SHADOW_ONLY`. No model training, live trading, broker action,
or recommendation authority is introduced by this work.
