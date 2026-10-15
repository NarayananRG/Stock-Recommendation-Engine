from pathlib import Path
import os
import shutil


root = Path(os.environ["SRE_ENGINE_ROOT"])
here = Path(__file__).resolve().parent


def replace_between(text: str, start_marker: str, end_marker: str, replacement: str, label: str) -> str:
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"{label} start marker missing")
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(f"{label} end marker missing")
    return text[:start] + replacement + text[end:]


shutil.copy2(here / "official_daily_refresh_v3.py", root / "stock_app" / "official_daily_refresh.py")

api = root / "modern_ui" / "api.py"
s = api.read_text(encoding="utf-8")
s = s.replace(
    'APP_VERSION = "0.14.5-runtime-interaction-bootstrap"',
    'APP_VERSION = "0.14.6-official-data-refresh-repair"',
    1,
)

session_block = '''    @staticmethod
    def _nse_holidays() -> set[str]:
        # NSE capital-market holidays for calendar 2026, published by NSE.
        return {
            "2026-01-15", "2026-01-26", "2026-02-19", "2026-03-03",
            "2026-03-19", "2026-03-26", "2026-03-31", "2026-04-01",
            "2026-04-03", "2026-04-14", "2026-05-01", "2026-05-28",
            "2026-06-26", "2026-08-26", "2026-09-14", "2026-10-02",
            "2026-10-20", "2026-11-08", "2026-11-10", "2026-11-24",
            "2026-12-25",
        }

    @classmethod
    def _is_nse_trading_day(cls, day) -> bool:
        return day.weekday() < 5 and day.isoformat() not in cls._nse_holidays()

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

'''
s = replace_between(
    s,
    "    @staticmethod\n    def _nse_holidays()",
    "    def _refresh_official_first_market_data",
    session_block,
    "expected session resolver",
)

gate_block = '''    def _daily_data_gate(self) -> dict[str, Any]:
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

'''
s = replace_between(s, "    def _daily_data_gate", "    def post_close_daily_status", gate_block, "daily data gate")
s = s.replace('elif refresh_status == "OFFICIAL_NOT_READY":\n            refresh_label = "NOT READY"', 'elif refresh_status == "OFFICIAL_NOT_READY":\n            refresh_label = "NOT YET PUBLISHED"', 1)
s = s.replace(
    'elif refresh_status:\n            refresh_label = "FAILED"',
    'elif refresh_status in {"OFFICIAL_DOWNLOAD_FAILED", "OFFICIAL_INDEX_FAILED"}:\n            refresh_label = "DOWNLOAD ERROR"\n        elif refresh_status == "OFFICIAL_SCHEMA_ERROR":\n            refresh_label = "PARSE ERROR"\n        elif refresh_status == "OFFICIAL_COVERAGE_FAILED":\n            refresh_label = "COVERAGE ERROR"\n        elif refresh_status in {"LOCAL_VERIFICATION_FAILED", "LOCAL_PERSISTENCE_FAILED"}:\n            refresh_label = "LOCAL VERIFICATION ERROR"\n        elif refresh_status:\n            refresh_label = "FAILED"',
    1,
)
s = s.replace(
    '"run_status": "READY" if gate["ready"] else ("BLOCKED - OFFICIAL SOURCE ERROR" if gate.get("blocked_reason") == "OFFICIAL_SOURCE_ERROR" else "BLOCKED - OFFICIAL DATA NOT READY"),',
    '"run_status": "READY" if gate["ready"] else f"BLOCKED - {gate.get(\'data_freshness\') or \'OFFICIAL DATA NOT READY\'}",',
    1,
)
api.write_text(s, encoding="utf-8")

policy = root / "phase7" / "official_data_refresh_repair_0146.json"
policy.write_text('''{
  "schema": "SRE_OFFICIAL_DATA_REFRESH_REPAIR_0146",
  "release": "0.14.6-official-data-refresh-repair",
  "official_publication_window_ist": "18:00",
  "official_source_hierarchy": ["NSE_INDEX_DAILY_CLOSE_REPORT", "NSE_INDEX_HISTORICAL_API"],
  "full_universe_reread": true,
  "transactional_rollback": true,
  "automatic_yfinance_fallback": false,
  "production_recommendation_authority_changed": false,
  "model_or_threshold_changed": false
}
''', encoding="utf-8")

assert 'APP_VERSION = "0.14.6-official-data-refresh-repair"' in api.read_text(encoding="utf-8")
assert "TRADING_DAY_BEFORE_OFFICIAL_PUBLICATION_WINDOW" in api.read_text(encoding="utf-8")
assert "NOT YET PUBLISHED" in api.read_text(encoding="utf-8")
assert "automatic_yfinance_fallback" in (root / "stock_app" / "official_daily_refresh.py").read_text(encoding="utf-8")
print("0.14.6 official data refresh repair applied")
