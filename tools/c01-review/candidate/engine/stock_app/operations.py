from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from . import APP_NAME, APP_VERSION
from .config import AppConfig
from .storage import AppDatabase

LEG8_RUNTIME_POLICY_VERSION = "LEG8_PRODUCTION_HARDENING_POLICY_V1"
LOCK_STALE_AFTER_SECONDS = 6 * 60 * 60
DEFAULT_BACKUP_RETENTION = 10
MIN_FREE_DISK_BYTES = 500 * 1024 * 1024


@dataclass(frozen=True)
class HealthCheck:
    name: str
    status: str
    detail: str
    critical: bool = False


class OperationLockedError(RuntimeError):
    pass


class OperationLock:
    """Portable file lock for one-at-a-time operational workflows.

    The lock is intentionally simple: exclusive file creation is atomic on the local
    filesystem. Stale locks are cleared only after a conservative age threshold.
    """

    def __init__(self, path: Path, stale_after_seconds: int = LOCK_STALE_AFTER_SECONDS):
        self.path = path
        self.stale_after_seconds = stale_after_seconds
        self._acquired = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            age = max(0.0, time.time() - self.path.stat().st_mtime)
            if age > self.stale_after_seconds:
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
            else:
                detail = self.path.read_text(encoding="utf-8", errors="replace")[:1000]
                raise OperationLockedError(f"Operation already running. Lock: {self.path}. {detail}")
        payload = {
            "pid": os.getpid(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "app_version": APP_VERSION,
        }
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(self.path, flags)
        except FileExistsError as exc:
            raise OperationLockedError(f"Operation already running. Lock: {self.path}") from exc
        try:
            os.write(fd, json.dumps(payload, sort_keys=True).encode("utf-8"))
        finally:
            os.close(fd)
        self._acquired = True

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        self._acquired = False

    def __enter__(self) -> "OperationLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class ProductionHardeningService:
    def __init__(self, config: AppConfig, db: AppDatabase):
        self.config = config
        self.db = db
        self.backup_dir = config.app_data_dir / "backups"
        self.support_dir = config.app_data_dir / "support"
        self.lock_dir = config.app_data_dir / "locks"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.support_dir.mkdir(parents=True, exist_ok=True)
        self.lock_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def operation_lock(self, name: str) -> Iterator[None]:
        safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)
        with OperationLock(self.lock_dir / f"{safe_name}.lock"):
            yield

    def health_report(self) -> dict[str, Any]:
        checks: list[HealthCheck] = []
        root = self.config.repo_root

        self._path_check(checks, "official_daily_runner", root / "run_official_v1_daily.py", critical=True)
        self._path_check(checks, "stage_2_2_2_final", root / "Stage 2.2.2 Final", critical=True)
        self._path_check(checks, "stage_3", root / "Stage 3", critical=True)
        self._path_check(checks, "stage_4a3", root / "Stage 4A.3", critical=True)
        self._path_check(checks, "data_tree", root / "data", critical=True)
        self._path_check(checks, "outputs_tree", root / "outputs", critical=True)

        recovery = root / "outputs" / "Leg5_Official_Source_Access_Recovery" / "NSE_15Y_NORMALIZED_QUARTERLY.csv"
        if recovery.exists():
            row_count, symbol_count = self._fundamental_recovery_shape(recovery)
            status = "PASS" if row_count >= 300 and symbol_count >= 50 else "WARN"
            checks.append(HealthCheck("leg5_pit_recovery", status, f"{row_count} rows / {symbol_count} symbols at {recovery}", critical=status != "PASS"))
        else:
            checks.append(HealthCheck("leg5_pit_recovery", "FAIL", f"Missing: {recovery}", critical=True))

        integrity = self.db.integrity_report()
        db_ok = integrity["integrity_check"] == "ok" and not integrity["foreign_key_violations"]
        checks.append(HealthCheck("database_integrity", "PASS" if db_ok else "FAIL", json.dumps(integrity, sort_keys=True), critical=not db_ok))

        yfinance_calls = 0
        latest_session = None
        latest_status = None
        with self.db.connect() as conn:
            row = conn.execute("SELECT COALESCE(SUM(yfinance_calls),0) AS calls FROM analysis_runs").fetchone()
            yfinance_calls = int(row["calls"] if row else 0)
            latest = conn.execute("SELECT session_date, run_status FROM analysis_runs ORDER BY session_date DESC, id DESC LIMIT 1").fetchone()
            if latest:
                latest_session = latest["session_date"]
                latest_status = latest["run_status"]
        checks.append(HealthCheck("production_yfinance_calls", "PASS" if yfinance_calls == 0 else "FAIL", f"persisted calls={yfinance_calls}; automatic fallback must remain disabled", critical=yfinance_calls != 0))

        free_bytes = shutil.disk_usage(self.config.app_data_dir).free
        checks.append(HealthCheck("free_disk_space", "PASS" if free_bytes >= MIN_FREE_DISK_BYTES else "WARN", f"free_bytes={free_bytes}", critical=False))

        backup = self.latest_backup()
        if backup:
            age_hours = (time.time() - backup.stat().st_mtime) / 3600
            checks.append(HealthCheck("backup_available", "PASS" if age_hours <= 48 else "WARN", f"{backup.name}; age_hours={age_hours:.1f}", critical=False))
        else:
            checks.append(HealthCheck("backup_available", "WARN", "No verified application database backup yet.", critical=False))

        critical_failures = [c for c in checks if c.critical and c.status == "FAIL"]
        warnings = [c for c in checks if c.status == "WARN"]
        overall = "BLOCKED" if critical_failures else ("READY_WITH_WARNINGS" if warnings else "READY")
        payload = {
            "policy_version": LEG8_RUNTIME_POLICY_VERSION,
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "overall_status": overall,
            "critical_failure_count": len(critical_failures),
            "warning_count": len(warnings),
            "latest_analysis_session": latest_session,
            "latest_analysis_status": latest_status,
            "repo_root": str(root),
            "app_data_dir": str(self.config.app_data_dir),
            "database_path": str(self.config.database_path),
            "checks": [asdict(c) for c in checks],
        }
        payload["report_hash"] = self._hash(payload)
        return payload

    def assert_runtime_ready(self) -> dict[str, Any]:
        report = self.health_report()
        if report["overall_status"] == "BLOCKED":
            failures = [c for c in report["checks"] if c["critical"] and c["status"] == "FAIL"]
            summary = "; ".join(f"{c['name']}: {c['detail']}" for c in failures)
            raise RuntimeError(f"Leg 8 runtime preflight blocked: {summary}")
        return report

    def create_backup(self, reason: str = "manual", retention: int = DEFAULT_BACKUP_RETENTION) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        target = self.backup_dir / f"stock_recommendation_engine_{timestamp}.sqlite3"
        self.db.backup_to(target)
        # Validate the backup with an explicitly closed SQLite connection.  sqlite3.Connection
        # used as a context manager commits/rolls back, but it does NOT close the connection.
        # On Windows that can keep the backup file handle open and make immediate retention
        # pruning fail with WinError 32.  Close it before _prune_backups().
        backup_conn = sqlite3.connect(target, timeout=5.0)
        try:
            integrity_row = backup_conn.execute("PRAGMA integrity_check").fetchone()
            integrity = str(integrity_row[0] if integrity_row else "unknown")
            foreign_keys = [tuple(row) for row in backup_conn.execute("PRAGMA foreign_key_check").fetchall()]
        finally:
            backup_conn.close()
        check = {"integrity_check": integrity, "foreign_key_violations": foreign_keys}
        if check["integrity_check"] != "ok" or check["foreign_key_violations"]:
            target.unlink(missing_ok=True)
            raise RuntimeError(f"Backup validation failed: {check}")
        self._prune_backups(retention)
        self.db.record_event("LEG8_DATABASE_BACKUP", {"reason": reason, "path": str(target), "sha256": self._sha256_file(target)})
        return target

    def ensure_recent_backup(self, max_age_hours: float = 24.0) -> Path:
        latest = self.latest_backup()
        if latest is not None:
            age_hours = (time.time() - latest.stat().st_mtime) / 3600
            if age_hours <= max_age_hours:
                return latest
        return self.create_backup(reason="automatic_pre_operation")

    def latest_backup(self) -> Path | None:
        backups = sorted(self.backup_dir.glob("stock_recommendation_engine_*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True)
        return backups[0] if backups else None

    def create_support_bundle(self, include_log_tail_lines: int = 2000) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = self.support_dir / f"StockRecommendationEngine_Support_{timestamp}.zip"
        with tempfile.TemporaryDirectory(prefix="stock_app_support_") as tmp:
            temp_root = Path(tmp)
            health = self.health_report()
            (temp_root / "health_report.json").write_text(json.dumps(health, indent=2, sort_keys=True), encoding="utf-8")
            (temp_root / "database_summary.json").write_text(json.dumps(self._database_summary(), indent=2, sort_keys=True), encoding="utf-8")
            (temp_root / "runtime_manifest.json").write_text(json.dumps(self.runtime_manifest(), indent=2, sort_keys=True), encoding="utf-8")
            log_path = self.config.log_dir / "application.log"
            if log_path.exists():
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                (temp_root / "application_log_tail.txt").write_text("\n".join(lines[-include_log_tail_lines:]) + "\n", encoding="utf-8")
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for path in sorted(temp_root.iterdir()):
                    zf.write(path, arcname=path.name)
        self.db.record_event("LEG8_SUPPORT_BUNDLE_CREATED", {"path": str(destination), "sha256": self._sha256_file(destination)})
        return destination

    def runtime_manifest(self) -> dict[str, Any]:
        root = self.config.repo_root
        tracked = [
            root / "run_official_v1_daily.py",
            root / "outputs" / "Leg5_Official_Source_Access_Recovery" / "NSE_15Y_NORMALIZED_QUARTERLY.csv",
            root / "outputs" / "Leg6_Portfolio_Capital_Intelligence" / "LEG6_ALLOCATION_POLICY.json",
            root / "outputs" / "Leg7_Advanced_Daily_Monitoring" / "LEG7_REPLACEMENT_POLICY.json",
        ]
        files: list[dict[str, Any]] = []
        for path in tracked:
            files.append({
                "path": str(path),
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.exists() and path.is_file() else None,
                "sha256": self._sha256_file(path) if path.exists() and path.is_file() else None,
            })
        payload = {
            "policy_version": LEG8_RUNTIME_POLICY_VERSION,
            "app_version": APP_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "files": files,
        }
        payload["manifest_hash"] = self._hash(payload)
        return payload

    def _database_summary(self) -> dict[str, Any]:
        tables = [
            "portfolio_positions",
            "analysis_runs",
            "prediction_runs",
            "prediction_candidates",
            "recommendation_lifecycle",
            "daily_position_assessments",
            "leg7_daily_monitoring",
            "app_events",
        ]
        counts: dict[str, int | None] = {}
        with self.db.connect() as conn:
            for table in tables:
                try:
                    row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
                    counts[table] = int(row["n"] if row else 0)
                except sqlite3.Error:
                    counts[table] = None
            metadata = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM app_metadata ORDER BY key")}
            events = [dict(r) for r in conn.execute("SELECT event_type, created_at FROM app_events ORDER BY id DESC LIMIT 100")]
        return {"counts": counts, "metadata": metadata, "recent_event_headers": events}

    @staticmethod
    def _path_check(checks: list[HealthCheck], name: str, path: Path, critical: bool) -> None:
        checks.append(HealthCheck(name, "PASS" if path.exists() else "FAIL", ("Present: " if path.exists() else "Missing: ") + str(path), critical=critical))

    @staticmethod
    def _fundamental_recovery_shape(path: Path) -> tuple[int, int]:
        rows = 0
        symbols: set[str] = set()
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                rows += 1
                symbol = str(row.get("symbol") or "").strip().upper()
                if symbol:
                    symbols.add(symbol)
        return rows, len(symbols)

    def _prune_backups(self, retention: int) -> None:
        if retention < 1:
            retention = 1
        # Backup filenames contain YYYYMMDD_HHMMSS_microseconds, so lexical ordering is
        # deterministic even when Windows reports identical filesystem mtime values.
        backups = sorted(
            self.backup_dir.glob("stock_recommendation_engine_*.sqlite3"),
            key=lambda p: p.name,
            reverse=True,
        )
        for old in backups[retention:]:
            # Windows can briefly retain a handle after SQLite/AV/indexer access.  Retry a
            # small bounded number of times rather than failing an otherwise valid backup.
            last_error: PermissionError | None = None
            for attempt in range(8):
                try:
                    old.unlink(missing_ok=True)
                    last_error = None
                    break
                except PermissionError as exc:
                    last_error = exc
                    time.sleep(0.05 * (attempt + 1))
            if last_error is not None:
                raise RuntimeError(
                    f"Backup retention could not remove locked file after retries: {old}"
                ) from last_error

    @staticmethod
    def _hash(payload: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
