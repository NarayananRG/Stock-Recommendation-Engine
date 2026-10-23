from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .storage import AppDatabase
from .official_cache_guard import guarded


@dataclass(frozen=True)
class Price:
    symbol: str
    close: float
    session_date: str
    label: str = "LATEST OFFICIAL CLOSE"


class OfficialPriceService:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.cache_roots = [
            repo_root / "data" / "normalized" / "nse_official" / "equity_bhavcopy" / "expanded_universe_2026_10_05",
            repo_root / "data" / "normalized" / "nse_official" / "equity_bhavcopy" / "stage4a3_2026_10_05",
        ]
        self._history_cache: dict[tuple[str, int], tuple[float, list[dict[str, Any]]]] = {}

    def _price_file(self, symbol: str) -> Path | None:
        stem = symbol.upper().replace(".NS", "").replace(".BO", "")
        candidates = [f"{stem}.NS.csv", f"{stem}.csv"]
        for root in self.cache_roots:
            for name in candidates:
                path = root / name
                if path.exists():
                    return path
        return None

    @guarded(lambda self, *a, **k: self.cache_roots, invalidate=True)
    def latest_close(self, symbol: str) -> Price | None:
        stem = symbol.upper().replace(".NS", "").replace(".BO", "")
        path = self._price_file(stem)
        return None if path is None else self._read_latest(path, stem)

    @guarded(lambda self, *a, **k: self.cache_roots, invalidate=True)
    def history(self, symbol: str, limit: int = 252) -> list[dict[str, Any]]:
        """Load only one stock's official OHLCV file for read-only charting.

        The chart layer must not call HistoricalTechnicalPredictionAdapter._load_histories(),
        which loads the full universe and made row selection feel sluggish.
        """
        stem = symbol.upper().replace(".NS", "").replace(".BO", "")
        path = self._price_file(stem)
        if path is None:
            return []
        mtime = path.stat().st_mtime
        key = (str(path), int(limit))
        cached = self._history_cache.get(key)
        if cached and cached[0] == mtime:
            return list(cached[1])
        with path.open(newline="", encoding="utf-8") as handle:
            rows = []
            for row in csv.DictReader(handle):
                if not row.get("Date") or not row.get("Close"):
                    continue
                try:
                    rows.append({
                        "date": row["Date"],
                        "open": float(row.get("Open") or row["Close"]),
                        "high": float(row.get("High") or row["Close"]),
                        "low": float(row.get("Low") or row["Close"]),
                        "close": float(row["Close"]),
                        "volume": float(row.get("Volume") or 0.0),
                    })
                except (TypeError, ValueError):
                    continue
        rows.sort(key=lambda r: r["date"])
        if limit > 0:
            rows = rows[-limit:]
        self._history_cache[key] = (mtime, list(rows))
        return rows

    @staticmethod
    def _read_latest(path: Path, symbol: str) -> Price | None:
        with path.open(newline="", encoding="utf-8") as handle:
            rows = [r for r in csv.DictReader(handle) if r.get("Date") and r.get("Close")]
        if not rows:
            return None
        row = sorted(rows, key=lambda r: r["Date"])[-1]
        return Price(symbol=symbol, close=float(row["Close"]), session_date=row["Date"])


class PortfolioService:
    def __init__(self, db: AppDatabase, prices: OfficialPriceService):
        self.db = db
        self.prices = prices

    def list_positions(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM portfolio_positions ORDER BY symbol, id")]

    def add_position(self, symbol: str, quantity: float, buy_price: float, buy_date: str, notes: str = "") -> int:
        with self.db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO portfolio_positions(symbol, quantity, buy_price, buy_date, notes) VALUES (?, ?, ?, ?, ?)",
                (symbol.upper().replace(".NS", ""), quantity, buy_price, buy_date, notes),
            )
            position_id = int(cur.lastrowid)
        self.db.record_event("PORTFOLIO_POSITION_ADDED", {"id": position_id, "symbol": symbol})
        return position_id

    def update_position(self, position_id: int, symbol: str, quantity: float, buy_price: float, buy_date: str, notes: str = "") -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE portfolio_positions
                SET symbol = ?, quantity = ?, buy_price = ?, buy_date = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (symbol.upper().replace(".NS", ""), quantity, buy_price, buy_date, notes, position_id),
            )
        self.db.record_event("PORTFOLIO_POSITION_UPDATED", {"id": position_id, "symbol": symbol})

    def remove_position(self, position_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM portfolio_positions WHERE id = ?", (position_id,))
        self.db.record_event("PORTFOLIO_POSITION_REMOVED", {"id": position_id})

    def calculate_summary(self) -> dict[str, Any]:
        positions = self.list_positions()
        invested = sum(float(p["quantity"]) * float(p["buy_price"]) for p in positions)
        value = 0.0
        priced = 0
        rows = []
        for p in positions:
            price = self.prices.latest_close(str(p["symbol"]))
            current = None if price is None else float(p["quantity"]) * price.close
            if current is not None:
                value += current
                priced += 1
            rows.append({**p, "price": price, "current_value": current})
        pnl = value - invested if priced == len(positions) else None
        return {
            "total_invested": invested,
            "latest_portfolio_value": value if priced == len(positions) else None,
            "total_pnl": pnl,
            "total_pnl_percent": (pnl / invested * 100.0) if pnl is not None and invested else None,
            "holding_count": len(positions),
            "positions": rows,
        }
