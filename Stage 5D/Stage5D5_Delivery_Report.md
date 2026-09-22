# Stage 5D.5 — Live After-Close Paper Runner

- Branch: `stage5d5-live-paper-runner`
- Frozen base: `stage5d4-news-ml-shadow-baseline` (`fe899cfdb382bc8dd97b112a29ac929106b37ef2`)
- Final pushed commit SHA: provided in the handoff (a commit cannot contain its own SHA).
- Schema: `STAGE5D5_SCHEMA_V1`

## Operational command

1. Use Python 3.12 with `pip install -r "Stage 5D/live_paper/requirements.txt"`.
2. Copy `Stage 5D/live_paper/config.example.json` to `Stage 5D/live_paper/config.json` and replace the capital placeholder with the operator's actual ceiling. Set `stage4a3_runtime_repo` to the absolute path of the already activated Stage 4A.3 checkout. This is necessary because the prospective activation and snapshots are ignored runtime files, not carried into a new Git worktree. Only `ONE_MONTH` and `THREE_MONTHS` are supported.
3. After a completed NSE session and **not before 15:45 Asia/Kolkata**, run from the repository root:

   `python "Stage 5D/live_paper/run_after_close.py"`

The live runner has no production `--as-of` and no broker API. It will fail on incomplete or misaligned market data, a broken Stage 4A.3 snapshot/protocol, a missing holding observation, a broken session chain, or ledger integrity failure. A news-provider outage is reported as `NEWS_DATA_UNAVAILABLE` and blocks *new* paper admission while position management still completes.

For explicit paper actions, run `python "Stage 5D/live_paper/paper_action.py" pending <recommendation_id>`, or `fill`, `cancel`, `decline`, `sell` with `--qty` and `--price` where required. These record paper events only. The ordinary daily runner never marks pending or executes a buy/sell.

Daily order: clock gate → completed session → frozen Stage 4A.3 collection/verification → frozen scanner → ledger holdings and reservations → frozen holding observations → Stage 5D.3 management → Stage 5D.1 allocation and persistence → timestamped news → Stage 5D.4 overlay/ML shadow → admission assessment → immutable run row and JSON/human report.

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
| ML_PRODUCTION_INFLUENCE | NO | frozen overlay; admission ignores ML selection |
| BROKER_EXECUTION | NO | no broker client |
| AUTOMATIC_BUY | NO | ordinary runner does not call `mark_pending` or fill |
| AUTOMATIC_SELL | NO | SELL requires explicit paper-action invocation |
| UI | NO | CLI only |

Tests: Stage 5D.5 **69/69 PASS**; Stage 5D.4 **107/107 PASS**; Stage 5D.3 **130/130 PASS**; Stage 5D.2 **129/129 PASS**; Stage 5D.1 **80/80 PASS**. Frozen tracked changes: **0**. Runtime SQLite, WAL/SHM, profile config, and reports are gitignored.

The **production live smoke was not run**: no real capital config was supplied. The default bundled Python lacks some pinned production packages; the read-only TCS.NS news check used an existing local yfinance installation. The first live report remains contingent on installing the pinned requirements, supplying the real config, and a valid after-close session. The no-key provider is Yahoo Finance via yfinance; its news API returns a list, but article availability and relevance can vary. Ambiguous/malformed evidence is quarantined or neutral, never silently treated as a verified absence of risk. See [yfinance's `get_news` implementation](https://github.com/ranaroussi/yfinance/blob/main/yfinance/base.py).

The existing Stage 4A.3 activation record was found in the earlier `work/stage4a` checkout, not in this new worktree. Its activation date is 2026-09-13; no prospective snapshot was found there at this audit. The frozen protocol identity check passed (commit `3ff3c0283174589d43883ce75b1dfd87a33613ce`). The frozen collector will mark intervening eligible sessions **MISSED** when first run and must never backfill them. Stage 5D.5 requires an explicit path to that activated checkout and verifies its protocol identity before collection.

## Audit boundary

No frozen Stage 4A.3, Stage 2.2.2 Final, Stage 2B.1, or frozen Stage 5D semantic source was edited. No tag is requested or created. This stage is paper-only and does not establish ML economic advantage.
