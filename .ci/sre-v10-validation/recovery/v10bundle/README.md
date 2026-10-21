# SRE 0.14.13 — consolidated V10 in-place replay upgrade

This upgrades the exact V9 snapshot exported on 21 October 2026. No installer
is rebuilt. Existing paper portfolios, research databases, configuration,
LIVE_DECISION_V1 rules and portfolio accounting are retained.

## Apply once

Close SRE completely. Extract the ZIP to a normal writable folder and run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\APPLY.ps1
```

The default engine is `%LOCALAPPDATA%\StockRecommendationEngine\native-engine-0.14.13`.
For a different installation, pass `-EngineRoot 'FULL PATH'`. `py -3` must select
the interpreter used by your source-based installed engine.

APPLY verifies existing source and protected-file checksums. It refuses a
mismatch rather than overwriting local edits. Internet is needed once to install
platform-appropriate Polars/PyArrow into private `.replay-v10-deps`; global
NumPy/pandas/Python packages are retained. Exact indicator, PIT, Parquet reuse
and native lock checks run before source mutation. Open SRE normally after success.
No preparatory replay or separate installer is required.

## Rollback

Close SRE and run `powershell -NoProfile -ExecutionPolicy Bypass -File .\ROLLBACK.ps1`.
Rollback restores backed-up source bytes and removes the private V10 dependencies.
It refuses to overwrite later source edits. Portfolio/research/configuration and
existing replay caches/checkpoints are not deleted or rolled back. Disposable
V10 feature files may remain; the original application ignores them.
If APPLY is interrupted, rerun it with SRE closed; its source transaction is
recovered before a new attempt. Do not combine files from different patches.

## Processing and evidence

Canonical indicator formulas remain unchanged. NumPy accelerates the sequential
Supertrend recurrence; Polars supplies exact 126-bar high and strictly prior
20-bar support calculations. Full causal technical frames and typed fundamental
filing/event timelines persist in Arrow/Parquet. Original reporting basis,
original-order ties, scoring, freshness and supplements remain authoritative.
Immutable Parquet score chunks append at session boundaries. A small SQLite
index stores only lookup metadata; feature/score values are in Parquet. Atomic
publication and page checksums reject incomplete/corrupt objects. The score
payload cache is bounded at 64 MiB and chunk cache at 64 chunks; source rows and
numeric frames require additional memory.

Content hashes cover data, code, frozen rules, runtime, market, universe and
sector inputs, including same-size/same-mtime corrections. Score keys include
exact cutoff, price and relevant PIT prefixes. Old scores survive price appends;
changed-stock numeric timelines are rebuilt vectorially, while unrelated stock
histories remain reusable. This is not a constant-time recurrence append algorithm.
An exclusive OS lock prevents concurrent replay writers. Atomic session
checkpoints preserve interrupted recovery and reject incompatible generations.

1M/3M/6M retain 31/93/186-day windows. Added 1W/12M/24M use 7/366/732 days,
intersected with available sessions. Custom sends CUSTOM and both selected dates.
The existing date-only fundamental cutoff remains end-of-day UTC, with its same-day
filing eligibility. Benchmark and VIX inputs are clipped to each stock cutoff,
including when future auxiliary rows exist. No provider download, yfinance
fallback, training, threshold relaxation or broker execution is introduced.
Entry/exit, costs, slippage, whole shares and accounting code remain unchanged.

Opportunities shows completed, current-input, fully replayable historical
research evidence. Stale/incomplete results are excluded from that validated
summary. Evidence does not affect BUYs, ranks, confidence, allocation or live
authority. Existing surviving-universe bias disclosure remains applicable.

## Verification scope

Read TEST_RESULTS.md and PERFORMANCE_REPORT.md. Native Windows backend,
persistence, recovery and guarded source deployment/rollback tests passed on
Python 3.12 and 3.14. The interactive Windows desktop was not manually exercised;
APPLY also performs a native preflight with your selected interpreter.
Real-data audits/performance used Linux Python 3.12 and the supplied 200-stock,
504-session snapshot. Missing historical data remains missing and excluded.
The bundled harnesses expect the original export under `snapshot/installed-engine`
and a candidate tree under `v10work`; user data/databases are not embedded.
