# Free Official Restricted-Window Completion — Delivery Report

## Executive result

The audit implementation passed, but research readiness correctly remains fail-closed. Free official NSE sources produced a complete 497-session market panel, official calendar, NIFTY 50/NIFTY 500 benchmark history, and complete restricted-period execution-cost coverage for 2024-10-01 through 2026-10-01. The candidate period is exactly 24.0 months, but there is **no jointly valid research window** because membership lifecycle pairing, identity, survivorship, point-in-time price normalization, dependent features, and future model-training usage rights are not complete.

The corrected free-vs-paid result is `FREE_OFFICIAL_RECONSTRUCTION_INCOMPLETE`. The blocker count is not used to infer that licensed data is required. No model was trained, promoted, or granted trading authority.

## Required final report

1. **Overall result:** `PASS_AUDIT_FAIL_CLOSED_NOT_RESEARCH_READY`.
2. **Branch:** `nextgen-research-free-window-2024-2026`.
3. **Commit SHA:** recorded after commit in Git history and the final delivery response.
4. **Parent SHA exact:** `f0a45b2da54a687353a9aeab5f4956d15176b70b`.
5. **Decision V1 preserved:** YES; SHA-256 `afba30e325b6924286e0f8e2bcc7edcf2b9f779fb2f4ac966333d29e925a2c3d`.
6. **Decision V2 result:** `FREE_OFFICIAL_RECONSTRUCTION_INCOMPLETE`.
7. **Target restricted window:** 2024-10-01 through 2026-10-01.
8. **Membership reconstruction status:** `PARTIAL_WITH_GAPS`.
9. **Required scheduled cycles found:** all four — March 2025, September 2025, March 2026, September 2026.
10. **Required ad-hoc events found:** 14 classified; 26 total change events are represented in the restricted membership artifact.
11. **Remaining unresolved in-window events:** five lifecycle records: Siemens Energy dummy exit, ABFRL dummy exit, Tata Motors dummy conversion, Vedanta four-dummy conversion, and the partially paired Vedanta Aluminium exit.
12. **Pre-window unresolved events ignored correctly:** YES.
13. **Identity readiness:** `PARTIAL_WITH_GAPS`; 609 non-dummy symbols mapped, zero missing non-dummy symbols, zero ambiguous duplicate identities, five unresolved lifecycle identities.
14. **Historical constituent count:** 620 unique restricted-period symbols and 629 observed historical ISINs.
15. **Historical non-current members retained:** YES; 119 symbols.
16. **Free Bhavcopy source used:** NSE public Capital Market UDiFF Common Bhavcopy Final archive; MCP was not used for the bulk panel.
17. **Market sessions expected:** 497.
18. **Market sessions acquired:** 497.
19. **Missing sessions:** 0.
20. **Securities covered:** 5,820 unique symbols and 5,827 unique ISINs in 1,579,133 market rows; 620 restricted historical symbols.
21. **OHLC coverage:** complete for required constituent EQ/RR rows; zero invalid required constituent rows. The full exchange panel contains 192 invalid T0-series rows, retained and disclosed rather than silently corrected.
22. **Volume coverage:** complete; zero zero-volume/untraded rows under the governed checks.
23. **Turnover coverage:** complete.
24. **Source usage-right classification:** `RESEARCH_ANALYSIS_ALLOWED`; `MODEL_TRAINING_RIGHTS_NOT_ESTABLISHED`.
25. **Benchmark source:** official NSE historical indices API/report route.
26. **Benchmark coverage:** `COMPLETE_VERIFIED`; NIFTY 50 497/497 and NIFTY 500 497/497, with no missing sessions.
27. **Corporate-action coverage:** 90 relevant non-dividend actions classified from the official NSE corporate-actions source; 21 material actions remain fail-closed for normalization.
28. **Price-normalization status:** `PARTIAL_WITH_GAPS`; `PRICE_RETURN_ONLY`, dividends excluded by policy, future-action use prohibited.
29. **Restricted cost status:** `COMPLETE_VERIFIED`, 2024-10-01 through 2026-10-01; brokerage externally configurable.
30. **Minimal feature readiness:** NOT READY. Technical and market/index are `PIT_SAFE`; liquidity is `FULL_LIQUIDITY_AVAILABLE`; momentum and volatility are blocked by incomplete price normalization. Fundamentals and Stage 6 events are optional and do not block.
31. **Survivorship status:** `PARTIAL_WITH_GAPS`; 620 historical symbols, 501 current survivors, 119 non-current members retained, eight unresolved symbols, unknown-share governance metric 19.2308%.
32. **Longest valid free research window:** none jointly valid; candidate evidence window is 2024-10-01 through 2026-10-01.
33. **Duration:** candidate 24.0 continuous months.
34. **Trading-session count:** 497.
35. **Unique securities:** 620 restricted historical symbols; 629 historical ISINs observed. The full panel contains 5,820 symbols and 5,827 ISINs.
36. **V1 readiness preserved:** YES; SHA-256 `70b603aecd427e9947d4fbf4a68b9eb6f32ff2c1151a930049300d343c5ba6b4`.
37. **V2 readiness preserved:** YES; SHA-256 `7ec465cdf4178593d48dc7b89b690b581cd31ce97f06b505c04158da0244b1fb`.
38. **V3 readiness preserved:** YES; SHA-256 `67cf2cafee7d7beab308440f8bc4b9c6d1df85bd8608d9b540074211a600ce74`.
39. **V4 readiness preserved:** YES; SHA-256 `f85e4af7ee5ab832da15a3be1b356c659e5cbe0adac3dfd4b2fc5d36205b7b57`.
40. **V5 status:** `NOT_READY` for profile `FREE_OFFICIAL_RESTRICTED_NIFTY500_PIT`.
41. **V5 failed gates:** constituent reconstruction, features, identity, price adjustment, source usage rights, survivorship.
42. **Free-vs-paid V2 decision:** `FREE_OFFICIAL_RECONSTRUCTION_INCOMPLETE`.
43. **If paid required — exact sole minimum missing dataset:** NOT APPLICABLE; paid data is not yet proven required.
44. **Proof all free routes exhausted:** NOT ESTABLISHED, deliberately. The V2 blocker ledger identifies attempted routes and marks `free_routes_exhausted=false` and `licensed_only_proven=false`.
45. **Files created:** restricted-window Python package; two acquisition scripts; deterministic builder; focused test runner; test evidence; V2 decision; V5 readiness; source, membership, completeness, calendar, panel, benchmark, normalization, cost, feature, identity, survivorship, window, contract, and delivery-report artifacts — all under `NextGen Research/`.
46. **Files modified:** none outside `NextGen Research/`; existing V1–V4 and active-lane files are unchanged.
47. **Raw bulk files committed:** 0. Raw files remain gitignored.
48. **Focused tests:** 128/128 PASS.
49. **Regression results:** free reconstruction 131/131; authoritative data 83/83; readiness V2 22/22; historical evidence 63/63; real data 58/58; NextGen foundation 104/104; Stage 6.8C 170/170; Stage 5D 606/606; Stage 6.0C PASS / 10 schemas.
50. **Active-lane changed-file count:** 0.
51. **Active model trained:** NO.
52. **Challenger trained:** NO.
53. **Model promoted:** NO.
54. **Recommendation logic changed:** NO.
55. **Prospective runtime changed:** NO.
56. **Paid purchase performed:** NO.
57. **Tags created:** 0.
58. **Remote SHA verification:** recorded after push in the final delivery response.
59. **Recommended next stage:** remain fail-closed and complete the remaining free official lifecycle/normalization and explicit training-rights evidence. Do not start simple challenger research until V5 can emit `READY_WITH_RESTRICTED_PERIOD`.

## Governance boundary

- Authority: `SHADOW_ONLY`
- Trading authority: false
- ML authority: none
- Training started: false
- Paid data used or purchased: false
- Bulk MCP use: false
- Active Stage 4A.3 / Stage 5D / Stage 6 changes: zero
- Raw/runtime artifacts committed: zero
- Tag creation: prohibited for this delivery

