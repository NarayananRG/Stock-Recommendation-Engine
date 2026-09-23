# Stage 5D.5 — Live After-Close Paper Runner

- Branch: `stage5d5-live-paper-runner`
- Frozen base: `stage5d4-news-ml-shadow-baseline` (`fe899cfdb382bc8dd97b112a29ac929106b37ef2`)
- Final pushed commit SHA: provided in the handoff (a commit cannot contain its own SHA).
- Schema: `STAGE5D5_SCHEMA_V1`
- Stage 5D.5A hardening: allocator admission binding, safe fill session ordering, partial news quarantine, and full prior-run integrity verification. Final pushed commit SHA is provided in the handoff.
- Stage 5D.5B: post-collection UTC verification and exact immutable Stage 4A.3 input-cache reuse. Final pushed commit SHA is provided in the handoff.
- Stage 5D.5C: exact CSV round-trip reconstruction and holding-data provenance hardening. Final pushed commit SHA is provided in the handoff.
- Stage 5D.5D: explicit FILL/SELL market-session evidence guard. Final pushed commit SHA is provided in the handoff.
- Stage 5D.5E: `MORNING_PAPER_ACTION_SESSION_GUARD` using a versioned, code-pinned official NSE equity calendar before the same-day completed snapshot exists. Final pushed commit SHA is provided in the handoff.

## Operational command

1. Use Python 3.12 with `pip install -r "Stage 5D/live_paper/requirements.txt"`.
2. Copy `Stage 5D/live_paper/config.example.json` to `Stage 5D/live_paper/config.json` and replace the capital placeholder with the operator's actual ceiling. Set `stage4a3_runtime_repo` to the absolute path of the already activated Stage 4A.3 checkout. This is necessary because the prospective activation and snapshots are ignored runtime files, not carried into a new Git worktree. Only `ONE_MONTH` and `THREE_MONTHS` are supported.
3. After a completed NSE session and **not before 15:45 Asia/Kolkata**, run from the repository root:

   `python "Stage 5D/live_paper/run_after_close.py"`

The live runner has no production `--as-of` and no broker API. It will fail on incomplete or misaligned market data, a broken Stage 4A.3 snapshot/protocol, a missing holding observation, a broken session chain, or ledger integrity failure. A news-provider outage is reported as `NEWS_DATA_UNAVAILABLE` and blocks *new* paper admission while position management still completes.

For explicit paper actions, run `python "Stage 5D/live_paper/paper_action.py" pending <recommendation_id>`, or `fill`, `cancel`, `decline`, `sell` with `--qty` and `--price` where required. These record paper events only. The ordinary daily runner never marks pending or executes a buy/sell.

An after-close recommendation can become PENDING, but its fill must be dated strictly after the signal/decision session and recorded before the fill date's Stage 5D.3 after-close management run. A later fill for an already processed session fails with `FILL_SESSION_ALREADY_PROCESSED`, leaving transactions and lifecycle events untouched.

Explicit FILL and SELL actions validate the transaction date inside the production action path. If a same-day Stage 4A.3 snapshot exists, it is the stronger evidence and must fully verify its Signal Date, NIFTY date, market-data date, complete universe coverage, and raw-data hash. A corrupt or inconsistent existing snapshot fails closed and cannot fall back to the calendar. Before that completed-session snapshot exists, the checked-in `NSE_EQUITY_CALENDAR_V1` artifact proves an ordinary scheduled NSE Capital Market session using circular `NSE/CMTR/71775`, `172/2025`; its canonical hash is pinned in code. Weekends, official holidays, unsupported years, missing/tampered artifacts, and unimplemented special sessions fail closed. Validation is local and network-free. PENDING, CANCEL, and DECLINE remain administrative lifecycle actions and do not require an exchange session.

This removes the morning deadlock: a recommendation created on D can be filled or sold on a valid D+1 morning before the D+1 snapshot exists, provided the action precedes that date's Stage 5D.3 management run. The normal after-close runner then captures and verifies completed-session evidence before managing the position. It retains its existing fail-closed snapshot/provenance chain and does not invent intraday OHLC ordering.

Daily order: clock gate → completed session → frozen Stage 4A.3 collection/verification → frozen scanner → ledger holdings and reservations → frozen holding observations → Stage 5D.3 management → Stage 5D.1 allocation and persistence → timestamped news → Stage 5D.4 overlay/ML shadow → admission assessment → immutable run row and JSON/human report.

After collection, the runner derives the exact Stage 4A.3 cache directory from the verified `Snapshot Created UTC`. It requires the frozen universe and NIFTY CSVs to be present and non-empty before rebuilding candidates with the frozen builder. The complete candidate manifest and stable market-data fields must match the immutable snapshot; the reported market provider is the original snapshot provider. A missing/incomplete cache fails closed, never triggers a replacement download. A newly collected snapshot uses a fresh UTC verification clock after the frozen subprocess returns; existing snapshots retain the entry-time verification cutoff.

Candidate reconstruction temporarily injects pandas `float_precision="round_trip"` only for `.csv` reads underneath that exact cache's `raw_market_data` directory. All unrelated reads are unchanged, and `pandas.read_csv` is restored immediately after the frozen builder returns. Open-position observations use the same cache and parser, require exact per-ticker raw-hash equality with the immutable candidate manifest, and compute Close, Supertrend, and SwingLow10 through the frozen Stage 2.1 feature engine. There is no holding-data download fallback.

## Acceptance gates

| Gate | Result | Evidence |
|---|---|---|
| ONE_COMMAND_AFTER_CLOSE | PASS (fixture orchestration) | `run_stage5d5_tests.py` |
| REAL_DETERMINISTIC_SCANNER | PASS (frozen single-session sanity) | 2026-08-28 frozen builder: 19/19 tickers, aligned NIFTY, zero eligible candidates |
| REAL_NEWS_ADAPTER | PASS (one-ticker read-only acquisition and fixture) | TCS.NS: 10 timestamped articles, 0 quarantined; outage guard tested |
| STAGE4A3_LIVE_SHADOW | PASS (adapter integration/fixture) | frozen Stage 5D.4 regression plus Stage 5D.5 outage/ML tests |
| STAGE5D3_POSITION_MANAGEMENT | PASS (fixture) | zero-position session and frozen holding feature path |
| MAX_FIVE_SLOT_ADMISSION_GUARD | PASS | 0+0, 4+1, 5+0, 3+1, duplicate, held, cancellation tests |
| RECOMMENDATION_BUY_LIFECYCLE_GUARD | PASS | `record_recommendation_fill` and overfill tests; no generic linked BUY path |
| ALLOCATOR_ADMISSION_BINDING | PASS | `ACTIONABLE_BUY` and positive quantity required; watch/blocked allocator outcomes rejected |
| SAFE_FILL_SESSION_ORDERING | PASS | same-date and post-management fills rejected; next-session pre-management fill permitted; no rejected-fill transaction/event |
| PARTIAL_NEWS_QUARANTINE_HANDLED | PASS | usable feed remains `AVAILABLE_WITH_QUARANTINE`; malformed article excluded; zero usable evidence/outage blocks admission |
| STAGE5D5_RUN_INTEGRITY | PASS | every prior row payload/hash/typed binding, ordered dates, schema, SQLite and foreign key checks before production continuation |
| POST_SNAPSHOT_CLOCK_VERIFICATION | PASS | newly created snapshot accepted at post-subprocess clock; genuinely future snapshot rejected; existing snapshot cutoff unchanged |
| EXACT_STAGE4A3_INPUT_CACHE_REUSE | PASS | timestamp-derived cache under external activated checkout, all expected CSVs preflighted |
| SECOND_MARKET_REFRESH_PROHIBITED | PASS | complete-cache frozen builder fixture with download patched to hard-fail; missing/empty files fail before builder |
| SNAPSHOT_CANDIDATE_PROVENANCE | PASS | exact candidate manifest, raw/NIFTY/per-ticker hashes, stable original market manifest fields |
| ZERO_CANDIDATE_LIVE_SESSION_SUPPORTED | PASS | frozen zero-candidate cohort reconstruction and daily zero-position report fixture |
| ROUND_TRIP_CSV_RECONSTRUCTION | PASS | pinned precision-sensitive CSV differs under ordinary parsing and exactly reproduces the pre-serialization hash with round-trip parsing; scope/restoration verified |
| EXACT_RAW_HASH_RECONSTRUCTION | PASS | exact raw, NIFTY, per-ticker, Signal-ID and full input hashes retained; no tolerance or bypass |
| HOLDING_SNAPSHOT_CACHE_REUSE | PASS | holding observation sourced from the same verified session cache and frozen Stage 2.1 feature engine |
| HOLDING_MARKET_REFRESH_PROHIBITED | PASS | no fallback download; missing and empty holding cache files fail before network access |
| HOLDING_RAW_HASH_PROVENANCE | PASS | holding dataframe hash must equal immutable manifest per-ticker hash; mismatch and latest-date mismatch fail closed |
| OFFICIAL_NSE_CALENDAR_INTEGRITY | PASS | source identity, source hash, canonical calendar hash and code-pinned expected hash verified |
| MORNING_FILL_BEFORE_SNAPSHOT | PASS | valid D+1 scheduled-session FILL succeeds before same-day snapshot and management |
| MORNING_SELL_BEFORE_SNAPSHOT | PASS | valid scheduled-session linked SELL succeeds without same-day snapshot |
| HOLIDAY_TRANSACTION_REJECTION | PASS | Saturday, Sunday and official weekday holiday FILL/SELL rejected without mutation |
| UNSUPPORTED_CALENDAR_YEAR_FAIL_CLOSED | PASS | no weekday inference for years without a verified artifact |
| CORRUPT_SNAPSHOT_NO_CALENDAR_FALLBACK | PASS | existing malformed snapshot fails before scheduled-calendar handling |
| MARKET_SESSION_VALIDATION_NETWORK_FREE | PASS | socket and yfinance download sentinels remain unused |
| PAPER_ACTION_VALID_MARKET_SESSION | PASS | internal two-level verifier; no caller-supplied self-certified date bypass |
| ML_PRODUCTION_INFLUENCE | NO | frozen overlay; admission ignores ML selection |
| BROKER_EXECUTION | NO | no broker client |
| AUTOMATIC_BUY | NO | ordinary runner does not call `mark_pending` or fill |
| AUTOMATIC_SELL | NO | SELL requires explicit paper-action invocation |
| UI | NO | CLI only |

Tests: Stage 5D.5 **160/160 PASS**; Stage 5D.4 **107/107 PASS**; Stage 5D.3 **130/130 PASS**; Stage 5D.2 **129/129 PASS**; Stage 5D.1 **80/80 PASS**. Frozen tracked changes: **0**. Runtime SQLite, WAL/SHM, profile config, and reports are gitignored.

`production_smoke_status = "PRODUCTION_SMOKE_PASS_2026_09_23"`.

- `REAL_SMOKE_ATTEMPT_1`: Per supplied operational evidence, immutable Stage 4A.3 snapshot `S4A3_20260922_3b84e2cd8198` (zero candidates) was **CAPTURED**; Stage 5D.5 then false-failed `FUTURE_CREATED_SNAPSHOT` because its comparison clock preceded collection.
- `REAL_SMOKE_ATTEMPT_2`: The existing snapshot was verified; an independent market refresh then caused `CANDIDATE_PROVENANCE_MISMATCH`.
- `REAL_SMOKE_ATTEMPT_3`: Stage 5D.5B reused the exact immutable cache with zero network downloads and rebuilt zero candidates, but ordinary pandas CSV float parsing changed the exact per-ticker and aggregate raw hashes. Per supplied read-only diagnostic evidence, `float_precision="round_trip"` reproduced all 20/20 per-ticker hashes, Raw Market Data Hash, Full Input Logical Hash, and Candidate Count exactly. This was a CSV deserialization reproducibility defect, not market-data drift.

Those three attempts exposed and fixed orchestration defects; none was itself a completed production smoke. A later production smoke succeeded as recorded below. The no-key news provider is Yahoo Finance via yfinance; ambiguous/malformed evidence is quarantined or neutral, never silently treated as verified absence of risk.

`REAL_PRODUCTION_SMOKE_2026_09_23 = PASS`, per supplied production evidence:

- Snapshot: `S4A3_20260923_a1a5473b996a`
- Stage 5D.5 run: `S5D5_RUN_942b9d417e1b126e902ecee0`
- Candidate count: `0`
- Stage 5D.3 management: `S5D3_RUN_e39095f3e0511fd9d7d25108`
- Stage 5D.1 allocation: `S5D1_RUN_91679586adea218bc948890c`
- ML production influence: **NO**
- Second independent market refresh: **NO**

This was a real zero-candidate live-paper session. It validated the production runner but did not exercise a real recommendation, PENDING, FILL, or SELL lifecycle. This patch did not replay or alter that runtime evidence and did not rerun the smoke.

Stage 5D.5E does not replay or alter the successful 2026-09-23 production smoke. Morning FILL/SELL no longer require an impossible same-day completed snapshot: the official scheduled-session artifact is used only when the stronger same-day Stage 4A.3 evidence is absent. Special sessions are never guessed.

Stage 5D.5 requires an explicit path to the activated Stage 4A.3 checkout and verifies its frozen protocol identity before collection. The snapshot and its timestamp-derived input cache are resolved there, not assumed to be in the Stage 5D.5 development checkout. The real snapshot/cache cited above were described in the supplied smoke evidence; they were not opened or changed during this patch.

## Audit boundary

No frozen Stage 4A.3, Stage 2.2.2 Final, Stage 2B.1, or frozen Stage 5D semantic source was edited. No tag is requested or created. This stage is paper-only and does not establish ML economic advantage.
