from __future__ import annotations

from stock_app.official_cache_guard import guarded

from collections import Counter

import json
import math
import os
import random
from datetime import date, datetime, timedelta
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from stock_app.config import AppConfig, load_config
from stock_app.engine import OfficialV1Adapter
from stock_app.combined import CombinedDecisionEngine
from stock_app.fundamentals import FundamentalSnapshotService
from stock_app.lifecycle import PositionAssessmentService
from stock_app.allocation import AllocationRequest, PortfolioAllocator, explain_reason_code, is_executable_decision
from stock_app.monitoring import AdvancedMonitoringService
from stock_app.operations import ProductionHardeningService
from stock_app.daily_workflow import DailyWorkflowOrchestrator
from stock_app.glossary import GLOSSARY_TERMS
from stock_app.historical import HistoricalTechnicalPredictionAdapter
from stock_app.portfolio import OfficialPriceService, PortfolioService
from stock_app.storage import AppDatabase
from stock_app.evidence_coverage_v1 import classify_live_decision


APP_VERSION = "0.14.13-paper-trading-repair"


def _pct(new: float | None, old: float | None) -> float | None:
    if new is None or old in (None, 0):
        return None
    return (new / old - 1.0) * 100.0


def _finite(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _preview_bars() -> list[dict[str, Any]]:
    random.seed(85)
    rows: list[dict[str, Any]] = []
    d = date(2023, 1, 2)
    close = 1450.0
    while len(rows) < 760:
        if d.weekday() < 5:
            i = len(rows)
            drift = 0.00025 + 0.0035 * math.sin(i / 34.0)
            ret = random.gauss(drift, 0.0115)
            op = close * (1 + random.gauss(0, 0.003))
            cl = max(50.0, close * (1 + ret))
            hi = max(op, cl) * (1 + abs(random.gauss(0.0042, 0.0024)))
            lo = min(op, cl) * (1 - abs(random.gauss(0.0042, 0.0024)))
            vol = abs(random.gauss(4_600_000, 1_350_000))
            rows.append({"date": d.isoformat(), "open": op, "high": hi, "low": lo, "close": cl, "volume": vol})
            close = cl
        d += timedelta(days=1)
    return rows


def _preview_stock(symbol: str = "INFY") -> dict[str, Any]:
    bars = _preview_bars()
    last, prev = bars[-1], bars[-2]
    close = float(last["close"])
    prediction = {
        "symbol": symbol, "rank": 1, "latest_close": close, "profit_probability": 0.66,
        "target_probability": 0.57, "expected_return": 0.074, "downside_risk": 0.029,
        "confidence_label": "HIGH", "opportunity_status": "BUY CANDIDATE", "sample_size": 160,
        "v1_status": "V1 VALID ZERO / NOT SELECTED", "evidence": {"positive_terminal_outcomes": 106},
    }
    perf = {}
    for name, sessions in [("1W",5),("1M",21),("3M",63),("6M",126),("1Y",252)]:
        perf[name] = _pct(close, float(bars[max(0, len(bars)-1-sessions)]["close"]))
    return {
        "symbol": symbol,
        "preview_data": True,
        "quote": {
            "date": last["date"], "close": close, "change": close-float(prev["close"]),
            "change_pct": _pct(close, float(prev["close"])), "open": last["open"], "high": last["high"],
            "low": last["low"], "volume": last["volume"],
            "high_52w": max(float(x["high"]) for x in bars[-252:]),
            "low_52w": min(float(x["low"]) for x in bars[-252:]),
        },
        "performance": perf, "bars": bars, "prediction": prediction, "recommendation": None,
        "positions": [{"symbol":symbol,"quantity":10,"buy_price":close*0.94,"buy_date":bars[-42]["date"]}],
        "overlays": [
            {"kind":"reference","label":"Model reference","price":close},
            {"kind":"target","label":"Requested target","price":close*1.05},
            {"kind":"risk","label":"Estimated downside","price":close*(1-0.029)},
            {"kind":"entry","label":"Portfolio entry × 10","price":close*0.94,"date":bars[-42]["date"]},
        ],
    }


class OpportunityRunRequest(BaseModel):
    capital: float = Field(gt=0)
    horizon_sessions: int = Field(ge=5, le=126)
    target_return_percent: float | None = Field(default=None, gt=0)


class AllocationPlanRequest(BaseModel):
    deployable_capital: float = Field(gt=0)
    horizon_sessions: int = Field(ge=5, le=126)
    target_return_percent: float | None = Field(default=None, gt=0)


class HoldingRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    quantity: float = Field(gt=0)
    buy_price: float = Field(gt=0)
    buy_date: str = Field(min_length=8, max_length=16)
    notes: str = Field(default="", max_length=1000)


class HoldingUpdateRequest(HoldingRequest):
    id: int = Field(gt=0)


class SellRequest(BaseModel):
    sale_date: str = Field(min_length=8, max_length=16)
    sale_price: float = Field(gt=0)
    quantity_sold: float | None = Field(default=None, gt=0)
    charges: float = Field(default=0.0, ge=0)


class MonitoringRunRequest(BaseModel):
    market_session: str | None = None


class DataSourceRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1000)


class ModernAppContext:
    def __init__(self, repo_root: Path | None = None, app_data_dir: Path | None = None):
        self.config = load_config(repo_root=repo_root, app_data_dir=app_data_dir)
        self.code_root = self.config.repo_root.resolve()
        self.data_source_file = self.config.app_data_dir / "real_data_source.json"
        self.active_analysis_file = self.config.app_data_dir / "active_analysis_run.json"
        self.ui_state_version_file = self.config.app_data_dir / "current_ui_state_version.json"
        self._phase6_run_selected_in_session = False
        self._ensure_current_ui_state_version()
        self.db = AppDatabase(self.config.database_path)
        self.db.initialize()
        self.preview_requested = os.environ.get("STOCK_MODERN_UI_PREVIEW", "0") == "1"
        self.data_repo_root = self._discover_data_repo() or self.code_root
        self._bind_services(self.data_repo_root)
        # Enrol open paper holdings on normal startup. Only our additive evidence
        # registry is written; no trades, orders or historical journals are changed.
        try:
            self._holdings_startup_result = self.paper_holdings_monitoring(update=True)
        except Exception as exc:
            self._holdings_startup_error = type(exc).__name__

    @staticmethod
    def _official_cache_roots(root: Path) -> list[Path]:
        base = root / "data" / "normalized" / "nse_official" / "equity_bhavcopy"
        preferred = [base / "expanded_universe_2026_10_05", base / "stage4a3_2026_10_05"]
        discovered = []
        if base.exists():
            discovered = sorted((p for p in base.iterdir() if p.is_dir() and any(p.glob("*.csv"))), key=lambda p: p.name)
        roots = []
        for item in [*discovered, *preferred]:
            if item not in roots:
                roots.append(item)
        return roots

    @staticmethod
    def _legacy_frozen_cache_roots(root: Path) -> list[Path]:
        candidates = [
            root / "stage2_2_1" / "data" / "frozen",
            root / "Stage 2.2.2 Final" / "stage2_2_1" / "data" / "frozen",
        ]
        return [p for p in candidates if p.exists() and any(p.glob("*.csv"))]

    @classmethod
    def _market_cache_roots(cls, root: Path) -> tuple[list[Path], str, str]:
        official = [p for p in cls._official_cache_roots(root) if p.exists() and any(p.glob("*.csv"))]
        if official:
            return official, "REAL_OFFICIAL_DATA", "OFFICIAL_NSE_OHLCV"
        legacy = cls._legacy_frozen_cache_roots(root)
        if legacy:
            return legacy, "REAL_FROZEN_HISTORY", "LEGACY_FROZEN_OHLCV"
        return [], "NO_REAL_DATA_CONNECTED", "NONE"

    @staticmethod
    def _normalize_data_repo_root(raw_root: Path) -> Path:
        root = raw_root.expanduser().resolve()
        parts = [part.lower() for part in root.parts]
        for idx in range(max(0, len(parts) - 3)):
            if parts[idx:idx + 4] == ["data", "normalized", "nse_official", "equity_bhavcopy"]:
                return Path(*root.parts[:idx]).resolve()
        for idx in range(max(0, len(parts) - 2)):
            if parts[idx:idx + 3] == ["stage2_2_1", "data", "frozen"]:
                return Path(*root.parts[:idx]).resolve()
        return root

    @staticmethod
    def _last_nonempty_line(path: Path, chunk_size: int = 4096) -> str | None:
        try:
            with path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                pos = handle.tell()
                if pos <= 0:
                    return None
                buf = b""
                while pos > 0 and len(buf) < 65536:
                    step = min(chunk_size, pos)
                    pos -= step
                    handle.seek(pos)
                    buf = handle.read(step) + buf
                    lines = [line.strip() for line in buf.splitlines() if line.strip()]
                    if len(lines) >= 2 or pos == 0:
                        if not lines:
                            return None
                        return lines[-1].decode("utf-8", errors="replace")
        except OSError:
            return None
        return None

    @staticmethod
    def _history_file_kind(path: Path) -> str:
        name = path.name.upper()
        stem = path.stem.upper().replace(".NS", "").replace(".BO", "")
        if name.startswith("INDEX_") or stem.startswith("INDEX_") or stem in {"NSEI", "NIFTY", "NIFTY50", "NIFTY_50"}:
            return "INDEX"
        return "EQUITY"

    @staticmethod
    def _phase3_freshness_contract(latest_session: str | None, data_mode: str) -> dict[str, Any]:
        import datetime as _dt

        base = {
            "freshness_status": "UNAVAILABLE",
            "freshness_gate": "FAIL",
            "business_day_lag": None,
            "freshness_reason": "No market session is available.",
            "analysis_data_current": False,
        }
        if not latest_session:
            return base
        try:
            latest = _dt.date.fromisoformat(str(latest_session)[:10])
        except Exception:
            base["freshness_reason"] = "Latest market session is not a valid ISO date."
            return base

        today = _dt.date.today()
        lag = 0
        cursor = latest + _dt.timedelta(days=1)
        while cursor <= today:
            if cursor.weekday() < 5:
                lag += 1
            cursor += _dt.timedelta(days=1)

        base["business_day_lag"] = lag
        if data_mode == "REAL_OFFICIAL_DATA":
            if lag <= 2:
                base.update(
                    freshness_status="CURRENT",
                    freshness_gate="PASS",
                    freshness_reason=f"Official market data is within {lag} business day(s) of today.",
                    analysis_data_current=True,
                )
            else:
                base.update(
                    freshness_status="STALE",
                    freshness_gate="FAIL",
                    freshness_reason=f"Official market data is {lag} business day(s) behind today.",
                    analysis_data_current=False,
                )
        elif data_mode == "REAL_FROZEN_HISTORY":
            base.update(
                freshness_status="STALE_FROZEN",
                freshness_gate="WARN",
                freshness_reason="Frozen historical data is retained for deterministic analysis and is not current market data.",
                analysis_data_current=False,
            )
        else:
            base["freshness_reason"] = "No official current-market data source is connected."
        return base

    @staticmethod
    def _phase3b_official_universe_status(root: Path, equity_files: list[Path]) -> dict[str, Any]:
        from stock_app.official_universe import OfficialUniverseCatalog

        return OfficialUniverseCatalog.inspect(root, equity_files)

    @guarded(lambda self, root: self._market_cache_roots(self._normalize_data_repo_root(root))[0])
    def _inspect_data_repo(self, root: Path) -> dict[str, Any]:
        root = self._normalize_data_repo_root(root)
        roots, data_mode, provenance = self._market_cache_roots(root)
        files: list[Path] = []
        equity_files: list[Path] = []
        index_files: list[Path] = []
        latest = None
        for cache in roots:
            if not cache.exists():
                continue
            try:
                cache_files = list(cache.glob("*.csv"))
            except OSError:
                continue
            files.extend(cache_files)
            equity_files.extend(path for path in cache_files if self._history_file_kind(path) == "EQUITY")
            index_files.extend(path for path in cache_files if self._history_file_kind(path) == "INDEX")
            for path in cache_files:
                line = self._last_nonempty_line(path)
                if not line:
                    continue
                d = line.split(",", 1)[0].strip().strip('"')
                if d and d.lower() not in {"date", "timestamp", "datetime"}:
                    if not latest or d > latest:
                        latest = d
        full_engine_ready = (root / "run_official_v1_daily.py").exists() and (root / "Stage 4A.3").exists()
        fundamental_ready = (root / "data" / "fundamentals").exists()
        age_days = None
        freshness_status = "UNKNOWN"
        if latest:
            try:
                age_days = max(0, (date.today() - datetime.strptime(str(latest)[:10], "%Y-%m-%d").date()).days)
                freshness_status = "CURRENT" if age_days <= 3 else ("AGING" if age_days <= 7 else "STALE")
            except ValueError:
                pass
        return {
            "path": str(root),
            "exists": root.exists(),
            "ohlcv_ready": bool(equity_files),
            "stock_files": len({p.name for p in equity_files}),
            "index_files": len({p.name for p in index_files}),
            "index_file_names": sorted({p.name for p in index_files}),
            "history_files_total": len({p.name for p in files}),
            "latest_session": latest,
            "history_age_days": age_days,
            "freshness_status": freshness_status,
            "full_engine_ready": full_engine_ready,
            "fundamental_ready": fundamental_ready,
            "cache_roots": [str(p) for p in roots if p.exists()],
            "data_mode": data_mode,
            "provenance": provenance,
            **self._phase3_freshness_contract(latest, data_mode),
            **self._phase3b_official_universe_status(root, equity_files),
        }

    def _candidate_data_repos(self) -> list[Path]:
        candidates: list[Path] = []
        env = os.environ.get("STOCK_REAL_DATA_REPO_ROOT")
        if env:
            candidates.append(Path(env))
        if self.data_source_file.exists():
            try:
                saved = json.loads(self.data_source_file.read_text(encoding="utf-8"))
                if saved.get("path"):
                    candidates.append(Path(saved["path"]))
            except Exception:
                pass
        candidates.append(self.code_root)
        home = Path.home()
        for base in [home, home / "Documents", home / "Desktop", home / "Downloads", Path("C:/"), Path("D:/")]:
            candidates.append(base / "Stock-Recommendation-Engine")
            candidates.append(base / "StockRecommendationEngine")
            if base.exists() and base not in {Path("C:/"), Path("D:/")} :
                try:
                    candidates.extend(p for p in base.glob("*Stock*Recommendation*Engine*") if p.is_dir())
                except OSError:
                    pass
        # Keep discovery shallow and deterministic; never crawl the whole disk.
        seen: set[str] = set()
        out = []
        for candidate in candidates:
            try:
                key = str(candidate.expanduser().resolve()).lower()
            except Exception:
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(candidate)
        return out

    def _discover_data_repo(self) -> Path | None:
        for candidate in self._candidate_data_repos():
            try:
                status = self._inspect_data_repo(candidate)
            except Exception:
                continue
            if status["ohlcv_ready"]:
                return Path(status["path"])
        return None

    def _bind_services(self, root: Path) -> None:
        root = root.resolve()
        self.data_repo_root = root
        runtime_config = AppConfig(repo_root=root, app_data_dir=self.config.app_data_dir)
        self.prices = OfficialPriceService(root)
        roots, _, _ = self._market_cache_roots(root)
        if roots:
            self.prices.cache_roots = roots
        self.portfolio = PortfolioService(self.db, self.prices)
        self.v1 = OfficialV1Adapter(root, self.db)
        self.historical = HistoricalTechnicalPredictionAdapter(root, self.db, self.v1)
        if roots:
            self.historical.cache_roots = roots
        self.lifecycle = PositionAssessmentService(self.db, self.prices)
        self.fundamentals = FundamentalSnapshotService(root, self.db)
        self.combined = CombinedDecisionEngine(root, self.historical, self.fundamentals)
        self.allocator = PortfolioAllocator(root, self.portfolio)
        if roots and getattr(self.allocator, "history", None) is not None:
            self.allocator.history.adapter.cache_roots = roots
        self.monitoring = AdvancedMonitoringService(self.db, self.lifecycle, self.portfolio, self.allocator, self.historical, self.fundamentals)
        self.hardening = ProductionHardeningService(runtime_config, self.db)
        self.daily_workflow = DailyWorkflowOrchestrator(self.hardening, self.v1, self.fundamentals, self.monitoring)
        self.real_data_status = self._inspect_data_repo(root)
        self.preview_mode = self.preview_requested and not self.real_data_status["ohlcv_ready"]

    def data_source_status(self) -> dict[str, Any]:
        current = dict(self.real_data_status)
        candidates = []
        if not current["ohlcv_ready"]:
            for root in self._candidate_data_repos():
                try:
                    status = self._inspect_data_repo(root)
                except Exception:
                    continue
                if status["ohlcv_ready"] and status["path"] != current["path"]:
                    candidates.append(status)
                    if len(candidates) >= 3:
                        break
        return {
            "mode": current.get("data_mode") if current["ohlcv_ready"] else ("PREVIEW" if self.preview_mode else "NO_REAL_DATA_CONNECTED"),
            "active": current,
            "code_root": str(self.code_root),
            "saved_config": str(self.data_source_file),
            "candidates": candidates,
            "budget_uses_real_data": bool(current["ohlcv_ready"]),
            "yfinance_automatic_fallback": False,
        }

    def connect_data_repo(self, raw_path: str) -> dict[str, Any]:
        root = self._normalize_data_repo_root(Path(raw_path.strip().strip('"')))
        status = self._inspect_data_repo(root)
        if not status["ohlcv_ready"]:
            raise ValueError("No usable OHLCV history was found under that repository. Expected either data/normalized/nse_official/equity_bhavcopy or stage2_2_1/data/frozen.")
        self.data_source_file.write_text(json.dumps({"path": str(root)}, indent=2), encoding="utf-8")
        self._bind_services(root)
        return self.data_source_status()

    def require_real_data(self) -> None:
        status = self.real_data_status
        if not status["ohlcv_ready"]:
            raise HTTPException(status_code=409, detail="Real market history is not connected. Open System → Real data source and connect your Stock-Recommendation-Engine repository first.")

    def symbols(self) -> list[str]:
        symbols: set[str] = set()
        for root in self.prices.cache_roots:
            if not root.exists():
                continue
            for path in root.glob("*.csv"):
                if self._history_file_kind(path) != "EQUITY":
                    continue
                symbols.add(path.stem.replace(".NS", "").replace(".BO", "").upper())
        with self.db.connect() as conn:
            for table, column in [
                ("portfolio_positions", "symbol"),
                ("prediction_candidates", "symbol"),
                ("recommendation_snapshots", "symbol"),
            ]:
                try:
                    for row in conn.execute(f"SELECT DISTINCT {column} AS symbol FROM {table} WHERE {column} IS NOT NULL"):
                        if row["symbol"]:
                            symbols.add(str(row["symbol"]).replace(".NS", "").upper())
                except Exception:
                    pass
        if not symbols and self.preview_mode:
            symbols.update({"INFY","TCS","RELIANCE","HDFCBANK"})
        return sorted(symbols)

    @staticmethod
    def _targets_match(a: Any, b: Any) -> bool:
        if a is None or b is None:
            return a is None and b is None
        return abs(float(a) - float(b)) <= 1e-9

    def _prediction_run_by_id(self, run_id: str | None) -> dict[str, Any] | None:
        if not run_id:
            return None
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM prediction_runs WHERE run_id=? LIMIT 1", (run_id,)).fetchone()
            if row is None:
                return None
            rows = conn.execute("SELECT * FROM prediction_candidates WHERE run_id=? ORDER BY rank", (run_id,)).fetchall()
        return {"run": dict(row), "candidates": [dict(x) for x in rows]}

    def _saved_active_run_id(self) -> str | None:
        try:
            payload = json.loads(self.active_analysis_file.read_text(encoding="utf-8"))
            return str(payload.get("run_id") or "") or None
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def _ui_state_version_payload(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.ui_state_version_file.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}

    def _ensure_current_ui_state_version(self) -> None:
        payload = self._ui_state_version_payload()
        if payload.get("app_version") == APP_VERSION:
            return
        previous = payload.get("app_version")
        self.config.app_data_dir.mkdir(parents=True, exist_ok=True)
        for path in (
            self.active_analysis_file,
            self.config.app_data_dir / "active_target_state.json",
            self.config.app_data_dir / "active_opportunity_run.json",
            self.config.app_data_dir / "transient_ui_run_state.json",
        ):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
        self.ui_state_version_file.write_text(
            json.dumps(
                {
                    "schema": "SRE_CURRENT_UI_STATE_VERSION_V1",
                    "app_version": APP_VERSION,
                    "previous_app_version": previous,
                    "active_selection_reset": True,
                    "historical_runs_preserved": True,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _active_run_metadata(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.active_analysis_file.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}

    def _set_active_run(
        self,
        run_id: str,
        *,
        target_explicit: bool | None = None,
        target_origin: str | None = None,
        selected_in_session: bool = False,
    ) -> dict[str, Any] | None:
        data = self._prediction_run_by_id(run_id)
        if not data:
            return None
        previous = self._active_run_metadata()
        payload = {"run_id": run_id, "app_version": APP_VERSION, "updated_at": datetime.now().isoformat(timespec="seconds")}
        if previous.get("run_id") == run_id:
            for key in ("target_explicit", "target_origin"):
                if key in previous:
                    payload[key] = previous[key]
        if target_explicit is not None:
            payload["target_explicit"] = bool(target_explicit)
        if target_origin is not None:
            payload["target_origin"] = str(target_origin)
        self.active_analysis_file.parent.mkdir(parents=True, exist_ok=True)
        self.active_analysis_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if selected_in_session:
            self._phase6_run_selected_in_session = True
        return data

    def _live_file(self, run_id: str) -> Path:
        import hashlib
        return self.config.app_data_dir / "live_decision_v1" / (hashlib.sha256((APP_VERSION + ":" + run_id).encode()).hexdigest() + ".json")

    def _persist_position_thesis(self, position_id: int, symbol: str, buy_date: str) -> None:
        active = self.active_prediction_run() or {}
        row = next((r for r in active.get("candidates", []) if r["symbol"] == symbol.upper().replace(".NS", "")), {})
        live = row.get("live_decision")
        if not live or not live.get("executable"):
            return
        try:
            if date.fromisoformat(str(buy_date)) <= date.fromisoformat(str(live["market_session"])):
                return  # Never manufacture a historical entry thesis from later evidence.
        except (ValueError, TypeError):
            return
        with self.db.connect() as con:
            con.execute("create table if not exists live_position_theses (position_id integer primary key, thesis_json text not null)")
            con.execute("insert or ignore into live_position_theses values (?,?)", (position_id, json.dumps(live)))

    def paper_holdings_monitoring(self, update: bool = False) -> dict:
        from stock_app.holdings_monitoring import HoldingsRegistry
        return HoldingsRegistry(self).run(update=update)

    def live_today_summary(self) -> dict:
        from stock_app.holdings_monitoring import REVIEW
        paper = self.paper_holdings_monitoring()
        open_positions = {p["id"]: p for p in self.portfolio.list_positions() if p.get("position_status") != "CLOSED"}
        open_ids = set(open_positions)
        legacy = [{**open_positions.get(a.get("position_id"), {}), **a, "authority": "LEG7_LEGACY", "portfolio_system": "LEG7"}
                  for a in self.monitoring.latest_actions() if a.get("position_id") in open_ids]
        counts = Counter(a["action"] for a in paper["actions"])
        return {**paper, "action_counts": dict(counts),
                "health_counts": {"HEALTHY": counts["HOLD"], "WEAKENING": counts["WEAKENING"],
                                  "REVIEW": counts[REVIEW], "BROKEN / EXIT": counts["EXIT"]},
                "stale_count": paper["coverage"]["blocked"], "qualified_replacements": 0,
                "legacy_actions": legacy, "paper_v2_diagnostics": [],
                "post_close_daily": self.holdings_daily_read_status()}

    def holdings_daily_read_status(self) -> dict:
        # Status GET must never refresh providers, materialize 200 recommendations,
        # recompute allocation/analogues, or trigger a replay.
        state = self._read_daily_state()
        last = state.get("last_successful_run") or {}
        expected = self.expected_market_session()
        session = expected["expected_market_session"]
        latest = self.real_data_status.get("latest_session")
        current = latest == session and last.get("market_session") == session
        previous = state.get("last_result") or {}
        return {**previous, **expected, "target_session": session,
                "latest_available_official_session": latest,
                "active_analysis_session": last.get("analysis_session") or last.get("market_session"),
                "analysis_current": current, "run_status": "READY" if current else "BLOCKED - RUN POST-CLOSE DAILY FLOW",
                "freshness_gate": "PASS" if current else "FAIL", "data_freshness": "READY" if latest == session else "OFFICIAL SESSION UNAVAILABLE",
                "recommendation_count": last.get("recommendation_count", 0),
                "executable_count": last.get("executable_count", 0) if current else 0,
                "signal_eligible_count": previous.get("signal_eligible_count", 0) if current else 0,
                "executable_count_semantics": "FINAL_ALLOCATION_CHECKED_LAST_DAILY_RUN",
                "last_successful_daily_run": last, "automatic_yfinance_fallback": False,
                "status_mode": "LOCAL_READ_ONLY", "refresh_label": "LOCAL STATUS ONLY"}

    def _paper_capital_plan(self, state: dict, run: dict) -> dict:
        from stock_app.allocation import Holding
        active = self.active_prediction_run() or {"candidates": []}
        reserved = sum(float((o.get("allocation") or {}).get("capital") or 0) for o in state.get("pending_orders", []) if o.get("side") == "BUY")
        capital = max(0, float(state["cash"]) - reserved)
        if capital <= 0: return {"new_buys": [], "excluded": []}
        held = [p for p in state.get("positions", []) if p.get("state") != "CLOSED"]
        excluded_symbols = {p["symbol"] for p in held} | {p["symbol"] for p in state.get("pending_orders", [])}
        candidates = self.allocator.candidates_from_latest_run(active)
        candidates = [c for c in candidates if is_executable_decision(c.opportunity_status) and c.symbol not in excluded_symbols]
        holdings = [Holding(p["symbol"], int(p["qty"]), float(p.get("last_price") or p["entry_price"]), self.allocator.sectors.get(p["symbol"], {}).get("sector", "UNKNOWN")) for p in held]
        return self.allocator.allocate(AllocationRequest(capital, int(run.get("horizon_sessions") or 20), None), candidates, holdings)

    def _materialize_live_run(self, data: dict) -> dict:
        from stock_app.live_decision_v1 import route, lane_counts, rank_candidates
        import os
        run = data["run"]
        path = self._live_file(str(run["run_id"]))
        session = str(run["market_session"])
        if path.exists():
            cached = json.loads(path.read_text(encoding="utf-8"))
            cached_run = cached.get("run") or {}
            cached_session = str(cached_run.get("market_session") or "")
            cached_version = str(cached_run.get("model_version") or "")
            if cached_session == session and cached_version == APP_VERSION:
                return cached
            # A cache from an older market session OR older evidence-pipeline
            # release must never survive into the current decision run.
            path.unlink(missing_ok=True)
        gate = self._daily_data_gate()
        current = bool(gate.get("ready") and str(gate.get("target_session")) == session)
        source = self.data_source_status()
        members = [m["symbol"] for m in (source.get("active") or {}).get("members", [])] if source.get("mode") == "REAL_OFFICIAL_DATA" else []
        universe = set(members) if members else set(self.historical._load_histories())
        legacy_rows = {row["symbol"]: row for row in data["candidates"]}
        candidate_rows = [legacy_rows.get(symbol) or {"symbol":symbol, "rank":0, "expected_return":None,
                         "profit_probability":None, "confidence_label":"UNAVAILABLE", "opportunity_status":"LEGACY ANALOGUES UNAVAILABLE",
                         "evidence_json":"{}", "raw_json":"{}"} for symbol in sorted(universe)]
        rows = []
        for row in candidate_rows:
            symbol = str(row["symbol"]).upper().replace(".NS", "")
            bars = [b for b in self.prices.history(symbol, limit=5000) if str(b.get("date"))[:10] <= session]
            technical = self.technical_v2_context(symbol, bars, int(run.get("horizon_sessions") or 20))
            price = _finite(bars[-1].get("close")) if bars else None
            fundamental = self.fundamental_v3_context(symbol, price, session)
            # Every comparison re-evaluates filings at that historical cutoff.
            # Never reuse today's EPS for a past valuation observation.
            from statistics import median
            pe_history = []
            pb_history = []
            for prior in bars[-253:-21:21]:
                past = self.fundamental_v3_context(symbol, _finite(prior.get("close")), str(prior["date"])[:10])
                pe = _finite((past.get("valuation") or {}).get("implied_pe_from_ttm_eps"))
                if past.get("point_in_time_safe") and past.get("filing_freshness") == "CURRENT_FOR_DECISION_TIME" and pe is not None and pe > 0:
                    pe_history.append({"session": prior["date"], "pe": pe, "availability_ts": past.get("effective_availability_ts")})
                pb = _finite((past.get("valuation") or {}).get("implied_pb"))
                if past.get("point_in_time_safe") and past.get("filing_freshness") == "CURRENT_FOR_DECISION_TIME" and pb is not None and pb > 0:
                    pb_history.append({"session": prior["date"], "pb": pb, "availability_ts": past.get("effective_availability_ts")})
            fundamental["valuation"] = {**(fundamental.get("valuation") or {}),
                                       "pit_comparison_available": len(pb_history) >= 4 if fundamental.get("sector_profile") == "FINANCIAL_DOMAIN_CONSERVATIVE" else len(pe_history) >= 4,
                                       "pit_historical_pe_reference": median([p["pe"] for p in pe_history]) if len(pe_history) >= 4 else None,
                                       "pit_historical_pb_reference": median([p["pb"] for p in pb_history]) if len(pb_history) >= 4 else None,
                                       "pit_comparison_observations": pb_history if fundamental.get("sector_profile") == "FINANCIAL_DOMAIN_CONSERVATIVE" else pe_history}
            fundamental.setdefault("feature_coverage", {})["PIT relative valuation reference"] = {
                "status": "AVAILABLE" if fundamental["valuation"]["pit_comparison_available"] else "MISSING",
                "value": fundamental["valuation"]["pit_historical_pb_reference"] if fundamental.get("sector_profile") == "FINANCIAL_DOMAIN_CONSERVATIVE" else fundamental["valuation"]["pit_historical_pe_reference"],
                "observations": len(pb_history) if fundamental.get("sector_profile") == "FINANCIAL_DOMAIN_CONSERVATIVE" else len(pe_history),
            }
            history = bars[-126:]
            highs = [_finite(b.get("high")) for b in history]
            lows = [_finite(b.get("low")) for b in bars[-21:-1]]
            highs = [v for v in highs if v is not None and v > 0]
            lows = [v for v in lows if v is not None and v > 0]
            context = {"drawdown_from_126_high_pct": (price / max(highs) - 1) * 100 if price and highs and len(history) >= 126 else None,
                       "prior_support": min(lows) if len(lows) == 20 else None}
            live = route(symbol, session, technical, fundamental, price_context=context,
                         official_current=current and bool(bars) and str(bars[-1].get("date"))[:10] == session, legacy=dict(row))
            # Diagnostic annotation only. The router has already produced its
            # action and remains byte-for-byte unchanged.
            live["evidence_classification"] = classify_live_decision(live)
            rows.append({**row, "legacy_opportunity_status": row.get("opportunity_status"), "live_decision": live,
                         "opportunity_status": live["final_action"], "confidence_label": live["confidence"],
                         "final_action": live["final_action"], "strategy_style": live["strategy_style"],
                         "latest_close": price, "target_used_in_score": False})
        rows = rank_candidates(rows)
        result = {"run": {**run, "production_authority": "LIVE_DECISION_V1", "model_version": APP_VERSION,
                            "lane_counts": lane_counts([r["live_decision"] for r in rows])}, "candidates": rows}
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation preserves the original decision across duplicate runs.
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            json.dump(result, handle, indent=2)
            temporary = Path(handle.name)
        try:
            os.rename(temporary, path)
        except FileExistsError:
            return json.loads(path.read_text(encoding="utf-8"))
        finally:
            temporary.unlink(missing_ok=True)
        return json.loads(path.read_text(encoding="utf-8"))

    def active_prediction_run(self) -> dict[str, Any] | None:
        meta = self._active_run_metadata()
        if meta.get("app_version") != APP_VERSION:
            return None
        run_id = self._saved_active_run_id()
        if run_id and self._live_file(run_id).exists():
            return json.loads(self._live_file(run_id).read_text(encoding="utf-8"))
        return None

    def active_target_state(self) -> dict[str, Any]:
        active = self.active_prediction_run()
        run = {} if not active else dict(active.get("run") or {})
        raw_target = _finite(run.get("target_return"))
        meta = self._active_run_metadata()
        same_run = bool(run.get("run_id")) and str(meta.get("run_id") or "") == str(run.get("run_id") or "")
        explicit = bool(same_run and meta.get("app_version") == APP_VERSION and meta.get("target_explicit") is True and raw_target is not None)
        legacy_unconfirmed = bool(raw_target is not None and not explicit)
        restored = bool(explicit and not self._phase6_run_selected_in_session)
        if explicit:
            origin = "RESTORED_EXPLICIT_USER_TARGET" if restored else str(meta.get("target_origin") or "USER_SUPPLIED")
        elif legacy_unconfirmed:
            origin = "LEGACY_RESTORED_UNCONFIRMED"
        else:
            origin = "NONE"
        return {
            "explicit": explicit,
            "value": raw_target if explicit else None,
            "raw_persisted_value": raw_target,
            "origin": origin,
            "restored": restored,
            "legacy_unconfirmed": legacy_unconfirmed,
            "display_status": "EXPLICIT_TARGET" if explicit else "NO_TARGET",
        }

    def ui_run_input(self) -> dict[str, Any] | None:
        active = self.active_prediction_run()
        if not active:
            return None
        run = dict(active.get("run") or {})
        state = self.active_target_state()
        if not state["explicit"]:
            run["target_return"] = None
        run["target_explicit"] = state["explicit"]
        run["target_origin"] = state["origin"]
        run["target_restored"] = state["restored"]
        return run

    def _find_matching_run(self, capital: float, horizon: int, target: float | None) -> dict[str, Any] | None:
        market_session = self.real_data_status.get("latest_session")
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM prediction_runs WHERE market_session=? AND horizon_sessions=? ORDER BY id DESC",
                (market_session, int(horizon)),
            ).fetchall()
        for row in rows:
            item = dict(row)
            if abs(float(item.get("capital") or 0.0) - float(capital)) > 0.005:
                continue
            if not self._targets_match(item.get("target_return"), target):
                continue
            if str(item.get("engine_version") or "") != "COMBINED_DECISION_ENGINE_V1":
                continue
            return self._prediction_run_by_id(str(item["run_id"]))
        return None

    def ensure_analysis_run(self, capital: float, horizon: int, target: float | None) -> tuple[dict[str, Any], bool]:
        self.require_real_data()
        match = self._find_matching_run(capital, horizon, target)
        if match:
            self._set_active_run(str(match["run"]["run_id"]), target_explicit=target is not None, target_origin="USER_SUPPLIED" if target is not None else "NONE", selected_in_session=True)
            candidate = self._materialize_live_run(match)
            source_now = self.data_source_status()
            latest_now = (source_now.get("active") or {}).get("latest_session")
            from stock_app.session_consistency import reusable_analysis_session
            if reusable_analysis_session((candidate.get("run") or {}).get("market_session"), latest_now):
                return candidate, True
            # Same capital/horizon/target is not sufficient for reuse when the
            # official market session has advanced. Fall through and create a
            # fresh analysis run for the accepted data session.
        self.fundamentals.refresh_from_cache()
        from stock_app.historical import PredictionRequest
        run = self.combined.run_prediction(PredictionRequest(float(capital), int(horizon), target))
        data = self._prediction_run_by_id(run.run_id)
        if not data:
            raise RuntimeError("Prediction run completed but could not be reloaded from the audit database.")
        self._set_active_run(run.run_id, target_explicit=target is not None, target_origin="USER_SUPPLIED" if target is not None else "NONE", selected_in_session=True)
        return self._materialize_live_run(data), False

    def _execution_preview_for_active_run(self) -> dict[str, dict[str, Any]]:
        active = self.active_prediction_run()
        if not active:
            return {}
        run = active.get("run") or {}
        try:
            request = AllocationRequest(float(run.get("capital") or 0.0), int(run.get("horizon_sessions") or 20), _finite(run.get("target_return")))
            all_inputs = self.allocator.candidates_from_latest_run(active)
            executable_inputs = [row for row in all_inputs if is_executable_decision(row.opportunity_status)]
            preview = self.allocator.execution_preview(request, executable_inputs, self.allocator.holdings_from_portfolio())
            for candidate in all_inputs:
                symbol = candidate.symbol
                price = candidate.latest_close
                if price is None:
                    price, _ = self.allocator.history.latest_close(symbol)
                cash_qty = 0 if price is None or price <= 0 else int(request.deployable_capital // price)
                if symbol not in preview:
                    preview[symbol] = {
                        "cash_affordable": cash_qty > 0,
                        "cash_affordable_qty": cash_qty,
                        "executable": False,
                        "executable_qty": 0,
                        "execution_action": "EXCLUDED",
                        "execution_reason_code": "NON_EXECUTABLE_MODEL_STATUS",
                        "execution_reason": explain_reason_code("NON_EXECUTABLE_MODEL_STATUS"),
                        "single_stock_exception_applied": False,
                    }
                else:
                    preview[symbol]["cash_affordable"] = cash_qty > 0
                    preview[symbol]["cash_affordable_qty"] = cash_qty
            return preview
        except Exception:
            return {}

    def _daily_state_file(self) -> Path:
        return self.config.app_data_dir / "post_close_daily_flow_state.json"

    def _read_daily_state(self) -> dict[str, Any]:
        try:
            payload = json.loads(self._daily_state_file().read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}

    def _write_daily_state(self, payload: dict[str, Any]) -> None:
        self.config.app_data_dir.mkdir(parents=True, exist_ok=True)
        self._daily_state_file().write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def _nse_holidays() -> set[str]:
        from stock_app.exchange_calendar import HOLIDAYS
        return set(HOLIDAYS)

    @classmethod
    def _is_nse_trading_day(cls, day) -> bool:
        from stock_app.exchange_calendar import is_trading_day
        return is_trading_day(day)

    @classmethod
    def _previous_nse_session(cls, day):
        cursor = day
        while True:
            cursor = cursor - timedelta(days=1)
            if cls._is_nse_trading_day(cursor):
                return cursor

    @classmethod
    def expected_market_session(cls, now: datetime | None = None) -> dict[str, Any]:
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("Asia/Kolkata")
        except Exception:
            tz = None
        if now is None:
            override = os.environ.get("SRE_EXPECTED_SESSION_NOW")
            now = datetime.fromisoformat(override) if override else (datetime.now(tz) if tz else datetime.now())
        if tz:
            now = now.replace(tzinfo=tz) if now.tzinfo is None else now.astimezone(tz)
        today = now.date()
        publication_ready = (now.hour, now.minute) >= (18, 0)
        if cls._is_nse_trading_day(today) and publication_ready:
            expected = today
            basis = "TRADING_DAY_AFTER_OFFICIAL_PUBLICATION_WINDOW"
        elif cls._is_nse_trading_day(today):
            expected = cls._previous_nse_session(today)
            basis = "TRADING_DAY_BEFORE_OFFICIAL_PUBLICATION_WINDOW"
        else:
            expected = cls._previous_nse_session(today)
            basis = "NON_TRADING_DAY_PREVIOUS_COMPLETED_SESSION"
        return {
            "current_calendar_date": today.isoformat(),
            "expected_market_session": expected.isoformat(),
            "basis": basis,
            "market_close_time": "15:30:00+05:30",
            "official_publication_window": "18:00:00+05:30",
            "calendar": "NSE_OFFICIAL_HOLIDAY_TABLE_2026_V2",
        }

    def _refresh_official_first_market_data(self) -> dict[str, Any]:
        expected = self.expected_market_session()["expected_market_session"]
        try:
            before = self.data_source_status()
            active_before = dict(before.get("active") or {})
            if before.get("mode") == "REAL_OFFICIAL_DATA" and active_before.get("latest_session") == expected:
                return {
                    "status": "PASS",
                    "refresh_result": {
                        "expected_session": expected,
                        "status": "ALREADY_CURRENT",
                        "stage": "precheck",
                        "source": "LOCAL_OFFICIAL_CACHE",
                        "source_url_or_provider": None,
                        "http_status": None,
                        "reason_code": "LOCAL_OFFICIAL_CACHE_CURRENT",
                        "reason_detail": f"Local official cache already contains {expected}",
                        "equity_session": expected,
                        "index_session": expected,
                        "stock_files_expected": None,
                        "stock_files_matched": None,
                        "stock_coverage": active_before.get("history_coverage"),
                        "persisted": True,
                        "verified_latest_session": expected,
                        "automatic_yfinance_fallback": False,
                    },
                    "source": before,
                    "automatic_yfinance_fallback": False,
                }
            from stock_app.official_daily_refresh import refresh_official_session
            refresh = refresh_official_session(list(active_before.get("cache_roots") or []), expected)
            if refresh.get("status") == "REFRESHED_AND_VERIFIED":
                for attr in ("_cache", "cache", "_history_cache", "_data_cache"):
                    value = getattr(self.prices, attr, None)
                    if isinstance(value, dict):
                        value.clear()
            source = self.data_source_status()
            latest = (source.get("active") or {}).get("latest_session")
            verified_latest = refresh.get("verified_latest_session")
            verified_contract = (
                refresh.get("status") == "REFRESHED_AND_VERIFIED"
                and verified_latest == expected
                and bool(refresh.get("persisted"))
            )
            if verified_contract:
                active_now = dict(source.get("active") or {})
                active_now["latest_session"] = expected
                source = {**source, "active": active_now}
                latest = expected
                status = "PASS"
            elif source.get("mode") == "REAL_OFFICIAL_DATA" and latest == expected:
                status = "PASS"
            elif refresh.get("status") == "OFFICIAL_NOT_READY":
                status = "NOT_READY"
            else:
                status = "ERROR"
            if status == "PASS" and refresh.get("status") != "REFRESHED_AND_VERIFIED":
                refresh = {**refresh, "status": "LOCAL_VERIFICATION_FAILED", "reason_code": "REFRESH_VERIFICATION_CONTRACT_MISMATCH", "reason_detail": "PASS requires REFRESHED_AND_VERIFIED or ALREADY_CURRENT"}
                status = "ERROR"
            return {
                "status": status,
                "refresh_result": refresh,
                "source": source,
                "automatic_yfinance_fallback": False,
            }
        except Exception as exc:
            source = self.data_source_status()
            return {
                "status": "ERROR",
                "error": str(exc),
                "refresh_result": {
                    "expected_session": expected,
                    "status": "OFFICIAL_DOWNLOAD_FAILED",
                    "stage": "exception",
                    "source": "NSE_OFFICIAL",
                    "reason_code": type(exc).__name__,
                    "reason_detail": str(exc),
                    "automatic_yfinance_fallback": False,
                },
                "source": source,
                "automatic_yfinance_fallback": False,
            }

    def _daily_data_gate(self) -> dict[str, Any]:
        expected = self.expected_market_session()
        refresh = self._refresh_official_first_market_data()
        source = refresh.get("source") or self.data_source_status()
        active = dict(source.get("active") or {})
        latest = active.get("latest_session")
        result = dict(refresh.get("refresh_result") or {})
        result_status = str(result.get("status") or "").upper()
        ready = bool(
            source.get("mode") == "REAL_OFFICIAL_DATA"
            and latest == expected["expected_market_session"]
            and refresh.get("status") == "PASS"
        )
        if ready:
            freshness = "READY"
            blocked = None
        elif result_status == "OFFICIAL_NOT_READY":
            freshness = "NOT YET PUBLISHED"
            blocked = "OFFICIAL_NOT_YET_PUBLISHED"
        elif result_status in {"OFFICIAL_DOWNLOAD_FAILED", "OFFICIAL_INDEX_FAILED"}:
            freshness = "DOWNLOAD ERROR"
            blocked = "OFFICIAL_DOWNLOAD_ERROR"
        elif result_status == "OFFICIAL_SCHEMA_ERROR":
            freshness = "PARSE ERROR"
            blocked = "OFFICIAL_PARSE_ERROR"
        elif result_status == "OFFICIAL_COVERAGE_FAILED":
            freshness = "COVERAGE ERROR"
            blocked = "OFFICIAL_COVERAGE_ERROR"
        elif result_status in {"LOCAL_VERIFICATION_FAILED", "LOCAL_PERSISTENCE_FAILED"}:
            freshness = "LOCAL VERIFICATION ERROR"
            blocked = "LOCAL_VERIFICATION_ERROR"
        else:
            freshness = "DOWNLOAD ERROR" if refresh.get("status") == "ERROR" else "NOT YET PUBLISHED"
            blocked = "OFFICIAL_SOURCE_ERROR" if refresh.get("status") == "ERROR" else "OFFICIAL_NOT_YET_PUBLISHED"
        detail = refresh.get("error") or result.get("reason_detail") or result.get("reason_code") or "No official refresh detail was returned"
        return {
            "source": source,
            **expected,
            "target_session": expected["expected_market_session"],
            "latest_official_session": latest,
            "data_freshness": freshness,
            "freshness_gate": "PASS" if ready else "BLOCKED",
            "official_mode": source.get("mode") == "REAL_OFFICIAL_DATA",
            "analysis_data_current": ready,
            "universe_coverage": active.get("history_coverage"),
            "identity_coverage": active.get("identity_coverage"),
            "ready": ready,
            "blocked_reason": blocked,
            "refresh_error_detail": detail,
            "refresh_status": refresh,
        }

    def _analysis_session_state(self, gate: dict[str, Any] | None = None) -> dict[str, Any]:
        from stock_app.session_consistency import analysis_session_state
        gate = gate or self._daily_data_gate()
        active = self.active_prediction_run() or {}
        run = dict(active.get("run") or {})
        state = analysis_session_state(
            data_ready=bool(gate.get("ready")),
            target_session=gate.get("target_session"),
            analysis_session=run.get("market_session"),
        )
        return {
            **state,
            "active_run_id": run.get("run_id"),
            "active_model_version": run.get("model_version"),
            "candidate_count": len(active.get("candidates") or []),
        }

    def post_close_daily_status(self) -> dict[str, Any]:
        gate = self._daily_data_gate()
        session_state = self._analysis_session_state(gate)
        state = self._read_daily_state()
        latest_success = state.get("last_successful_run")
        active = self.active_prediction_run() or {}
        rows = list(active.get("candidates") or [])

        refresh_result = ((gate.get("refresh_status") or {}).get("refresh_result") or {})
        refresh_status = str(refresh_result.get("status") or "")
        if refresh_status == "REFRESHED_AND_VERIFIED":
            refresh_label = "REFRESHED & VERIFIED"
        elif refresh_status == "ALREADY_CURRENT":
            refresh_label = "ALREADY CURRENT"
        elif refresh_status == "OFFICIAL_NOT_READY":
            refresh_label = "NOT YET PUBLISHED"
        elif refresh_status in {"OFFICIAL_DOWNLOAD_FAILED", "OFFICIAL_INDEX_FAILED"}:
            refresh_label = "DOWNLOAD ERROR"
        elif refresh_status == "OFFICIAL_SCHEMA_ERROR":
            refresh_label = "PARSE ERROR"
        elif refresh_status == "OFFICIAL_COVERAGE_FAILED":
            refresh_label = "COVERAGE ERROR"
        elif refresh_status in {"LOCAL_VERIFICATION_FAILED", "LOCAL_PERSISTENCE_FAILED"}:
            refresh_label = "LOCAL VERIFICATION ERROR"
        elif refresh_status:
            refresh_label = "FAILED"
        elif gate.get("ready"):
            refresh_label = "ALREADY CURRENT"
        else:
            refresh_label = "UNKNOWN"

        source_detail = refresh_result.get("reason_detail") or gate.get("refresh_error_detail")
        if refresh_status in {"REFRESHED_AND_VERIFIED", "ALREADY_CURRENT"} or (gate.get("ready") and not source_detail):
            source_detail = f"NSE OFFICIAL - {refresh_result.get('verified_latest_session') or gate.get('latest_official_session') or gate.get('target_session')}"
        if not source_detail:
            source_detail = "No official refresh detail was returned"

        if not gate.get("ready"):
            run_status = f"BLOCKED - {gate.get('data_freshness') or 'OFFICIAL DATA NOT READY'}"
        elif not session_state.get("analysis_current"):
            run_status = "ANALYSIS REFRESH REQUIRED"
        else:
            run_status = "READY"

        # Signal eligibility is distinct from final trade executability.
        signal_eligible = sum(
            1 for row in rows
            if (row.get("live_decision") or {}).get("executable") is True
        ) if session_state.get("analysis_current") else 0
        executable = sum(
            1 for row in self.latest_prediction_rows(limit=200)
            if row.get("executable") is True
        ) if session_state.get("analysis_current") else 0

        return {
            "schema": "SRE_POST_CLOSE_DAILY_FLOW_STATUS_V3",
            "authority": "LIVE_DECISION_V1",
            "current_calendar_date": gate.get("current_calendar_date"),
            "expected_market_session": gate.get("expected_market_session"),
            "target_session": gate.get("target_session"),
            "latest_available_official_session": gate.get("latest_official_session"),
            "active_analysis_session": session_state.get("analysis_session"),
            "analysis_current": session_state.get("analysis_current"),
            "analysis_status": session_state.get("status"),
            "analysis_action": None if session_state.get("analysis_current") else "RUN_POST_CLOSE_DAILY_FLOW",
            "data_freshness": gate.get("data_freshness"),
            "freshness_gate": gate.get("freshness_gate"),
            "universe_coverage": gate.get("universe_coverage"),
            "identity_coverage": gate.get("identity_coverage"),
            "run_status": run_status,
            "recommendation_count": len(rows),
            "recommendation_scope": "ACTIVE_LIVE_UNIVERSE",
            "recommendation_session": session_state.get("analysis_session"),
            "executable_count": executable,
            "signal_eligible_count": signal_eligible,
            "executable_count_semantics": "FINAL_ALLOCATION_CHECKED",
            "shadow_analysis_status": "Technical V2 and Fundamental V3: LIVE_EVIDENCE; Combined V2: DIAGNOSTIC_ONLY",
            "validation_snapshot_status": "SUPPORTED_WHEN_MONITORING_ROWS_EXIST",
            "last_successful_daily_run": latest_success,
            "last_result": state.get("last_result"),
            "refresh_label": refresh_label,
            "source_detail": source_detail,
            "refresh_error_detail": gate.get("refresh_error_detail"),
            "refresh_status": gate.get("refresh_status"),
            "no_yfinance": True,
            "automatic_yfinance_fallback": False,
        }

    def run_post_close_daily_flow(self, *, force: bool = False) -> dict[str, Any]:
        gate = self._daily_data_gate()
        previous = self._read_daily_state()
        prior_success = previous.get("last_successful_run") or {}
        prior_session_state = self._analysis_session_state(gate)

        if not gate["ready"]:
            result = {
                **self.post_close_daily_status(),
                "ok": False,
                "run_status": f"BLOCKED - {gate.get('data_freshness') or 'OFFICIAL DATA NOT READY'}",
                "blocked_reason": gate.get("blocked_reason"),
            }
            self._write_daily_state({"last_result": result, "last_successful_run": prior_success})
            return result

        # Duplicate protection is valid only when the ACTIVE analysis itself is
        # current. A successful refresh record must never hide a stale run.
        if (
            prior_success.get("market_session") == gate["target_session"]
            and prior_success.get("model_version") == APP_VERSION
            and prior_session_state.get("analysis_current")
            and not force
        ):
            result = {**self.post_close_daily_status(), "ok": True, "run_status": "DUPLICATE_PROTECTED", "duplicate": True}
            try:
                paper_status = self.phase81_paper_status()
                if paper_status.get("active"):
                    result["paper_portfolio_observation"] = self.phase81_record_today()
            except Exception as exc:
                result["paper_portfolio_observation"] = {"status": "ERROR", "reason": str(exc)}
            return result

        target_state = self.active_target_state()
        target = target_state.get("value") if target_state.get("explicit") else None
        active, reused = self.ensure_analysis_run(100000.0, 20, target)
        active_run = dict((active or {}).get("run") or {})
        active_session = str(active_run.get("market_session") or "")
        target_session = str(gate.get("target_session") or "")

        if active_session != target_session:
            result = {
                **self.post_close_daily_status(),
                "ok": False,
                "run_status": "BLOCKED - ANALYSIS SESSION STALE",
                "blocked_reason": "ANALYSIS_SESSION_MISMATCH",
                "expected_analysis_session": target_session,
                "actual_analysis_session": active_session or None,
            }
            self._write_daily_state({"last_result": result, "last_successful_run": prior_success})
            return result

        rows = self.latest_prediction_rows(limit=200)
        run = self.ui_run_input() or active_run
        sample_symbols = [str(x.get("symbol") or "") for x in rows[:5]]
        shadow_status = {"technical_v2": "NOT_RUN", "fundamental_v3": "NOT_RUN", "combined_v2": "NOT_RUN"}
        for symbol in sample_symbols:
            try:
                bars = self.prices.history(symbol, limit=5000)
                latest_price = _finite(bars[-1].get("close")) if bars else None
                pred = next((row for row in rows if str(row.get("symbol") or "") == symbol), None)
                self.technical_v2_context(symbol, bars)
                self.fundamental_v3_context(symbol, latest_price, gate["target_session"])
                self.combined_v2_context(symbol, pred, bars, latest_price)
                shadow_status = {"technical_v2": "PASS", "fundamental_v3": "PASS_OR_EXPLICITLY_UNAVAILABLE", "combined_v2": "PASS"}
                break
            except Exception:
                continue

        try:
            self.monitoring.run_daily_monitoring(gate["target_session"])
            validation_status = "CAPTURED"
        except Exception:
            validation_status = "PARTIAL"

        success = {
            "run_id": run.get("run_id"),
            "market_session": target_session,
            "analysis_session": active_session,
            "run_timestamp": datetime.now().isoformat(timespec="seconds"),
            "model_version": APP_VERSION,
            "recommendation_count": len(rows),
            "executable_count": len([x for x in rows if x.get("executable")]),
            "reused_run": reused,
            "provenance": {
                "official_first": True,
                "automatic_yfinance_fallback": False,
                "data_mode": gate["source"].get("mode"),
                "latest_official_session": gate["latest_official_session"],
            },
            "shadow_analysis_status": shadow_status,
            "validation_snapshot_status": validation_status,
        }
        self._write_daily_state({"last_successful_run": success, "last_result": {"run_status": "SUCCESS", "market_session": target_session}})

        result = {**self.post_close_daily_status(), "ok": True, "run_status": "SUCCESS", "duplicate": False, "last_successful_daily_run": success}
        try:
            paper_status = self.phase81_paper_status()
            if paper_status.get("active"):
                result["paper_portfolio_observation"] = self.phase81_record_today()
        except Exception as exc:
            result["paper_portfolio_observation"] = {"status": "ERROR", "reason": str(exc)}

        self._write_daily_state({"last_successful_run": success, "last_result": result})
        return result

    def _phase81_db_path(self) -> Path:
        return self.config.app_data_dir / "phase81_validation.sqlite3"

    def phase81_authority_trace(self) -> dict[str, Any]:
        from stock_app.phase81_validation import AUTHORITY
        return {**AUTHORITY, "backend_version": APP_VERSION, "validation_version": "V2", "production_rank_authority_changed": False, "production_action_authority_changed": False}

    def _phase81_available_sessions(self) -> list[str]:
        """Use actual accepted index trading sessions, not dates in filenames."""
        # Historical research reads accepted local files; live refresh remains
        # exclusively in the existing daily-data workflow.
        latest = self.expected_market_session()["expected_market_session"]

        bars = self._validation_v2_index_bars()
        sessions = set()
        for bar in bars:
            session = str(bar.get("date") or "")[:10]
            if len(session) == 10 and session[4:5] == "-" and session[7:8] == "-" and session[:4].isdigit() and session[5:7].isdigit() and session[8:10].isdigit() and session <= latest:
                if _finite(bar.get("close")) is not None:
                    sessions.add(session)
        return sorted(sessions)

    def _validation_router_sha(self) -> str:
        import hashlib
        return hashlib.sha256((self.code_root / "stock_app" / "live_decision_v1.py").read_bytes()).hexdigest()

    def _validation_v2_index_bars(self) -> list[dict[str, Any]]:
        for symbol in ("INDEX_NSEI", "NSEI", "^NSEI", "NIFTY"):
            try:
                bars = self.prices.history(symbol, limit=5000)
            except Exception:
                bars = []
            if bars:
                return bars
        return []

    def _validation_pit_session(self, session: str, state: dict[str, Any], assumptions, replay_cache=None) -> dict[str, Any]:
        from statistics import median
        from stock_app.allocation import AllocationRequest, Holding
        from stock_app.live_decision_v1 import BUY_ACTIONS, monitor, rank_candidates, route
        from stock_app.validation_v2 import pit_price_bars

        def history(symbol, limit=5000):
            return (replay_cache.history(symbol, limit, self.prices.history) if replay_cache is not None
                    else self.prices.history(symbol, limit=limit))

        def pit_bars(symbol, cutoff, limit=5000):
            if replay_cache is not None:
                return replay_cache.pit_history(symbol, cutoff, limit, self.prices.history)
            return pit_price_bars(self.prices.history(symbol, limit=limit), cutoff)

        def fundamental_for(symbol, price, cutoff):
            return (replay_cache.fundamental(symbol, price, cutoff, self.fundamental_v3_context)
                    if replay_cache is not None else self.fundamental_v3_context(symbol, price, cutoff))

        # V9: historical valuation-only path. LIVE_DECISION_V1 and current-day
        # fundamentals still use the full authoritative analyzer above.
        from stock_app.replay_fast_valuation_v9 import historical_valuation
        def valuation_for(symbol, price, cutoff):
            if replay_cache is not None and hasattr(replay_cache, "valuation"):
                def reference(sym, px, date):
                    primary = historical_valuation(self.data_repo_root, sym, date, px)
                    if not primary.get("available") and self.code_root.resolve() != self.data_repo_root.resolve():
                        fallback = historical_valuation(self.code_root, sym, date, px)
                        if fallback.get("available"):
                            return fallback
                    return primary
                return replay_cache.valuation(symbol, price, cutoff, reference)
            primary = historical_valuation(self.data_repo_root, symbol, cutoff, price)
            if (not primary.get("available") and
                    self.code_root.resolve() != self.data_repo_root.resolve()):
                fallback = historical_valuation(self.code_root, symbol, cutoff, price)
                if fallback.get("available"):
                    return fallback
            return primary

        source = self.data_source_status()
        members = [str(x["symbol"]).upper().replace(".NS", "") for x in (source.get("active") or {}).get("members", [])]
        universe = sorted(set(members or self.historical._load_histories()))
        universe_status = "CURRENT_UNIVERSE_SURVIVORSHIP_BIAS"
        index_bars = []
        for index_symbol in ("INDEX_NSEI", "NSEI", "^NSEI", "NIFTY"):
            index_bars = pit_bars(index_symbol, session)
            if index_bars:
                break
        index_bar = index_bars[-1] if index_bars and str(index_bars[-1].get("date"))[:10] == session else None
        benchmark_close = _finite(index_bar.get("close")) if index_bar else None
        rows = []
        exact_market = unsafe_fundamental = safe_fundamental = valuation_ready = 0
        for symbol in universe:
            bars = pit_bars(symbol, session)
            exact = bool(bars and str(bars[-1].get("date"))[:10] == session)
            if exact:
                exact_market += 1
            price = _finite(bars[-1].get("close")) if exact else None
            technical = self.technical_v2_context(symbol, bars, 20, replay_cache=replay_cache)
            fundamental = fundamental_for(symbol, price, session)
            if fundamental.get("available") and not fundamental.get("point_in_time_safe"):
                unsafe_fundamental += 1
                continue
            if fundamental.get("point_in_time_safe"):
                safe_fundamental += 1
            pe_history, pb_history = [], []
            valuation_canary_checked = False
            for prior in bars[-253:-21:21]:
                prior_session = str(prior.get("date"))[:10]
                prior_price = _finite(prior.get("close"))
                past = valuation_for(symbol, prior_price, prior_session)
                if not valuation_canary_checked:
                    # One full PIT valuation per symbol guards against accidental
                    # parity regressions. Stop replay rather than silently alter decisions.
                    reference = fundamental_for(symbol, prior_price, prior_session)
                    if (reference.get("available") != past.get("available") or
                            reference.get("point_in_time_safe") != past.get("point_in_time_safe") or
                            any(_finite((reference.get("valuation") or {}).get(f)) !=
                                    _finite((past.get("valuation") or {}).get(f))
                                for f in ("implied_pe_from_ttm_eps", "implied_pb"))):
                        raise RuntimeError("V9_HISTORICAL_VALUATION_PARITY_FAILURE:" + str(symbol))
                    valuation_canary_checked = True
                if not past.get("point_in_time_safe"):
                    continue
                pe = _finite((past.get("valuation") or {}).get("implied_pe_from_ttm_eps"))
                pb = _finite((past.get("valuation") or {}).get("implied_pb"))
                if pe is not None and pe > 0:
                    pe_history.append({"session": prior_session, "pe": pe})
                if pb is not None and pb > 0:
                    pb_history.append({"session": prior_session, "pb": pb})
            financial = fundamental.get("sector_profile") == "FINANCIAL_DOMAIN_CONSERVATIVE"
            observations = pb_history if financial else pe_history
            comparison = median([x["pb" if financial else "pe"] for x in observations]) if len(observations) >= 4 else None
            valuation = dict(fundamental.get("valuation") or {})
            valuation.update(
                pit_comparison_available=comparison is not None,
                pit_historical_pe_reference=None if financial else comparison,
                pit_historical_pb_reference=comparison if financial else None,
                pit_comparison_observations=observations,
            )
            fundamental["valuation"] = valuation
            if comparison is not None:
                valuation_ready += 1
            fast_context = (replay_cache.rolling_price_context(symbol, session, limit=5000,
                            provider=self.prices.history, finite=_finite)
                            if replay_cache is not None else None)
            if fast_context is not None:
                high_126, support_20, enough_history = fast_context
                context = {
                    "drawdown_from_126_high_pct": (price / high_126 - 1) * 100 if price and enough_history and high_126 is not None else None,
                    "prior_support": support_20,
                }
            else:
                recent_bars = bars[-126:]
                highs = [x for x in (_finite(b.get("high")) for b in recent_bars) if x is not None and x > 0]
                lows = [x for x in (_finite(b.get("low")) for b in bars[-21:-1]) if x is not None and x > 0]
                context = {
                    "drawdown_from_126_high_pct": (price / max(highs) - 1) * 100 if price and len(recent_bars) >= 126 and highs else None,
                    "prior_support": min(lows) if len(lows) == 20 else None,
                }
            live = route(symbol, session, technical, fundamental, price_context=context, official_current=exact, legacy={"symbol": symbol})
            row = {
                "symbol": symbol, "market_session": session, "latest_close": price,
                "live_decision": live, "final_action": live["final_action"],
                "opportunity_status": live["final_action"], "confidence_label": live["confidence"],
                "strategy_style": live["strategy_style"], "executable": live["executable"],
            }
            held = state.get("positions", {}).get(symbol)
            if held:
                monitor_state, reason = monitor({**held, "sessions_held": 0}, live)
                row["monitoring_action"] = "EXIT SIGNAL" if "EXIT" in monitor_state else ("WEAKENING" if "WEAK" in monitor_state else "HOLD")
                row["monitoring_reason"] = reason
            rows.append(row)
        rows = rank_candidates(rows)
        market_ratio = exact_market / len(universe) if universe else 0.0
        market_status = "PASS" if benchmark_close is not None and market_ratio >= 0.95 else "INCOMPLETE"
        fundamental_status = "UNSAFE_FUTURE_EVIDENCE" if unsafe_fundamental else ("PASS" if safe_fundamental else "MISSING")
        valuation_status = "PASS" if valuation_ready else "MISSING_OPTIONAL"
        if market_status != "PASS" or unsafe_fundamental or not safe_fundamental:
            replayability = "NOT_REPLAYABLE"
        elif valuation_status == "PASS" and safe_fundamental == len(rows):
            replayability = "FULL_PIT_VALID"
        else:
            replayability = "PIT_VALID_WITH_OPTIONAL_GAPS"
        closes = {r["symbol"]: r["latest_close"] for r in rows if r.get("latest_close") is not None}
        opens = {}
        for symbol in set(closes) | {x.get("symbol") for x in state.get("pending", [])}:
            bars = pit_bars(symbol, session)
            if bars and str(bars[-1].get("date"))[:10] == session and _finite(bars[-1].get("open")) is not None:
                opens[symbol] = float(bars[-1]["open"])
        held_symbols = set(state.get("positions", {}))
        pending_symbols = {x.get("symbol") for x in state.get("pending", [])}
        reserved = sum(float(x.get("capital") or 0) for x in state.get("pending", []) if x.get("side") == "BUY")
        candidates = self.allocator.candidates_from_latest_run({"candidates": rows})
        candidates = [x for x in candidates if x.opportunity_status in BUY_ACTIONS and x.symbol not in held_symbols | pending_symbols]
        holdings = [Holding(symbol, int(p["qty"]), float(p.get("last_price") or p["entry_price"]), self.allocator.sectors.get(symbol, {}).get("sector", "UNKNOWN")) for symbol, p in state.get("positions", {}).items()]
        capital = max(0.0, float(state.get("cash") or 0) - reserved)
        plan = self.allocator.allocate(AllocationRequest(capital, 20, None), candidates, holdings) if capital > 0 else {"new_buys": [], "excluded": []}
        return {
            "replayability": replayability, "market_data_status": market_status,
            "fundamental_pit_status": fundamental_status, "valuation_pit_status": valuation_status,
            "universe_status": universe_status, "live_decision_v1_run_status": "PASS" if replayability in {"FULL_PIT_VALID", "PIT_VALID_WITH_OPTIONAL_GAPS"} else "NOT_RUN",
            "rows": rows, "opens": opens, "closes": closes, "benchmark_close": benchmark_close,
            "allocation_plan": plan,
        }

    def phase81_historical_replay(self, period: str = "6M", starting_capital: float = 100000.0, benchmark: str = "NIFTY 50", start_date: str | None = None, end_date: str | None = None, slippage_bps: float = 10.0, transaction_cost_bps: float = 5.0) -> dict[str, Any]:
        import time
        call_started=time.perf_counter()
        from stock_app.replay_v10 import ReplayLock
        with ReplayLock(self.config.app_data_dir / "historical_feature_store_v10" / ".replay.lock"):
            # File-content invalidation also covers revisions retaining the same mtime.
            if hasattr(self.prices, "_history_cache"):
                self.prices._history_cache.clear()
            result=self._phase81_historical_replay_v10(period, starting_capital, benchmark, start_date, end_date, slippage_bps, transaction_cost_bps)
            result.setdefault("replay_request_stats", {"simulation_runs":1,"result_cache_hit":False})["wall_seconds"]=round(time.perf_counter()-call_started,6)
            return result

    def _phase81_historical_replay_v10(self, period: str = "6M", starting_capital: float = 100000.0, benchmark: str = "NIFTY 50", start_date: str | None = None, end_date: str | None = None, slippage_bps: float = 10.0, transaction_cost_bps: float = 5.0) -> dict[str, Any]:
        from stock_app.validation_v2 import ExecutionAssumptions, persist_replay, run_replay
        from stock_app.phase81_validation import period_start, trading_sessions_for_range
        period = str(period).upper()
        starting_capital=float(starting_capital); slippage_bps=float(slippage_bps); transaction_cost_bps=float(transaction_cost_bps)
        available = self._phase81_available_sessions()
        latest = str(end_date or (available[-1] if available else ""))
        if not latest:
            raise RuntimeError("NO_ACCEPTED_OFFICIAL_SESSION_FOR_REPLAY")
        start = period_start(latest, period, start_date)
        sessions = trading_sessions_for_range(available, start, latest)
        assumptions = ExecutionAssumptions(starting_capital=float(starting_capital), slippage_bps=float(slippage_bps), transaction_cost_bps=float(transaction_cost_bps))
        from stock_app.replay_v10 import source_signature, market_signature, digest
        from stock_app.replay_v10_final import ReplayCacheV10Final as ReplayCacheV10, VerifiedCheckpointStore, contract, valid_result, attest, VERSION
        from stock_app.replay_checkpoint_v2 import CheckpointStore, fingerprint
        from stock_app.replay_evidence_v3 import market_fingerprint, completed_replay_evidence
        import time
        inventory_started=time.perf_counter()
        source_fingerprint = source_signature(self.code_root, self.data_repo_root)
        market_fp = market_signature(self.prices)
        config = {"period": period, "start": start, "end": latest,
                  "starting_capital": starting_capital, "benchmark": benchmark,
                  "slippage_bps": slippage_bps, "transaction_cost_bps": transaction_cost_bps,
                  "v10_market_signature": market_fp, "v10_authority": "RESEARCH_ONLY",
                  "v10_universe_and_sectors": digest([(self.data_source_status().get("active") or {}).get("members"), self.allocator.sectors])}
        identity = contract(config, sessions, source_fingerprint, market_fp)
        ck_key = digest(identity)
        ck_store = VerifiedCheckpointStore(self.config.app_data_dir / "historical_replay_checkpoints_v2", ck_key)
        import time
        request_started=time.perf_counter()
        inventory_elapsed=request_started-inventory_started
        try:
            cached_result=ck_store.read_result()
        except (OSError,ValueError,KeyError,TypeError,AttributeError, __import__('zlib').error):
            cached_result=None
        if cached_result is not None and valid_result(cached_result, identity):
            cached_result["replay_cache_status"] = "COMPLETE_RESULT_REUSED"
            cached_result["replay_input_cache_stats"]={k:0 for k in cached_result.get("replay_build_stats",{})}
            cached_result["replay_input_cache_stats"]["completed_result_hits"]=1
            cached_result["replay_request_stats"] = {"simulation_runs":0,"scored_input_calculations":0,"feature_builds":0,"result_cache_hit":True,"elapsed_seconds":time.perf_counter()-request_started,"inventory_seconds":inventory_elapsed}
            return cached_result
        try:
            resume_state = ck_store.read_checkpoint()
        except (OSError,ValueError,KeyError,TypeError,AttributeError,__import__('zlib').error):
            import uuid
            if ck_store.path.exists():ck_store.path.rename(ck_store.path.with_name(ck_store.path.name+".invalid-"+uuid.uuid4().hex))
            resume_state=None
        import time
        progress_path = self.config.app_data_dir / "historical_replay_progress_v1.jsonl"
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        run_started = time.perf_counter()
        def replay_provider(session, state):
            started = time.perf_counter()
            try:
                package = self._validation_pit_session(session, state, assumptions, replay_cache)
                replay_cache.flush()
                event = {"session": session, "status": package.get("replayability"),
                         "market": package.get("market_data_status"),
                         "fundamental_pit": package.get("fundamental_pit_status")}
            except Exception as exc:
                event = {"session": session, "status": "ERROR", "error_type": type(exc).__name__}
                raise
            finally:
                event["elapsed_seconds"] = round(time.perf_counter() - started, 3)
                event["total_elapsed_seconds"] = round(time.perf_counter() - run_started, 3)
                event["source_fingerprint"] = source_fingerprint
                with progress_path.open("a", encoding="utf-8") as progress:
                    progress.write(json.dumps(event, separators=(",", ":")) + "\n")
            return package
        with ReplayCacheV10(store_directory=self.config.app_data_dir / "historical_feature_store_v10" / "performance_correction_v1",
                            source_fingerprint=source_fingerprint, market_fingerprint=market_fp,
                            history_provider=self.prices.history, source_roots=(self.data_repo_root, self.code_root)) as replay_cache:
            result = run_replay(requested_period=period, sessions=sessions, starting_capital=float(starting_capital), assumptions=assumptions, session_provider=replay_provider,
                                resume_checkpoint=resume_state, checkpoint_callback=ck_store.write_checkpoint)
            replay_cache.flush()
            result["replay_input_cache_stats"] = dict(replay_cache.stats)
            result["v10"] = {"schema": "SRE_REPLAY_V10_1", "authority": "RESEARCH_ONLY", "affects_live_decisions": False}
        if (source_signature(self.code_root, self.data_repo_root) != source_fingerprint or market_signature(self.prices) != market_fp
                or digest([(self.data_source_status().get("active") or {}).get("members"), self.allocator.sectors]) != config["v10_universe_and_sectors"]):
            # Preserve mixed-generation cache/checkpoint bytes for inspection;
            # never make them readable as valid evidence or delete prior V10 data.
            import uuid
            correction=self.config.app_data_dir / "historical_feature_store_v10" / "performance_correction_v1"
            suffix=".invalid-"+uuid.uuid4().hex
            if correction.exists():correction.rename(correction.with_name(correction.name+suffix))
            if ck_store.path.exists():ck_store.path.rename(ck_store.path.with_name(ck_store.path.name+suffix))
            raise RuntimeError("V10_INPUTS_CHANGED_DURING_REPLAY_RETRY_REQUIRED")
        result["replay_context_signature"] = config["v10_universe_and_sectors"]
        result["replay_market_content_signature"] = market_fp
        result["replay_fundamental_source_fingerprint"] = source_fingerprint
        result["authority"] = {**self.phase81_authority_trace(), "production_router_sha256": self._validation_router_sha()}
        result["automatic_yfinance_fallback"] = False
        result["broker_execution"] = False
        result["replay_id"] = persist_replay(self._phase81_db_path(), result, config)
        result["replay_cache_status"] = "RESUMED" if resume_state else "NEW_COMPUTATION"
        result["replay_build_stats"]=dict(result["replay_input_cache_stats"])
        result["replay_request_stats"]={"simulation_runs":1,"result_cache_hit":False,
            "cache_miss_reason":"NO_VALID_COMPLETED_RESULT_FOR_CURRENT_CONTRACT","inventory_seconds":inventory_elapsed,
            "scored_input_calculations":result["replay_build_stats"].get("v10_score_misses",0),
            "feature_builds":result["replay_build_stats"].get("v10_timeline_builds",0)}
        attest(result, identity)
        ck_store.write_result(result)
        return result

    def v10_historical_evidence(self):
        from stock_app.replay_v10 import source_signature, market_signature, digest
        from stock_app.replay_v10_final import completed_evidence
        return completed_evidence(self.config.app_data_dir / "historical_replay_checkpoints_v2",
                                  source_signature(self.code_root, self.data_repo_root), market_signature(self.prices),
                                  digest([(self.data_source_status().get("active") or {}).get("members"), self.allocator.sectors]))

    def phase81_paper_status(self, portfolio_id: str | None = None) -> dict[str, Any]:
        from stock_app.validation_v2 import ensure_legacy_continuity, load_portfolio
        continuity = ensure_legacy_continuity(
            self._phase81_db_path(), app_version=APP_VERSION,
            production_model_version="LIVE_DECISION_V1",
            evidence_pipeline_version="0.14.11-missing-evidence-coverage-repair",
            router_sha256=self._validation_router_sha(),
        )
        return {**load_portfolio(self._phase81_db_path(), portfolio_id), "label": "PAPER PORTFOLIO V2 — FORWARD ONLY", "authority": self.phase81_authority_trace(), "continuity_check": continuity, "holdings_monitoring": self.paper_holdings_monitoring()}

    def phase81_start_paper(self, starting_capital: float = 100000.0) -> dict[str, Any]:
        from stock_app.validation_v2 import create_portfolio, ensure_legacy_continuity, load_portfolio
        continuity = ensure_legacy_continuity(
            self._phase81_db_path(), app_version=APP_VERSION,
            production_model_version="LIVE_DECISION_V1",
            evidence_pipeline_version="0.14.11-missing-evidence-coverage-repair",
            router_sha256=self._validation_router_sha(),
        )
        current = load_portfolio(self._phase81_db_path())
        if current.get("active"):
            return {**current, "continuity_check": continuity}
        gate = self._daily_data_gate()
        run = self.ui_run_input() or {}
        session = str(gate.get("target_session") or "")
        if not gate.get("ready") or str(gate.get("latest_official_session") or session) != session:
            raise RuntimeError("OFFICIAL_DATA_NOT_READY")
        if str(run.get("market_session") or "") != session or not run.get("run_id"):
            raise RuntimeError("CURRENT_ACCEPTED_PRODUCTION_RUN_REQUIRED")
        return create_portfolio(self._phase81_db_path(), starting_session=session, starting_run_id=str(run["run_id"]), starting_capital=float(starting_capital), app_version=APP_VERSION, production_model_version=str(run.get("model_version") or "LIVE_DECISION_V1"), evidence_pipeline_version=APP_VERSION, router_sha256=self._validation_router_sha())

    def phase81_record_today(self) -> dict[str, Any]:
        from stock_app.live_decision_v1 import monitor
        from stock_app.validation_v2 import ExecutionAssumptions, process_paper_session
        status = self.phase81_paper_status()
        if not status.get("active"):
            return {"active": False, "status": "PAPER_PORTFOLIO_INACTIVE", "recorded": False}
        gate = self._daily_data_gate()
        session = str(gate.get("target_session") or "")
        latest = str(gate.get("latest_official_session") or "")
        run = self.ui_run_input() or {}
        rows = self.latest_prediction_rows(limit=200) if str(run.get("market_session") or "") == session else []
        symbols = {x.get("symbol") for x in rows} | {x.get("symbol") for x in status.get("positions", [])} | {x.get("symbol") for x in status.get("pending_orders", [])}
        index_sessions = sorted({
            str(bar.get("date"))[:10] for bar in self._validation_v2_index_bars()
            if str(bar.get("date") or "")[:10] <= session
        })
        opens, opens_by_session, closes = {}, {}, {}
        for symbol in {str(x) for x in symbols if x}:
            bars = [x for x in self.prices.history(symbol, limit=5000) if str(x.get("date"))[:10] <= session]
            if bars and str(bars[-1].get("date"))[:10] == session:
                if _finite(bars[-1].get("open")) is not None: opens[symbol] = float(bars[-1]["open"])
                if _finite(bars[-1].get("close")) is not None: closes[symbol] = float(bars[-1]["close"])
            by_session = {str(bar.get("date"))[:10]: bar for bar in bars}
            for order in status.get("pending_orders", []):
                if order.get("symbol") != symbol:
                    continue
                eligible = str(order.get("eligible_session") or "")
                if not eligible:
                    eligible = next((candidate for candidate in index_sessions if candidate > str(order.get("signal_session") or "")), "")
                bar = by_session.get(eligible)
                price = _finite((bar or {}).get("open"))
                if eligible and price is not None and price > 0:
                    opens_by_session.setdefault(eligible, {})[symbol] = float(price)
        row_map = {x["symbol"]: x for x in rows}
        checked = self.paper_holdings_monitoring(update=True)
        monitoring = {a["position_id"]: {"state": "EXIT SIGNAL" if a["action"] == "EXIT" else a["action"],
                     "reason": a["explanation"]} for a in checked["actions"]}
        paper_plan = self._paper_capital_plan(status, run) if rows else {"new_buys": [], "excluded": []}
        result = process_paper_session(self._phase81_db_path(), portfolio_id=status["portfolio_id"], expected_session=session, latest_official_session=latest, official_freshness="PASS" if gate.get("ready") else "FAIL", production_session=str(run.get("market_session") or ""), production_run_id=str(run.get("run_id") or ""), app_version=APP_VERSION, production_model_version=str(run.get("model_version") or "LIVE_DECISION_V1"), evidence_pipeline_version=APP_VERSION, candidates=rows, allocation_plan=paper_plan, official_opens=opens, official_closes=closes, available_sessions=index_sessions, official_opens_by_session=opens_by_session, monitoring=monitoring, assumptions=ExecutionAssumptions())
        result["holdings_monitoring"] = self.paper_holdings_monitoring(update=True)
        return result

    def latest_prediction_rows(self, limit: int = 20) -> list[dict[str, Any]]:
        active = self.active_prediction_run()
        if not active:
            rows = []
            run = None
        else:
            run = active["run"]
            rows = active["candidates"][: int(limit)]
        execution_preview = self._execution_preview_for_active_run() if active else {}
        out = []
        for row in rows:
            item = dict(row)
            live = item.get("live_decision") or {}
            item.update({key: value for key, value in live.items() if key != "evidence"})
            item["run_id"] = run["run_id"]
            item["market_session"] = run["market_session"]
            item["capital"] = run["capital"]
            item["horizon_sessions"] = run["horizon_sessions"]
            target_state = self.active_target_state()
            item["target_return_request"] = run["target_return"] if target_state.get("explicit") else None
            item["target_explicit"] = bool(target_state.get("explicit"))
            item["target_origin"] = target_state.get("origin")
            item["target_restored"] = bool(target_state.get("restored"))
            expected = _finite(item.get("expected_return"))
            requested = _finite(run.get("target_return")) if target_state.get("explicit") else None
            item["meets_target"] = None if requested is None or expected is None else expected >= requested
            item["target_gap"] = None if requested is None or expected is None else expected - requested
            item["target_status"] = "NO TARGET" if requested is None else ("RETURN THRESHOLD MET" if item["meets_target"] else "RETURN THRESHOLD BELOW")
            try:
                item["evidence"] = json.loads(item.get("evidence_json") or "{}")
            except Exception:
                item["evidence"] = {}
            try:
                item["raw"] = json.loads(item.get("raw_json") or "{}")
            except Exception:
                item["raw"] = {}
            execution = execution_preview.get(str(item.get("symbol") or "").upper().replace(".NS", ""), {})
            item.update({
                "cash_affordable": bool(execution.get("cash_affordable")),
                "cash_affordable_qty": int(execution.get("cash_affordable_qty") or 0),
                "executable": bool(execution.get("executable")) and live.get("executable") is True and bool(self._daily_data_gate().get("ready")) and str(self._daily_data_gate().get("target_session")) == str(run["market_session"]),
                "executable_qty": int(execution.get("executable_qty") or 0),
                "execution_action": execution.get("execution_action"),
                "execution_reason_code": execution.get("execution_reason_code"),
                "execution_reason": execution.get("execution_reason"),
                "single_stock_exception_applied": bool(execution.get("single_stock_exception_applied")),
            })
            if item["executable"]:
                item["execution_status"] = "EXECUTABLE ×" + str(item["executable_qty"])
            elif item["cash_affordable"] and not is_executable_decision(item.get("opportunity_status")):
                item["execution_status"] = "NOT EXECUTABLE - WATCH"
            elif item["cash_affordable"]:
                item["execution_status"] = "CASH AFFORDABLE · BLOCKED"
            else:
                item["execution_status"] = "NOT EXECUTABLE"
            out.append(item)
        if not out and self.preview_mode:
            base = _preview_stock("INFY")["prediction"]
            out = [
                {**base, "symbol":"INFY", "rank":1, "market_session":"PREVIEW"},
                {**base, "symbol":"TCS", "rank":2, "expected_return":0.055, "profit_probability":0.61, "confidence_label":"MEDIUM", "market_session":"PREVIEW"},
                {**base, "symbol":"RELIANCE", "rank":3, "expected_return":0.042, "profit_probability":0.58, "opportunity_status":"WATCH", "confidence_label":"MEDIUM", "market_session":"PREVIEW"},
                {**base, "symbol":"HDFCBANK", "rank":4, "expected_return":0.031, "profit_probability":0.55, "opportunity_status":"WATCH", "confidence_label":"MEDIUM", "market_session":"PREVIEW"},
            ][:limit]
        return out

    def portfolio_summary(self) -> dict[str, Any]:
        rows = []
        invested = 0.0
        value = 0.0
        priced = 0
        for p in self.portfolio.list_positions():
            item = dict(p)
            qty = float(item.get("quantity") or 0.0)
            buy = float(item.get("buy_price") or 0.0)
            invested_value = qty * buy
            invested += invested_value
            latest = self.prices.latest_close(str(item.get("symbol") or ""))
            latest_close = None if latest is None else float(latest.close)
            current_value = None if latest_close is None else qty * latest_close
            if current_value is not None:
                value += current_value
                priced += 1
            pnl_rs = None if current_value is None else current_value - invested_value
            pnl_pct = None if pnl_rs is None or invested_value == 0 else pnl_rs / invested_value * 100.0
            item.update({
                "latest_close": latest_close,
                "latest_session": None if latest is None else latest.session_date,
                "invested_value": invested_value,
                "current_value": current_value,
                "pnl_rs": pnl_rs,
                "pnl_pct": pnl_pct,
            })
            rows.append(item)
        total_pnl = value - invested if priced == len(rows) else None
        return {
            "items": rows,
            "summary": {
                "total_invested": invested,
                "latest_portfolio_value": value if priced == len(rows) else None,
                "total_pnl": total_pnl,
                "total_pnl_percent": None if total_pnl is None or invested == 0 else total_pnl / invested * 100.0,
                "holding_count": len(rows),
                "priced_count": priced,
            },
        }

    def canonical_ui_state(self) -> dict[str, Any]:
        source = self.data_source_status()
        active_source = dict(source.get("active") or {})
        source_session = active_source.get("latest_session")

        active = self.active_prediction_run() or {}
        run = dict(active.get("run") or {})
        run_id = run.get("run_id")
        run_session = run.get("market_session")

        daily = self._read_daily_state()
        success = dict(daily.get("last_successful_run") or {})
        success_session = success.get("market_session")
        success_official = (success.get("provenance") or {}).get("latest_official_session")

        expected = self.expected_market_session()
        expected_session = expected.get("expected_market_session")
        current_date = expected.get("current_calendar_date")

        # ISO market-session strings are YYYY-MM-DD, so lexical max is
        # chronological.  Ignore malformed/non-string values rather than
        # manufacturing a date.
        credible = [
            value for value in (source_session, success_official, success_session, run_session)
            if isinstance(value, str) and len(value) == 10 and value[4:5] == "-" and value[7:8] == "-"
        ]
        latest_official = max(credible) if credible else None
        active_analysis = run_session
        analysis_complete = bool(run_id and active.get("candidates") is not None)
        stale_active = bool(active_analysis and latest_official and active_analysis != latest_official)
        lane_counts = dict(run.get("lane_counts") or {})
        live_buy_count = int(lane_counts.get("momentum_buy") or 0) + int(lane_counts.get("recovery_buy") or 0) + int(lane_counts.get("both") or 0)
        if not analysis_complete:
            production_decision_status = "NO_ACTIVE_ANALYSIS"
        elif stale_active:
            production_decision_status = "STALE_ANALYSIS"
        elif live_buy_count > 0:
            production_decision_status = "BUY_OPPORTUNITIES_AVAILABLE"
        else:
            production_decision_status = "ANALYSIS_COMPLETE"

        if expected_session and latest_official == expected_session:
            freshness = "CURRENT"
        elif latest_official:
            freshness = "STALE"
        else:
            freshness = "UNAVAILABLE"

        return {
            "schema": "SRE_UI_SESSION_TRUTH_V1",
            "current_date": current_date,
            "expected_session": expected_session,
            "latest_official_session": latest_official,
            "active_analysis_session": active_analysis,
            "active_run_id": run_id,
            "active_run_market_session": run_session,
            "data_freshness": freshness,
            "production_authority": run.get("production_authority") or "LIVE_DECISION_V1",
            "analysis_complete": analysis_complete,
            "stale_active_run": stale_active,
            "lane_counts": lane_counts,
            "live_buy_count": live_buy_count,
            "production_decision_status": production_decision_status,
            "source_mode": source.get("mode"),
            "source_reported_latest_session": source_session,
        }

    def live_coverage(self) -> dict[str, Any]:
        from collections import Counter
        rows = self.latest_prediction_rows(limit=200)
        features: dict[str, Counter] = {}
        conditions: dict[str, Counter] = {}
        blockers = Counter()
        ready = partial = unavailable = financial = 0
        symbols = []
        for row in rows:
            live = row.get("live_decision") or {}
            fundamental = ((live.get("evidence") or {}).get("fundamental") or {})
            classified = live.get("evidence_classification") or classify_live_decision(live)
            is_financial = classified.get("domain") != "corporate"
            financial += int(is_financial)
            if not fundamental.get("available"):
                unavailable += 1
            elif (not is_financial and live.get("cash_flow_state") in ("ADEQUATE", "SUPPORTIVE") and
                  live.get("balance_sheet_state") in ("HEALTHY", "ACCEPTABLE")):
                ready += 1
            else:
                partial += 1
            for code in live.get("reason_codes") or []:
                blockers[str(code)] += 1
            per_symbol = {}
            for name, item in (fundamental.get("feature_coverage") or {}).items():
                status = str((item or {}).get("status") or "MISSING").upper()
                status = status if status in ("AVAILABLE", "MISSING", "STALE") else "MISSING"
                features.setdefault(name, Counter())[status] += 1
                per_symbol[name] = status
            for name, item in (classified.get("families") or {}).items():
                conditions.setdefault(name, Counter())[str(item.get("condition"))] += 1
            symbols.append({"symbol": row.get("symbol"), "final_action": live.get("final_action"),
                            "missing_evidence": classified.get("missing") or [],
                            "unfavorable_evidence": classified.get("unfavorable") or [],
                            "evidence_classification": classified, "features": per_symbol})
        for counts in features.values():
            counts["MISSING"] += len(rows) - sum(counts.values())
        lane = (self.active_prediction_run() or {}).get("run", {}).get("lane_counts") or {}
        return {"authority": "LIVE_DECISION_V1", "model_version": APP_VERSION, "universe_size": len(rows),
                "fundamental_ready": ready, "fundamental_partial": partial,
                "fundamental_unavailable": unavailable, "financial_domain_count": financial,
                "nonfinancial_count": len(rows) - financial, "lane_counts": lane,
                "blocker_counts": dict(blockers.most_common()),
                "evidence_condition_counts": {name: dict(counts) for name, counts in sorted(conditions.items())},
                "feature_coverage_counts": {name: dict(counts) for name, counts in sorted(features.items())},
                "symbols": symbols}

    def latest_run_input(self) -> dict[str, Any] | None:
        active = self.active_prediction_run()
        return None if not active else dict(active.get("run") or {})

    def build_capital_plan(self, capital: float, horizon: int, target_percent: float | None) -> dict[str, Any]:
        target = None if target_percent in (None, 0) else float(target_percent) / 100.0
        active_run, reused = self.ensure_analysis_run(capital, horizon, target)
        gate = self._daily_data_gate()
        if not gate.get("ready") or str(gate.get("target_session")) != str(active_run["run"]["market_session"]):
            active_run = {**active_run, "candidates": []}
        all_inputs = self.allocator.candidates_from_latest_run(active_run)
        inputs = [row for row in all_inputs if is_executable_decision(row.opportunity_status)]
        result = self.allocator.allocate(
            AllocationRequest(capital, horizon, target),
            inputs,
            self.allocator.holdings_from_portfolio(),
        )
        for row in result.get("rows", []):
            row["reason_text"] = explain_reason_code(row.get("reason_code", ""))
        for row in result.get("new_buys", []):
            row["reason_text"] = explain_reason_code(row.get("reason_code", ""))
        live_by_symbol = {row["symbol"]: row.get("live_decision") or {} for row in active_run.get("candidates", [])}
        for row in result.get("rows", []) + result.get("new_buys", []):
            live = live_by_symbol.get(row.get("symbol"), {})
            row.update({key: live.get(key) for key in ("strategy_style", "primary_style", "secondary_style", "momentum_thesis", "recovery_thesis", "business_health", "technical_state", "confidence", "thesis", "final_action")})
        result["source_run"] = dict(active_run.get("run") or {})
        result["active_run_id"] = result["source_run"].get("run_id")
        result["reused_run"] = reused
        summary = result.get("capital_summary") or {}
        remaining = float(summary.get("remaining_cash") or 0.0)
        deployable = float(summary.get("deployable_capital") or capital)
        reason_counts: dict[str, int] = {}
        for row in result.get("rows", []):
            code = str(row.get("reason_code") or "UNKNOWN")
            reason_counts[code] = reason_counts.get(code, 0) + 1
        summary["remaining_cash_fraction"] = 0.0 if deployable <= 0 else remaining / deployable
        summary["unused_cash_reason_counts"] = reason_counts
        if remaining <= 0.005:
            summary["unused_cash_explanation"] = "Capital was fully deployed within whole-share and portfolio constraints."
        elif result.get("new_buys"):
            exception_rows = [row for row in result.get("new_buys", []) if row.get("single_stock_exception_applied")]
            if exception_rows:
                row = exception_rows[0]
                summary["unused_cash_explanation"] = (
                    "A small-capital exception was used because only one target-qualified model-executable stock was affordable within the small-cap threshold. "
                    + "The plan proposes " + str(int(row.get("shares") or 0)) + " whole share(s) of " + str(row.get("symbol")) + " without leverage."
                )
            else:
                cap = float((result.get("capital_summary") or {}).get("effective_position_cap_fraction") or getattr(self.allocator, "policy", {}).get("max_position_capital_fraction", 0.35) or 0.35)
                target_n = (result.get("capital_summary") or {}).get("diversification_target_holdings")
                target_note = (" The allocator targets at least " + str(target_n) + " holdings when enough target-qualified executable stocks exist.") if target_n else ""
                summary["unused_cash_explanation"] = (
                    f"Cash is intentionally left unallocated. Each selected stock is capped at {cap*100:.0f}% of deployable capital."
                    + target_note
                    + " Stocks below the desired-return threshold are excluded rather than added merely to deploy cash."
                )
        else:
            details = ", ".join(f"{code}: {count}" for code, count in sorted(reason_counts.items())) or "no executable LIVE_DECISION_V1 BUY opportunities"
            summary["unused_cash_explanation"] = "No stock was executable for these exact inputs. Allocator reasons — " + details + "."
        live_rows = list(active_run.get("candidates") or [])
        lane_counts = (active_run.get("run") or {}).get("lane_counts") or {}
        blocker_symbols: dict[str, set[str]] = {}
        for row in live_rows:
            symbol = str(row.get("symbol") or "").strip()
            for code in set((row.get("live_decision") or {}).get("reason_codes") or []):
                blocker_symbols.setdefault(str(code), set()).add(symbol)
        blocker_counts = sorted(
            ((code, len(symbols)) for code, symbols in blocker_symbols.items()),
            key=lambda item: (-item[1], item[0]),
        )
        summary["live_lane_counts"] = lane_counts
        summary["top_blockers"] = dict(blocker_counts[:8])
        summary["blocker_count_semantics"] = "UNIQUE_SYMBOLS"
        evidence_counts = Counter()
        for item in live_rows:
            live = item.get("live_decision") or {}
            classified = live.get("evidence_classification") or classify_live_decision(live)
            if classified.get("domain") != "corporate":
                evidence_counts["BANK/NBFC policy not validated"] += 1
                continue
            families = classified.get("families") or {}
            leverage = (families.get("Debt / leverage / DebtEquityRatio") or {}).get("condition")
            cashflow = (families.get("Operating cash flow") or {}).get("condition")
            history = (families.get("Historical PIT valuation reference") or {}).get("condition")
            if leverage == "PRESENT_BUT_UNFAVORABLE": evidence_counts["Balance-sheet present but caution/weak"] += 1
            elif leverage != "PRESENT_AND_SUPPORTIVE": evidence_counts["Balance-sheet unavailable"] += 1
            if cashflow == "PRESENT_BUT_UNFAVORABLE": evidence_counts["Cash flow present but not supportive"] += 1
            elif cashflow != "PRESENT_AND_SUPPORTIVE": evidence_counts["Cash flow unavailable"] += 1
            if history != "PRESENT_AND_SUPPORTIVE": evidence_counts["PIT valuation history unavailable"] += 1
        summary["evidence_condition_counts"] = dict(evidence_counts)
        summary["live_universe_size"] = len(live_rows)
        summary["ui_state"] = self.canonical_ui_state()
        if not result.get("new_buys"):
            summary["unused_cash_explanation"] = "No executable LIVE_DECISION_V1 BUY opportunities for the selected inputs. Cash is retained."
        result["capital_summary"] = summary
        return result

    def technical_v2_context(self, symbol: str, bars: list[dict[str, Any]] | None = None, horizon_override: int | None = None, replay_cache: Any = None) -> dict[str, Any]:
        import pandas as _pd
        from stock_app.technical_v2 import analyze

        symbol = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        source_bars = list(bars) if bars is not None else self.prices.history(symbol, limit=5000)
        if not source_bars:
            return {
                "schema": "SRE_TECHNICAL_INTELLIGENCE_V2",
                "authority": "LIVE_EVIDENCE",
                "status": "NO_DATA",
                "technical_score": None,
            }

        benchmark_bars = []
        for index_symbol in ("INDEX_NSEI", "NSEI", "^NSEI", "NIFTY"):
            try:
                candidate = (replay_cache.history(index_symbol, 5000, self.prices.history) if replay_cache is not None else self.prices.history(index_symbol, limit=5000))
            except Exception:
                candidate = []
            if candidate:
                benchmark_bars = candidate
                break

        vix_bars = []
        for vix_symbol in ("INDEX_INDIAVIX", "INDIAVIX", "INDIA_VIX"):
            try:
                candidate = (replay_cache.history(vix_symbol, 1500, self.prices.history) if replay_cache is not None else self.prices.history(vix_symbol, limit=1500))
            except Exception:
                candidate = []
            if candidate:
                vix_bars = candidate
                break

        active = (self.latest_run_input() or {}) if horizon_override is None else {}
        horizon = int(horizon_override or active.get("horizon_sessions") or 20)
        def compute():
            return analyze(
            _pd.DataFrame(source_bars),
            _pd.DataFrame(benchmark_bars) if benchmark_bars else None,
            horizon_sessions=horizon,
            india_vix=_pd.DataFrame(vix_bars) if vix_bars else None,
            )
        if replay_cache is not None and hasattr(replay_cache, "technical_timeline"):
            return replay_cache.technical_timeline(symbol, horizon, source_bars, benchmark_bars, vix_bars)
        if replay_cache is not None:
            return replay_cache.technical(symbol, horizon, source_bars, benchmark_bars, vix_bars, compute)
        return compute()

    def fundamental_v3_context(
        self,
        symbol: str,
        latest_price: float | None = None,
        decision_timestamp: str | None = None,
    ) -> dict[str, Any]:
        from stock_app.fundamental_v3 import analyze

        active = (self.latest_run_input() or {}) if not decision_timestamp else {}
        cutoff = decision_timestamp or active.get("market_session")
        primary = analyze(
            self.data_repo_root,
            symbol,
            decision_timestamp=cutoff,
            latest_price=latest_price,
        )
        if (
            not primary.get("available")
            and self.code_root.resolve() != self.data_repo_root.resolve()
        ):
            fallback = analyze(
                self.code_root,
                symbol,
                decision_timestamp=cutoff,
                latest_price=latest_price,
            )
            if fallback.get("available"):
                return fallback
        return primary

    def combined_v2_context(
        self,
        symbol: str,
        prediction: dict[str, Any] | None = None,
        bars: list[dict[str, Any]] | None = None,
        latest_price: float | None = None,
    ) -> dict[str, Any]:
        from stock_app.combined_prediction_v2 import combine
        symbol = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        source_bars = list(bars) if bars is not None else self.prices.history(symbol, limit=5000)
        if latest_price is None and source_bars:
            latest_price = _finite(source_bars[-1].get("close"))
        if prediction is None:
            prediction = next((row for row in self.latest_prediction_rows(limit=100) if str(row.get("symbol") or "").upper().replace(".NS", "").replace(".BO", "") == symbol), None)
        technical = self.technical_v2_context(symbol, source_bars)
        decision_timestamp = (prediction or {}).get("market_session") or (source_bars[-1].get("date") if source_bars else None)
        fundamental = self.fundamental_v3_context(symbol, latest_price, decision_timestamp)
        current = bool((self.data_source_status().get("active") or {}).get("analysis_data_current"))
        return combine(prediction, technical, fundamental, analysis_data_current=current)

    def combined_v2_rankings(self, limit: int = 20) -> list[dict[str, Any]]:
        source_rows = self.latest_prediction_rows(limit=max(1, min(100, int(limit) * 3)))
        shadow_rows = []
        for row in source_rows:
            symbol = str(row.get("symbol") or "").upper().replace(".NS", "").replace(".BO", "")
            if not symbol:
                continue
            bars = self.prices.history(symbol, limit=5000)
            latest_price = _finite(bars[-1].get("close")) if bars else None
            combined = self.combined_v2_context(symbol, row, bars, latest_price)
            shadow_rows.append({
                "symbol": symbol,
                "production_rank": row.get("rank"),
                "production_status": row.get("opportunity_status"),
                "combined_score": combined.get("combined_score"),
                "combined_label": combined.get("combined_label"),
                "combined_confidence": combined.get("confidence"),
                "combined_evidence_coverage": combined.get("evidence_coverage"),
                "authority": combined.get("authority"),
                "promotion_allowed": combined.get("promotion_allowed"),
            })
        shadow_rows.sort(key=lambda x: (
            x.get("combined_score") is None,
            -(float(x.get("combined_score")) if x.get("combined_score") is not None else -1.0),
            int(x.get("production_rank") or 10**9),
            str(x.get("symbol") or ""),
        ))
        for index, row in enumerate(shadow_rows, start=1):
            row["combined_shadow_rank"] = index
        return shadow_rows[: max(1, int(limit))]

    def stock_context(self, symbol: str, limit: int) -> dict[str, Any]:
        symbol = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        bars = self.prices.history(symbol, limit=max(0, int(limit)))
        if not bars:
            if self.preview_mode:
                return _preview_stock(symbol)
            mode = self.data_source_status().get("mode")
            label = "connected official dataset" if mode == "REAL_OFFICIAL_DATA" else "connected frozen-history dataset"
            raise HTTPException(status_code=404, detail=f"{symbol} is known to the app, but no OHLCV history exists for it in the {label}. Chart unavailable until history is added/refreshed.")
        last = bars[-1]
        close = float(last["close"])
        prev = float(bars[-2]["close"]) if len(bars) > 1 else close
        trailing_252 = bars[-252:]

        perf: dict[str, float | None] = {}
        for name, sessions in [("1W", 5), ("1M", 21), ("3M", 63), ("6M", 126), ("1Y", 252)]:
            ref_idx = max(0, len(bars) - 1 - sessions)
            perf[name] = _pct(close, float(bars[ref_idx]["close"])) if len(bars) > 1 else None

        with self.db.connect() as conn:
            pred = conn.execute(
                """
                SELECT c.*, r.market_session, r.horizon_sessions, r.target_return AS target_return_request,
                       r.capital, r.engine_version
                FROM prediction_candidates c
                JOIN prediction_runs r ON r.run_id=c.run_id
                WHERE UPPER(REPLACE(c.symbol,'.NS',''))=? AND r.run_id=?
                ORDER BY c.rank ASC LIMIT 1
                """,
                (symbol, (self.latest_run_input() or {}).get("run_id", "")),
            ).fetchone()
            rec = conn.execute(
                """
                SELECT rs.*, ar.session_date
                FROM recommendation_snapshots rs
                JOIN analysis_runs ar ON ar.id=rs.analysis_run_id
                WHERE UPPER(REPLACE(rs.symbol,'.NS',''))=?
                ORDER BY ar.id DESC, rs.id DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
            positions = conn.execute(
                "SELECT * FROM portfolio_positions WHERE UPPER(REPLACE(symbol,'.NS',''))=? AND COALESCE(position_status,'OPEN')!='CLOSED' ORDER BY id",
                (symbol,),
            ).fetchall()

        prediction = next((r for r in self.latest_prediction_rows(limit=200) if r.get("symbol") == symbol), None)
        if prediction:
            target_state = self.active_target_state()
            prediction["target_explicit"] = bool(target_state.get("explicit"))
            prediction["target_origin"] = target_state.get("origin")
            prediction["target_restored"] = bool(target_state.get("restored"))
            if not target_state.get("explicit"):
                prediction["target_return_request"] = None
                prediction["target_status"] = "NO TARGET"
        if prediction:
            for field in ("evidence_json", "raw_json"):
                if isinstance(prediction.get(field), str):
                    try:
                        prediction[field[:-5] if field.endswith("_json") else field] = json.loads(prediction[field])
                    except Exception:
                        pass

        overlays = []
        if prediction:
            entry = _finite(prediction.get("latest_close"))
            requested_target = _finite(prediction.get("target_return_request"))
            expected = _finite(prediction.get("expected_return"))
            downside = _finite(prediction.get("downside_risk"))
            if entry:
                overlays.append({"kind": "reference", "label": "Model reference", "price": entry})
                if requested_target and requested_target > 0:
                    overlays.append({"kind": "target", "label": "Requested target", "price": entry * (1 + requested_target)})
                elif expected and expected > 0:
                    overlays.append({"kind": "target", "label": "Expected-return level", "price": entry * (1 + expected)})
                if downside and downside > 0:
                    overlays.append({"kind": "risk", "label": "Estimated downside", "price": entry * (1 - downside)})
        for p in positions:
            overlays.append({"kind": "entry", "label": f"Portfolio entry × {p['quantity']:g}", "price": float(p["buy_price"]), "date": p["buy_date"]})

        ds = self.data_source_status()
        return {
            "symbol": symbol,
            "history": {
                "available": True,
                "bars_returned": len(bars),
                "first_session": bars[0]["date"] if bars else None,
                "last_session": bars[-1]["date"] if bars else None,
                "source_mode": ds.get("mode"),
                "provenance": (ds.get("active") or {}).get("provenance"),
                "freshness_status": (ds.get("active") or {}).get("freshness_status"),
            },
            "active_run": self.latest_run_input(),
            "quote": {
                "date": last["date"],
                "close": close,
                "change": close - prev,
                "change_pct": _pct(close, prev),
                "open": last["open"],
                "high": last["high"],
                "low": last["low"],
                "volume": last["volume"],
                "high_52w": max((float(x["high"]) for x in trailing_252), default=close),
                "low_52w": min((float(x["low"]) for x in trailing_252), default=close),
            },
            "performance": perf,
            "bars": bars,
            "prediction": prediction,
            "recommendation": None if self.latest_run_input() else (dict(rec) if rec else None),
            "positions": [dict(x) for x in positions],
            "overlays": overlays,
            "live_decision": (prediction or {}).get("live_decision"),
            "technical_v2": self.technical_v2_context(symbol, bars),
            "fundamental_v3": self.fundamental_v3_context(
                symbol,
                close,
                (prediction or {}).get("market_session") or last.get("date"),
            ),
            "combined_v2": self.combined_v2_context(symbol, prediction, bars, close),
        }


def create_app(repo_root: Path | None = None, app_data_dir: Path | None = None) -> FastAPI:
    ctx = ModernAppContext(repo_root=repo_root, app_data_dir=app_data_dir)
    app = FastAPI(title="Stock Recommendation Engine — Modern UI", version=APP_VERSION)
    frontend = Path(__file__).resolve().parent / "frontend"

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "app_version": APP_VERSION,
            "repo_root": str(ctx.data_repo_root),
            "code_root": str(ctx.code_root),
            "database": str(ctx.config.database_path),
            "symbols": len(ctx.symbols()),
            "decision_authority": "LIVE_DECISION_V1",
            "preview_mode": ctx.preview_mode,
            "data_source": ctx.data_source_status(),
            "ui_state": ctx.canonical_ui_state(),
        }

    @app.get("/api/data-source")
    def data_source() -> dict[str, Any]:
        return ctx.data_source_status()

    @app.post("/api/data-source")
    def set_data_source(req: DataSourceRequest) -> dict[str, Any]:
        try:
            return {"ok": True, **ctx.connect_data_repo(req.path)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/symbols")
    def symbols(q: str = "", limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
        query = q.strip().upper()
        rows = [s for s in ctx.symbols() if not query or query in s]
        return {"symbols": rows[:limit], "total": len(rows)}

    def _gate_a_quality(_ctx):
        from stock_app.gate_a_quality import assess
        return assess(_ctx.v10_historical_evidence())

    @app.get("/api/opportunities")
    def opportunities(limit: int = Query(200, ge=1, le=200)) -> dict[str, Any]:
        rows = ctx.latest_prediction_rows(limit=limit)
        return {"items": rows, "count": len(rows), "run": ctx.ui_run_input(), "target_state": ctx.active_target_state(), "ui_state": ctx.canonical_ui_state(),
                "historical_validation": ctx.v10_historical_evidence(), "strategy_quality": _gate_a_quality(ctx)}

    @app.get("/api/validation/gate-a-diagnostics")
    def gate_a_diagnostics() -> dict[str, Any]:
        from stock_app.gate_a_diagnostics import inspect_cache
        from stock_app.replay_v10 import source_signature, market_signature, digest
        from stock_app.replay_v10_final import valid_result
        return inspect_cache(ctx.config.app_data_dir / "historical_replay_checkpoints_v2",
                             source_signature(ctx.code_root, ctx.data_repo_root),
                             market_signature(ctx.prices),
                             digest([(ctx.data_source_status().get("active") or {}).get("members"), ctx.allocator.sectors]),
                             result_validator=valid_result)

    @app.get("/api/validation/gate-a-recovery-plan")
    def gate_a_recovery_plan() -> dict[str, Any]:
        from stock_app.gate_a_recovery_plan import plan_recovery
        from stock_app.replay_v10 import source_signature, market_signature, digest
        from stock_app.replay_v10_final import valid_result
        return plan_recovery(
            ctx.config.app_data_dir / "historical_replay_checkpoints_v2",
            source_signature(ctx.code_root, ctx.data_repo_root),
            market_signature(ctx.prices),
            digest([(ctx.data_source_status().get("active") or {}).get("members"), ctx.allocator.sectors]),
            result_validator=valid_result,
        )

    @app.get("/api/validation/strategy-quality")
    def gate_a_strategy_quality() -> dict[str, Any]:
        from stock_app.gate_a_quality import assess
        return assess(ctx.v10_historical_evidence())

    @app.get("/api/validation/historical-evidence/summary")
    def historical_evidence_summary() -> dict[str, Any]:
        from stock_app.replay_evidence_v3 import completed_replay_evidence
        return ctx.v10_historical_evidence()

    @app.get("/api/live/coverage")
    def live_coverage() -> dict[str, Any]:
        return ctx.live_coverage()

    @app.get("/api/ui-consistency")
    def ui_consistency() -> dict[str, Any]:
        truth = ctx.canonical_ui_state()
        run_id = truth.get("active_run_id")
        return {
            **truth,
            "overview_run_id": run_id,
            "opportunities_run_id": run_id,
            "capital_run_id": run_id,
            "today_run_id": run_id,
            "accepted_session": truth.get("active_analysis_session"),
        }

    @app.get("/api/portfolio")
    def portfolio() -> dict[str, Any]:
        return ctx.portfolio_summary()

    @app.post("/api/portfolio")
    def add_portfolio(req: HoldingRequest) -> dict[str, Any]:
        position_id = ctx.portfolio.add_position(req.symbol, req.quantity, req.buy_price, req.buy_date, req.notes)
        ctx._persist_position_thesis(position_id, req.symbol, req.buy_date)
        return {"ok": True, "position_id": position_id, **ctx.portfolio_summary()}

    @app.put("/api/portfolio/{position_id}")
    def update_portfolio(position_id: int, req: HoldingRequest) -> dict[str, Any]:
        ctx.portfolio.update_position(position_id, req.symbol, req.quantity, req.buy_price, req.buy_date, req.notes)
        return {"ok": True, **ctx.portfolio_summary()}

    @app.delete("/api/portfolio/{position_id}")
    def delete_portfolio(position_id: int) -> dict[str, Any]:
        ctx.portfolio.remove_position(position_id)
        return {"ok": True, **ctx.portfolio_summary()}

    @app.post("/api/portfolio/{position_id}/sell")
    def sell_portfolio(position_id: int, req: SellRequest) -> dict[str, Any]:
        ctx.lifecycle.close_position(position_id, req.sale_date, req.sale_price, req.quantity_sold, req.charges)
        return {"ok": True, **ctx.portfolio_summary()}

    @app.post("/api/opportunities/run")
    def run_opportunities(req: OpportunityRunRequest) -> dict[str, Any]:
        ctx.require_real_data()
        from stock_app.historical import PredictionRequest
        target = None if req.target_return_percent is None else req.target_return_percent / 100.0
        active, reused = ctx.ensure_analysis_run(req.capital, req.horizon_sessions, target)
        rows = ctx.latest_prediction_rows(limit=200)
        return {"ok": True, "items": rows, "count": len(rows), "fundamentals": None, "run": ctx.ui_run_input(), "target_state": ctx.active_target_state(), "reused_run": reused, "ui_state": ctx.canonical_ui_state()}

    @app.get("/api/capital-plan")
    def capital_plan_default() -> dict[str, Any]:
        latest = ctx.ui_run_input()
        return {"latest_run": latest, "target_state": ctx.active_target_state()}

    @app.post("/api/capital-plan")
    def capital_plan(req: AllocationPlanRequest) -> dict[str, Any]:
        return ctx.build_capital_plan(req.deployable_capital, req.horizon_sessions, req.target_return_percent)

    @app.get("/api/validation/authority")
    def validation_authority() -> dict[str, Any]:
        return ctx.phase81_authority_trace()

    @app.post("/api/validation/historical-replay")
    def validation_historical_replay(period: str = "6M", starting_capital: float = 100000.0, benchmark: str = "NIFTY 50", start_date: str | None = None, end_date: str | None = None, slippage_bps: float = 10.0, transaction_cost_bps: float = 5.0) -> dict[str, Any]:
        return ctx.phase81_historical_replay(period=period, starting_capital=starting_capital, benchmark=benchmark, start_date=start_date, end_date=end_date, slippage_bps=slippage_bps, transaction_cost_bps=transaction_cost_bps)

    @app.get("/api/validation/historical-evidence")
    def validation_historical_evidence() -> dict[str, Any]:
        from stock_app.replay_evidence_v3 import completed_replay_evidence
        return ctx.v10_historical_evidence()

    @app.get("/api/validation/paper-portfolio")
    def validation_paper_status(portfolio_id: str | None = None) -> dict[str, Any]:
        return ctx.phase81_paper_status(portfolio_id)

    @app.post("/api/validation/paper-portfolio/start")
    def validation_paper_start(starting_capital: float = 100000.0) -> dict[str, Any]:
        return ctx.phase81_start_paper(starting_capital=starting_capital)

    @app.post("/api/validation/paper-portfolio/record-today")
    def validation_paper_record_today() -> dict[str, Any]:
        return ctx.phase81_record_today()

    @app.get("/api/today")
    def today() -> dict[str, Any]:
        return ctx.live_today_summary()

    @app.get("/api/post-close-daily-flow")
    def post_close_daily_flow_status() -> dict[str, Any]:
        return ctx.post_close_daily_status()

    @app.post("/api/post-close-daily-flow")
    def run_post_close_daily_flow(force: bool = False) -> dict[str, Any]:
        return ctx.run_post_close_daily_flow(force=force)

    @app.post("/api/today/run")
    def run_today(req: MonitoringRunRequest) -> dict[str, Any]:
        # Resolve the eligible session internally; caller cannot bypass the cutoff.
        ctx.monitoring.run_daily_monitoring(req.market_session)
        ctx.paper_holdings_monitoring(update=True)
        return {"ok": True, **ctx.live_today_summary()}

    @app.post("/api/daily-workflow")
    def run_daily_workflow() -> dict[str, Any]:
        result = ctx.daily_workflow.run()
        ctx.paper_holdings_monitoring(update=True)
        return {"ok": True, "result": result, "today": ctx.live_today_summary()}

    @app.get("/api/history")
    def history(limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
        predictions = ctx.historical.get_history()[:limit]
        monitoring = ctx.monitoring.history(limit=limit)
        return {"prediction_runs": predictions, "monitoring": monitoring}

    @app.get("/api/system")
    def system() -> dict[str, Any]:
        return {"health": ctx.hardening.health_report(), "latest_backup": str(ctx.hardening.latest_backup() or "")}

    @app.post("/api/system/backup")
    def create_backup() -> dict[str, Any]:
        path = ctx.hardening.create_backup(reason="native_ui_manual")
        return {"ok": True, "path": str(path), "health": ctx.hardening.health_report()}

    @app.post("/api/system/support-bundle")
    def create_support_bundle() -> dict[str, Any]:
        path = ctx.hardening.create_support_bundle()
        return {"ok": True, "path": str(path)}

    @app.get("/api/glossary")
    def glossary(q: str = "") -> dict[str, Any]:
        query = q.strip().lower()
        rows = [x for x in GLOSSARY_TERMS if not query or query in x["term"].lower() or query in x["definition"].lower() or query in x["category"].lower()]
        return {"items": rows, "count": len(rows)}

    @app.get("/api/combined-v2/rankings")
    def combined_v2_rankings(limit: int = Query(20, ge=1, le=50)) -> dict[str, Any]:
        rows = ctx.combined_v2_rankings(limit)
        return {
            "schema": "SRE_COMBINED_PREDICTION_V2_RANKINGS",
            "authority": "DIAGNOSTIC_ONLY",
            "production_rank_changed": False,
            "promotion_allowed": False,
            "items": rows,
            "count": len(rows),
        }

    @app.get("/api/stocks/{symbol}")
    def stock(symbol: str, limit: int = Query(1300, ge=60, le=5000)) -> dict[str, Any]:
        return ctx.stock_context(symbol, limit)

    @app.get("/api/stocks/{symbol}/technical-v2")
    def stock_technical_v2(symbol: str) -> dict[str, Any]:
        return ctx.technical_v2_context(symbol)

    @app.get("/api/stocks/{symbol}/fundamental-v3")
    def stock_fundamental_v3(symbol: str) -> dict[str, Any]:
        bars = ctx.prices.history(symbol, limit=2)
        latest_price = float(bars[-1]["close"]) if bars else None
        active = ctx.latest_run_input() or {}
        decision_timestamp = active.get("market_session") or (bars[-1]["date"] if bars else None)
        return ctx.fundamental_v3_context(symbol, latest_price, decision_timestamp)

    @app.get("/api/stocks/{symbol}/combined-v2")
    def stock_combined_v2(symbol: str) -> dict[str, Any]:
        bars = ctx.prices.history(symbol, limit=5000)
        latest_price = float(bars[-1]["close"]) if bars else None
        clean = symbol.upper().replace(".NS", "").replace(".BO", "")
        prediction = next((row for row in ctx.latest_prediction_rows(limit=100) if str(row.get("symbol") or "").upper().replace(".NS", "").replace(".BO", "") == clean), None)
        return ctx.combined_v2_context(symbol, prediction, bars, latest_price)

    @app.get("/api/dashboard")
    def dashboard() -> dict[str, Any]:
        opps = ctx.latest_prediction_rows(limit=8)
        portfolio_data = ctx.portfolio_summary()
        status = ctx.v1.get_status()
        return {
            "opportunities": opps,
            "positions": portfolio_data["items"],
            "portfolio_summary": portfolio_data["summary"],
            "today": ctx.live_today_summary(),
            "engine_status": status,
            "symbol_count": int((ctx.data_source_status().get("active") or {}).get("stock_files") or 0),
            "app_version": APP_VERSION,
            "active_run": ctx.ui_run_input(),
            "target_state": ctx.active_target_state(),
            "data_source": ctx.data_source_status(),
        }

    app.mount("/assets", StaticFiles(directory=frontend), name="assets")

    @app.get("/")
    @app.get("/{path:path}")
    def shell(path: str = ""):
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        return FileResponse(frontend / "index.html")

    return app
