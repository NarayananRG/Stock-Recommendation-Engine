from __future__ import annotations

import importlib.util
import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .operations import OperationLock
from .storage import AppDatabase

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecommendationViewModel:
    symbol: str
    recommendation_date: str
    engine: str
    engine_version: str
    score: float | None = None
    confidence: float | None = None
    expected_return: float | None = None
    target_probability: float | None = None
    downside_probability: float | None = None
    target_return: float | None = None
    holding_period: str | None = None
    action: str | None = None
    reasoning: str | None = None
    status: str = "NOT AVAILABLE IN V1"
    raw: dict[str, Any] | None = None


class EngineAdapter(Protocol):
    def get_status(self) -> dict[str, Any]: ...
    def run_analysis(self) -> dict[str, Any]: ...
    def get_latest_result(self) -> dict[str, Any] | None: ...
    def get_history(self) -> list[dict[str, Any]]: ...


class OfficialV1Adapter:
    def __init__(self, repo_root: Path, db: AppDatabase):
        self.repo_root = repo_root
        self.db = db
        self.run_dir = repo_root / "outputs" / "Official_V1_Daily_Runner_EndToEnd_Closure" / "daily_runs"
        self.runner = repo_root / "run_official_v1_daily.py"

    def get_status(self) -> dict[str, Any]:
        latest = self.get_latest_result()
        return {
            "engine": "Official V1",
            "runner_exists": self.runner.exists(),
            "latest_session": latest.get("target_session") if latest else None,
            "latest_status": latest.get("final_execution_status") if latest else "NO_RESULT",
            "yfinance_allowed": False,
        }

    def run_analysis(self, use_lock: bool = True) -> dict[str, Any]:
        if use_lock:
            lock_path = self.db.path.parent / "locks" / "official_v1_analysis.lock"
            with OperationLock(lock_path):
                return self._run_analysis_unlocked()
        return self._run_analysis_unlocked()

    def _run_analysis_unlocked(self) -> dict[str, Any]:
        # In a PyInstaller build sys.executable is StockRecommendationEngine.exe.
        # Launching [sys.executable, run_official_v1_daily.py, --latest] therefore
        # starts a second GUI instead of Python. Execute the bundled runner in-process
        # when frozen; keep subprocess isolation for normal source/development runs.
        if getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS"):
            return self._run_analysis_frozen_in_process()

        command = [sys.executable, str(self.runner), "--latest"]
        LOG.info("analysis start command=%s", command)
        completed = subprocess.run(command, cwd=self.repo_root, text=True, capture_output=True, timeout=3600)
        LOG.info("analysis exit code=%s", completed.returncode)
        if completed.returncode != 0:
            # Exit 10 is the runner's documented WAITING_FOR_OFFICIAL_EOD outcome.
            if completed.returncode == 10:
                result = {
                    "final_execution_status": "WAITING_FOR_OFFICIAL_EOD",
                    "errors": [],
                    "target_session": None,
                    "yfinance_calls": 0,
                }
                self.persist_result(result)
                return result
            result = {"final_execution_status": "RUN_FAILED", "errors": [completed.stderr[-2000:] or completed.stdout[-2000:]]}
            self.persist_result(result)
            return result
        latest = self.get_latest_result()
        if latest is None:
            result = {"final_execution_status": "RUN_FAILED", "errors": ["Runner completed but no daily result was found."]}
            self.persist_result(result)
            return result
        self.persist_result(latest)
        return latest

    def _run_analysis_frozen_in_process(self) -> dict[str, Any]:
        if not self.runner.exists():
            result = {"final_execution_status": "RUN_FAILED", "errors": [f"Bundled runner missing: {self.runner}"]}
            self.persist_result(result)
            return result

        LOG.info("frozen analysis: loading bundled runner in-process path=%s", self.runner)
        module_name = "stock_recommendation_engine_official_v1_runner"
        spec = importlib.util.spec_from_file_location(module_name, self.runner)
        if spec is None or spec.loader is None:
            result = {"final_execution_status": "RUN_FAILED", "errors": [f"Could not load bundled runner: {self.runner}"]}
            self.persist_result(result)
            return result

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            session = module.latest_common_local_session()
            if session is None:
                result = {
                    "final_execution_status": "WAITING_FOR_OFFICIAL_EOD",
                    "errors": [],
                    "target_session": None,
                    "yfinance_calls": 0,
                }
            else:
                result = module.evaluate_session(session)
                code = module.exit_code_for(result)
                if result.get("final_execution_status") != "WAITING_FOR_OFFICIAL_EOD" and "errors" not in result:
                    module.write_daily_report(result)
                log_path = module.write_log(result, code)
                result["operational_log"] = str(log_path)
        except Exception as exc:
            LOG.exception("frozen in-process official V1 runner failed")
            result = {"final_execution_status": "RUN_FAILED", "errors": [repr(exc)]}
        finally:
            sys.modules.pop(module_name, None)

        self.persist_result(result)
        return result

    def get_latest_result(self) -> dict[str, Any] | None:
        files = sorted(self.run_dir.glob("*.json"))
        if not files:
            return None
        return json.loads(files[-1].read_text(encoding="utf-8"))

    def get_history(self) -> list[dict[str, Any]]:
        history = []
        for path in sorted(self.run_dir.glob("*.json"), reverse=True):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                history.append(self.summarize_result(payload))
            except Exception as exc:  # keep history screen resilient
                history.append({"session_date": path.stem, "run_status": "DATA_ERROR", "error": repr(exc)})
        return history

    def persist_result(self, result: dict[str, Any]) -> int:
        summary = self.summarize_result(result)
        session = summary["session_date"]
        with self.db.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO analysis_runs(session_date, run_status, official_stock_status, official_benchmark_status,
                    cohort001_count, cohort002_count, yfinance_calls, result_classification, result_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_date) DO UPDATE SET
                    run_status=excluded.run_status,
                    official_stock_status=excluded.official_stock_status,
                    official_benchmark_status=excluded.official_benchmark_status,
                    cohort001_count=excluded.cohort001_count,
                    cohort002_count=excluded.cohort002_count,
                    yfinance_calls=excluded.yfinance_calls,
                    result_classification=excluded.result_classification,
                    result_json=excluded.result_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    session,
                    summary["run_status"],
                    summary["official_stock_status"],
                    summary["official_benchmark_status"],
                    summary["cohort001_count"],
                    summary["cohort002_count"],
                    summary["yfinance_calls"],
                    summary["result_classification"],
                    json.dumps(result, sort_keys=True, default=str),
                ),
            )
            run_id = int(cur.lastrowid or conn.execute("SELECT id FROM analysis_runs WHERE session_date=?", (session,)).fetchone()[0])
            conn.execute("DELETE FROM recommendation_snapshots WHERE analysis_run_id=?", (run_id,))
            for vm in self.map_recommendations(result):
                conn.execute(
                    """
                    INSERT INTO recommendation_snapshots(analysis_run_id, symbol, recommendation_date, engine, engine_version,
                        score, confidence, expected_return, target_probability, downside_probability, target_return,
                        holding_period, action, reasoning, status, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id, vm.symbol, vm.recommendation_date, vm.engine, vm.engine_version, vm.score, vm.confidence,
                        vm.expected_return, vm.target_probability, vm.downside_probability, vm.target_return,
                        vm.holding_period, vm.action, vm.reasoning, vm.status, json.dumps(vm.raw or {}, sort_keys=True),
                    ),
                )
        return run_id

    @staticmethod
    def summarize_result(result: dict[str, Any]) -> dict[str, Any]:
        finality = result.get("official_eod_finality", {})
        status = result.get("final_execution_status") or result.get("error") or "UNKNOWN"
        c1 = int(result.get("cohort001_recommendation_count") or 0)
        c2 = int(result.get("cohort002_recommendation_count") or 0)
        if status == "WAITING_FOR_OFFICIAL_EOD" or result.get("error") == "WAITING_FOR_OFFICIAL_EOD":
            classification = "WAITING_FOR_OFFICIAL_EOD"
        elif c1 == 0 and c2 == 0 and "COMPLETE" in status:
            classification = "VALID_ZERO_SESSION"
        elif c1 or c2:
            classification = "RECOMMENDATIONS_AVAILABLE"
        elif "FAIL" in status or "ERROR" in status:
            classification = "RUN_FAILED"
        else:
            classification = status
        return {
            "session_date": result.get("target_session") or result.get("selected_session") or "UNKNOWN",
            "run_status": status,
            "official_stock_status": result.get("official_acquisition", {}).get("stock", {}).get("acquisition_status")
            or str(finality.get("official_stock_eod_available")),
            "official_benchmark_status": result.get("official_acquisition", {}).get("benchmark", {}).get("acquisition_status")
            or str(finality.get("official_nifty50_eod_available")),
            "cohort001_count": c1,
            "cohort002_count": c2,
            "yfinance_calls": int(result.get("yfinance_calls") or result.get("fallback_policy", {}).get("yfinance_calls") or 0),
            "result_classification": classification,
        }

    @staticmethod
    def map_recommendations(result: dict[str, Any]) -> list[RecommendationViewModel]:
        rows: list[RecommendationViewModel] = []
        session = str(result.get("target_session") or "")
        for key, engine in [("cohort001", "Official V1 Cohort001"), ("cohort002", "Official V1 Cohort002")]:
            for rec in result.get(f"{key}_recommendations", []) or []:
                rows.append(
                    RecommendationViewModel(
                        symbol=str(rec.get("symbol") or ""),
                        recommendation_date=session,
                        engine=engine,
                        engine_version="Official V1",
                        score=rec.get("r3_score"),
                        action=rec.get("signal") or "NOT AVAILABLE IN V1",
                        status="RECOMMENDATIONS_AVAILABLE",
                        raw=rec,
                    )
                )
        return rows
