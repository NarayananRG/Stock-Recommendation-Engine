from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

root = Path(os.environ["SRE_ENGINE_ROOT"])
sys.path.insert(0, str(root))

from stock_app import technical_v2
from stock_app.fundamental_v3 import point_in_time_leakage_audit
from stock_app.validation_v2 import benchmark_nav_series, technical_snapshot_from_features

# Synthetic OHLCV with deterministic causal history.
dates = pd.bdate_range("2025-01-01", periods=340)
base = 100 + np.linspace(0, 35, len(dates)) + np.sin(np.arange(len(dates))/7)
stock = pd.DataFrame({
    "date": dates,
    "open": base * 0.998,
    "high": base * 1.01,
    "low": base * 0.99,
    "close": base,
    "volume": 1_000_000 + np.arange(len(dates))*100,
})
bench_base = 200 + np.linspace(0, 20, len(dates)) + np.cos(np.arange(len(dates))/11)
bench = pd.DataFrame({
    "date": dates,
    "open": bench_base * 0.999,
    "high": bench_base * 1.005,
    "low": bench_base * 0.995,
    "close": bench_base,
    "volume": 2_000_000 + np.arange(len(dates))*50,
})

full = technical_v2.compute_features(stock, bench)
for pos in (240, 280, 320):
    session = str(dates[pos].date())
    prefix = technical_v2.compute_features(stock.iloc[:pos+1], bench.iloc[:pos+1])
    left = technical_snapshot_from_features(full, session)
    right = technical_snapshot_from_features(prefix, session)
    for path in (
        ("trend","close"),("trend","ema50"),("trend","ema50_slope_5d_pct"),
        ("momentum","roc20_pct"),("momentum","macd_hist"),
        ("volatility","atr_pct"),("volume_flow","cmf20"),
        ("relative_strength","rs20_vs_nifty"),("multi_timeframe","weekly_trend_confirmed"),
        ("market_context","nifty_regime"),
    ):
        a = left[path[0]][path[1]]
        b = right[path[0]][path[1]]
        if isinstance(a, float) and isinstance(b, float):
            assert abs(a-b) < 1e-8, (session, path, a, b)
        else:
            assert a == b, (session, path, a, b)

# Appending future prices must not mutate a historical technical snapshot.
session = str(dates[280].date())
before = technical_snapshot_from_features(
    technical_v2.compute_features(stock.iloc[:281], bench.iloc[:281]), session
)
after = technical_snapshot_from_features(full, session)
assert before == after, (before, after)

# Benchmark must be actual normalized history, never a flat placeholder.
series = benchmark_nav_series(100000, [("D0",100),("D1",105),("D2",110)])
assert series[0]["benchmark_nav"] == 100000
assert series[-1]["benchmark_nav"] == 110000
assert len({x["benchmark_nav"] for x in series}) > 1

# Existing Fundamental V3 PIT audit must reject any filing timestamp after cutoff.
audit = point_in_time_leakage_audit(
    root, "HINDZINC",
    ["2026-04-30", "2026-06-30", "2026-08-31", "2026-10-15"],
    latest_price=500.0,
)
assert audit["status"] == "PASS", audit
for item in audit["selections"]:
    selected = item.get("selected_availability_ts")
    if selected:
        assert str(selected)[:10] <= str(item["decision_timestamp"])[:10], item

print("VALIDATION V2 PIT / ANTI-LOOKAHEAD TESTS PASS")
