from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .engine import OfficialV1Adapter
from .storage import AppDatabase
from .official_cache_guard import guarded

ENGINE_VERSION = "HIST_TECH_PREDICTOR_V1"
MODEL_VERSION = "HISTORICAL_ANALOGUE_NEAREST_STATE_V1"
FEATURE_VERSION = "TECHNICAL_FEATURE_CONTRACT_V1"
VALIDATION_CONTRACT = "WALK_FORWARD_DATE_ORDERED_FINAL_HOLDOUT_2026_PARTIAL_V1"
MIN_HORIZON = 5
MAX_HORIZON = 126
MONTH_TO_SESSIONS = 21
MIN_WARMUP = 130
MAX_ANALOGUES = 160
MIN_ANALOGUES = 20


@dataclass(frozen=True)
class MarketBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class PredictionRequest:
    capital: float
    horizon_sessions: int
    target_return: float | None = None


@dataclass(frozen=True)
class CandidatePrediction:
    rank: int
    symbol: str
    latest_close: float | None
    affordable_qty: int
    profit_probability: float | None
    target_probability: float | None
    expected_return: float | None
    median_return: float | None
    downside_risk: float | None
    max_adverse_excursion: float | None
    max_favorable_excursion: float | None
    sample_size: int
    confidence_label: str
    ranking_score: float
    v1_status: str
    opportunity_status: str
    evidence: dict[str, Any]
    raw: dict[str, Any]


@dataclass(frozen=True)
class PredictionRun:
    run_id: str
    market_session: str
    capital: float
    horizon_sessions: int
    target_return: float | None
    engine_version: str
    model_version: str
    feature_contract_version: str
    training_cutoff: str
    validation_contract: str
    status: str
    candidates: list[CandidatePrediction]
    summary: dict[str, Any]


class HistoricalTechnicalPredictionAdapter:
    def __init__(self, repo_root: Path, db: AppDatabase, v1_adapter: OfficialV1Adapter | None = None):
        self.repo_root = repo_root
        self.db = db
        self.v1_adapter = v1_adapter or OfficialV1Adapter(repo_root, db)
        self.cache_roots = [
            repo_root / "data" / "normalized" / "nse_official" / "equity_bhavcopy" / "expanded_universe_2026_10_05",
            repo_root / "data" / "normalized" / "nse_official" / "equity_bhavcopy" / "stage4a3_2026_10_05",
        ]

    @staticmethod
    def horizon_from_user(number: str | int, unit: str) -> int:
        try:
            value = int(str(number).strip())
        except ValueError as exc:
            raise ValueError("Holding period must be a whole number.") from exc
        if value <= 0:
            raise ValueError("Holding period must be positive.")
        if unit.lower().startswith("month"):
            if value < 1 or value > 6:
                raise ValueError("Months must be between 1 and 6. The current validated engine supports up to 126 trading sessions (about 6 months).")
            sessions = value * MONTH_TO_SESSIONS
        else:
            sessions = value
        if sessions < MIN_HORIZON or sessions > MAX_HORIZON:
            raise ValueError(f"Trading days must be between {MIN_HORIZON} and {MAX_HORIZON} sessions.")
        return sessions

    @staticmethod
    def parse_capital(raw: str | float | int) -> float:
        text = str(raw).replace("Rs.", "").replace("₹", "").replace(",", "").strip()
        try:
            capital = float(text)
        except ValueError as exc:
            raise ValueError("Investment amount must be a number.") from exc
        if capital <= 0:
            raise ValueError("Investment amount must be greater than zero.")
        return capital

    @staticmethod
    def parse_target(raw: str | float | int | None) -> float | None:
        if raw is None or str(raw).strip() == "":
            return None
        text = str(raw).replace("%", "").strip()
        try:
            target = float(text) / 100.0
        except ValueError as exc:
            raise ValueError("Desired return must be a percentage number.") from exc
        if target <= 0:
            raise ValueError("Desired return must be positive when supplied.")
        return target

    def get_latest_run(self) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM prediction_runs ORDER BY id DESC LIMIT 1").fetchone()
            if row is None:
                return None
            rows = conn.execute("SELECT * FROM prediction_candidates WHERE run_id=? ORDER BY rank", (row["run_id"],)).fetchall()
        return {"run": dict(row), "candidates": [dict(r) for r in rows]}

    def get_history(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT run_id, created_at, market_session, capital, horizon_sessions, target_return, status, summary_json FROM prediction_runs ORDER BY id DESC")]

    def run_prediction(self, request: PredictionRequest, progress=None) -> PredictionRun:
        for message in [
            "Preparing historical features...",
            "Evaluating historical evidence...",
            "Running prediction model...",
            "Ranking opportunities...",
        ]:
            if progress:
                progress(message)
        histories = self._load_histories()
        if not histories:
            raise RuntimeError("No official historical market data was found.")
        latest_session = max(bars[-1].date for bars in histories.values() if bars)
        v1_latest = self.v1_adapter.get_latest_result() or {}
        v1_symbols = {r.symbol for r in self.v1_adapter.map_recommendations(v1_latest)}
        candidates: list[CandidatePrediction] = []
        insufficient = 0
        for symbol in sorted(histories):
            prediction = self._predict_symbol(symbol, histories[symbol], request, v1_symbols)
            if prediction is None:
                insufficient += 1
                continue
            candidates.append(prediction)
        candidates.sort(key=lambda c: (-c.ranking_score, c.symbol))
        ranked = [CandidatePrediction(**{**asdict(c), "rank": i}) for i, c in enumerate(candidates, start=1)]
        summary = self._build_summary(histories, ranked, request, latest_session, insufficient)
        run = PredictionRun(
            run_id=f"leg2-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}",
            market_session=latest_session,
            capital=request.capital,
            horizon_sessions=request.horizon_sessions,
            target_return=request.target_return,
            engine_version=ENGINE_VERSION,
            model_version=MODEL_VERSION,
            feature_contract_version=FEATURE_VERSION,
            training_cutoff=latest_session,
            validation_contract=VALIDATION_CONTRACT,
            status="COMPLETE" if ranked else "NO_ELIGIBLE_CANDIDATES",
            candidates=ranked,
            summary=summary,
        )
        if progress:
            progress("Saving results...")
        self.persist_run(run)
        if progress:
            progress("Complete.")
        return run

    def persist_run(self, run: PredictionRun) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO prediction_runs(run_id, market_session, capital, horizon_sessions, target_return,
                    engine_version, model_version, feature_contract_version, training_cutoff, validation_contract,
                    status, survivorship_limited, progress_log_json, request_json, summary_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id, run.market_session, run.capital, run.horizon_sessions, run.target_return,
                    run.engine_version, run.model_version, run.feature_contract_version, run.training_cutoff,
                    run.validation_contract, run.status, 1, json.dumps([]),
                    json.dumps({"capital": run.capital, "horizon_sessions": run.horizon_sessions, "target_return": run.target_return}, sort_keys=True),
                    json.dumps(run.summary, sort_keys=True, default=str),
                ),
            )
            for c in run.candidates:
                conn.execute(
                    """
                    INSERT INTO prediction_candidates(run_id, rank, symbol, latest_close, affordable_qty,
                        profit_probability, target_probability, expected_return, median_return, downside_risk,
                        max_adverse_excursion, max_favorable_excursion, sample_size, confidence_label,
                        ranking_score, v1_status, opportunity_status, evidence_json, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.run_id, c.rank, c.symbol, c.latest_close, c.affordable_qty, c.profit_probability,
                        c.target_probability, c.expected_return, c.median_return, c.downside_risk,
                        c.max_adverse_excursion, c.max_favorable_excursion, c.sample_size, c.confidence_label,
                        c.ranking_score, c.v1_status, c.opportunity_status, json.dumps(c.evidence, sort_keys=True, default=str),
                        json.dumps(c.raw, sort_keys=True, default=str),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO prediction_evidence_summary(run_id, symbol, similar_situations, positive_terminal_count,
                        target_hit_count, median_return, worst_quartile, best_quartile, limitations)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.run_id, c.symbol, c.sample_size, int((c.profit_probability or 0) * c.sample_size),
                        None if c.target_probability is None else int(c.target_probability * c.sample_size),
                        c.median_return, c.evidence.get("worst_quartile"), c.evidence.get("best_quartile"),
                        "; ".join(c.evidence.get("limitations", [])),
                    ),
                )

    @guarded(lambda self: self.cache_roots)
    def _load_histories(self) -> dict[str, list[MarketBar]]:
        histories: dict[str, list[MarketBar]] = {}
        seen = set()
        for root in self.cache_roots:
            if not root.exists():
                continue
            for path in sorted(root.glob("*.csv")):
                raw_stem = path.stem.upper()
                symbol = raw_stem.replace(".NS", "").replace(".BO", "")
                if raw_stem.startswith("INDEX_") or symbol.startswith("INDEX_") or symbol in {"NSEI", "NIFTY", "NIFTY50", "NIFTY_50"}:
                    continue
                if symbol in seen:
                    continue
                bars = self._read_bars(path)
                if bars:
                    histories[symbol] = bars
                    seen.add(symbol)
        return histories

    @staticmethod
    @guarded(lambda path: [Path(path).parent])
    def _read_bars(path: Path) -> list[MarketBar]:
        rows: list[MarketBar] = []
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                try:
                    rows.append(MarketBar(row["Date"], float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"]), float(row.get("Volume") or 0)))
                except (KeyError, TypeError, ValueError):
                    continue
        return sorted(rows, key=lambda b: b.date)

    def _predict_symbol(self, symbol: str, bars: list[MarketBar], request: PredictionRequest, v1_symbols: set[str]) -> CandidatePrediction | None:
        latest_index = len(bars) - 1
        if latest_index < MIN_WARMUP + request.horizon_sessions + 1:
            return None
        current_features = self._features_at(bars, latest_index)
        if current_features is None:
            return None
        outcomes = []
        first_train = MIN_WARMUP
        last_train = latest_index - request.horizon_sessions - 1
        for i in range(first_train, last_train + 1):
            features = self._features_at(bars, i)
            outcome = self._outcome_after(bars, i, request.horizon_sessions, request.target_return)
            if features and outcome:
                outcomes.append((self._distance(current_features, features), features, outcome))
        if len(outcomes) < MIN_ANALOGUES:
            return None
        outcomes.sort(key=lambda row: row[0])
        analogues = outcomes[: min(MAX_ANALOGUES, len(outcomes))]
        terminal_returns = [row[2]["terminal_return"] for row in analogues]
        profit_probability = sum(1 for r in terminal_returns if r > 0) / len(terminal_returns)
        target_probability = None
        if request.target_return is not None:
            target_probability = sum(1 for row in analogues if row[2]["target_hit"]) / len(analogues)
        expected = statistics.fmean(terminal_returns)
        median = statistics.median(terminal_returns)
        downside = statistics.fmean([abs(min(0.0, r)) for r in terminal_returns])
        mae = statistics.fmean(row[2]["max_adverse_excursion"] for row in analogues)
        mfe = statistics.fmean(row[2]["max_favorable_excursion"] for row in analogues)
        confidence = self._confidence(len(analogues), analogues[0][0], profit_probability)
        ranking_score = expected + (profit_probability - 0.5) * 0.08 - downside * 0.35
        if target_probability is not None:
            ranking_score += (target_probability - 0.5) * 0.04
        opportunity_status = self._opportunity_status(ranking_score, confidence)
        latest_close = bars[-1].close
        evidence = {
            "similar_situations": len(analogues),
            "positive_terminal_outcomes": sum(1 for r in terminal_returns if r > 0),
            "target_hits": None if target_probability is None else sum(1 for row in analogues if row[2]["target_hit"]),
            "worst_quartile": self._quantile(terminal_returns, 0.25),
            "best_quartile": self._quantile(terminal_returns, 0.75),
            "nearest_similarity_distance": analogues[0][0],
            "positive_evidence": self._positive_evidence(current_features),
            "negative_evidence": self._negative_evidence(current_features),
            "limitations": ["Uses today's current safe universe retrospectively; survivorship limitation applies."],
        }
        raw = {
            "current_features": current_features,
            "model_family": "historical_analogue_nearest_state",
            "entry_reference": "T+1 official open",
            "target_hit_uses_intraday_high": request.target_return is not None,
            "feature_hash": self._hash(current_features),
        }
        return CandidatePrediction(
            rank=0,
            symbol=symbol,
            latest_close=latest_close,
            affordable_qty=int(request.capital // latest_close) if latest_close > 0 else 0,
            profit_probability=profit_probability,
            target_probability=target_probability,
            expected_return=expected,
            median_return=median,
            downside_risk=downside,
            max_adverse_excursion=mae,
            max_favorable_excursion=mfe,
            sample_size=len(analogues),
            confidence_label=confidence,
            ranking_score=ranking_score,
            v1_status="V1 RECOMMENDED" if symbol in v1_symbols else "V1 VALID ZERO / NOT SELECTED",
            opportunity_status=opportunity_status,
            evidence=evidence,
            raw=raw,
        )

    @staticmethod
    def _features_at(bars: list[MarketBar], i: int) -> dict[str, float] | None:
        if i < MIN_WARMUP:
            return None
        close = bars[i].close
        if close <= 0:
            return None
        closes = [b.close for b in bars]
        vols = [b.volume for b in bars]
        def ret(n: int) -> float:
            return close / closes[i - n] - 1.0 if closes[i - n] else 0.0
        def sma(n: int) -> float:
            return statistics.fmean(closes[i - n + 1 : i + 1])
        recent20 = closes[i - 19 : i + 1]
        recent60 = closes[i - 59 : i + 1]
        recent120 = closes[i - 119 : i + 1]
        day_returns = [(closes[j] / closes[j - 1] - 1.0) for j in range(i - 59, i + 1) if closes[j - 1]]
        vol20 = statistics.pstdev(day_returns[-20:]) if len(day_returns) >= 20 else 0.0
        vol60 = statistics.pstdev(day_returns) if len(day_returns) >= 2 else 0.0
        losses = [r for r in day_returns[-40:] if r < 0]
        downside_vol = statistics.pstdev(losses) if len(losses) >= 2 else 0.0
        avg_vol20 = statistics.fmean(vols[i - 19 : i + 1]) or 1.0
        avg_vol60 = statistics.fmean(vols[i - 59 : i + 1]) or 1.0
        gains = [max(0.0, closes[j] - closes[j - 1]) for j in range(i - 13, i + 1)]
        declines = [max(0.0, closes[j - 1] - closes[j]) for j in range(i - 13, i + 1)]
        rs = (statistics.fmean(gains) / statistics.fmean(declines)) if statistics.fmean(declines) else 100.0
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return {
            "ret_1d": ret(1),
            "ret_5d": ret(5),
            "ret_20d": ret(20),
            "ret_60d": ret(60),
            "ret_120d": ret(120),
            "momentum_accel": ret(20) - ret(60),
            "volatility_20d": vol20,
            "volatility_60d": vol60,
            "downside_volatility": downside_vol,
            "sma20_distance": close / sma(20) - 1.0,
            "sma60_distance": close / sma(60) - 1.0,
            "sma120_distance": close / sma(120) - 1.0,
            "distance_20d_high": close / max(recent20) - 1.0,
            "distance_60d_high": close / max(recent60) - 1.0,
            "distance_120d_high": close / max(recent120) - 1.0,
            "drawdown_120d": close / max(recent120) - 1.0,
            "volume_ratio_20_60": avg_vol20 / avg_vol60 - 1.0,
            "intraday_return": close / bars[i].open - 1.0 if bars[i].open else 0.0,
            "range_pct": (bars[i].high - bars[i].low) / close if close else 0.0,
            "rsi14": rsi / 100.0,
        }

    @staticmethod
    def _outcome_after(bars: list[MarketBar], i: int, horizon: int, target: float | None) -> dict[str, Any] | None:
        entry_index = i + 1
        exit_index = i + horizon
        if exit_index >= len(bars):
            return None
        entry = bars[entry_index].open
        if entry <= 0:
            return None
        window = bars[entry_index : exit_index + 1]
        terminal_return = bars[exit_index].close / entry - 1.0
        max_adverse = min(b.low / entry - 1.0 for b in window)
        max_favorable = max(b.high / entry - 1.0 for b in window)
        return {
            "entry_date": bars[entry_index].date,
            "exit_date": bars[exit_index].date,
            "terminal_return": terminal_return,
            "target_hit": None if target is None else any((b.high / entry - 1.0) >= target for b in window),
            "max_adverse_excursion": max_adverse,
            "max_favorable_excursion": max_favorable,
        }

    @staticmethod
    def _distance(a: dict[str, float], b: dict[str, float]) -> float:
        total = 0.0
        for key in a:
            scale = 0.05 if "ret" in key or "distance" in key or "volatility" in key or "drawdown" in key else 0.2
            total += ((a[key] - b[key]) / scale) ** 2
        return math.sqrt(total / len(a))

    @staticmethod
    def _confidence(sample_size: int, nearest_distance: float, profit_probability: float) -> str:
        if sample_size < MIN_ANALOGUES:
            return "INSUFFICIENT"
        if sample_size >= 120 and nearest_distance < 2.5 and abs(profit_probability - 0.5) >= 0.08:
            return "HIGH"
        if sample_size >= 70 and nearest_distance < 4.0:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _opportunity_status(score: float, confidence: str) -> str:
        if confidence in {"HIGH", "MEDIUM"} and score >= 0.025:
            return "STRONG CANDIDATE"
        if confidence != "INSUFFICIENT" and score >= 0.01:
            return "MODERATE CANDIDATE"
        if confidence == "INSUFFICIENT":
            return "INSUFFICIENT HISTORY"
        if score >= 0:
            return "WEAK / WATCH"
        return "NO STRONG EDGE"

    @staticmethod
    def _quantile(values: list[float], q: float) -> float:
        ordered = sorted(values)
        if not ordered:
            return 0.0
        idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
        return ordered[idx]

    @staticmethod
    def _positive_evidence(features: dict[str, float]) -> list[str]:
        evidence = []
        if features["ret_20d"] > 0:
            evidence.append("Positive 20-session momentum")
        if features["sma60_distance"] > 0:
            evidence.append("Close is above 60-session average")
        if features["distance_60d_high"] > -0.03:
            evidence.append("Near recent 60-session high")
        return evidence or ["Best available historical analogue rank"]

    @staticmethod
    def _negative_evidence(features: dict[str, float]) -> list[str]:
        evidence = []
        if features["volatility_20d"] > features["volatility_60d"] * 1.2:
            evidence.append("Recent volatility is elevated")
        if features["drawdown_120d"] < -0.12:
            evidence.append("Still in a material 120-session drawdown")
        if features["ret_5d"] < -0.03:
            evidence.append("Short-term pullback is active")
        return evidence or ["No dominant negative technical flag in selected features"]

    @staticmethod
    def _hash(payload: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]

    def _build_summary(self, histories: dict[str, list[MarketBar]], candidates: list[CandidatePrediction], request: PredictionRequest, latest_session: str, insufficient: int) -> dict[str, Any]:
        eligible = len(candidates)
        top = candidates[:10]
        return {
            "market_session": latest_session,
            "available_symbols": len(histories),
            "eligible_symbols": eligible,
            "insufficient_history_symbols": insufficient,
            "warmup_requirement_sessions": MIN_WARMUP,
            "horizon_support": [MIN_HORIZON, MAX_HORIZON],
            "months_to_sessions": MONTH_TO_SESSIONS,
            "method": MODEL_VERSION,
            "baseline": "Universe median and simple momentum rank reported in output artifacts.",
            "final_holdout": "Most recent chronological period is reserved in validation contract; runtime predictions train only from dates before current T.",
            "top1_profit_probability": top[0].profit_probability if top else None,
            "top3_median_expected_return": statistics.median([c.expected_return for c in top[:3] if c.expected_return is not None]) if top else None,
            "top5_median_expected_return": statistics.median([c.expected_return for c in top[:5] if c.expected_return is not None]) if top else None,
            "target_return": request.target_return,
            "survivorship_limitation": "Historical study uses today's current safe operational universe retrospectively.",
        }
