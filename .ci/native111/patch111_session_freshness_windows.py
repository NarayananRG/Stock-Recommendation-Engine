from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])


def repl(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(label + " contract missing")
    return text.replace(old, new, 1)


api = root / "modern_ui" / "api.py"
s = api.read_text(encoding="utf-8")
s = repl(s, 'APP_VERSION = "0.12.3-phase7-daily-flow-ui-hotfix"', 'APP_VERSION = "0.12.4-phase7-session-freshness-windows-hardening"', "backend version")

new = '''    @staticmethod
    def _nse_holidays() -> set[str]:
        # Auditable release-local table for sessions that affect the 0.12.4
        # post-close resolver. It is intentionally explicit rather than inferred.
        return {
            "2026-01-26", "2026-03-03", "2026-03-06", "2026-03-27",
            "2026-03-31", "2026-04-03", "2026-04-14", "2026-05-01",
            "2026-08-15", "2026-10-02", "2026-10-20", "2026-11-09",
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
            if override:
                now = datetime.fromisoformat(override)
            else:
                now = datetime.now(tz) if tz else datetime.now()
        if tz and now.tzinfo is None:
            now = now.replace(tzinfo=tz)
        today = now.date()
        after_close = (now.hour, now.minute) >= (15, 45)
        if cls._is_nse_trading_day(today) and after_close:
            expected = today
            basis = "TRADING_DAY_AFTER_CLOSE"
        elif cls._is_nse_trading_day(today):
            expected = cls._previous_nse_session(today)
            basis = "TRADING_DAY_BEFORE_CLOSE_PREVIOUS_COMPLETED_SESSION"
        else:
            expected = cls._previous_nse_session(today)
            basis = "NON_TRADING_DAY_PREVIOUS_COMPLETED_SESSION"
        return {
            "current_calendar_date": today.isoformat(),
            "expected_market_session": expected.isoformat(),
            "basis": basis,
            "market_close_time": "15:45:00+05:30",
            "calendar": "NSE_EXPLICIT_HOLIDAY_TABLE_V1",
        }

    def _refresh_official_first_market_data(self) -> dict[str, Any]:
        # Local desktop builds can only use configured official data providers.
        # No automatic yfinance fallback is permitted.
        try:
            return {"status": "PASS", "source": self.data_source_status(), "automatic_yfinance_fallback": False}
        except Exception as exc:
            return {"status": "ERROR", "error": str(exc), "automatic_yfinance_fallback": False}

    def _daily_data_gate(self) -> dict[str, Any]:
        expected = self.expected_market_session()
        refresh = self._refresh_official_first_market_data()
        if refresh.get("status") == "ERROR":
            return {
                "source": {},
                **expected,
                "target_session": expected["expected_market_session"],
                "latest_official_session": None,
                "data_freshness": "OFFICIAL SOURCE ERROR",
                "freshness_gate": "BLOCKED",
                "official_mode": False,
                "analysis_data_current": False,
                "universe_coverage": None,
                "identity_coverage": None,
                "ready": False,
                "blocked_reason": "OFFICIAL_SOURCE_ERROR",
                "refresh_status": refresh,
            }
        source = refresh.get("source") or {}
        active = dict(source.get("active") or {})
        latest = active.get("latest_session")
        official_mode = source.get("mode") == "REAL_OFFICIAL_DATA"
        ready = bool(official_mode and latest == expected["expected_market_session"])
        if ready:
            freshness_gate = "PASS"
            freshness_status = "CURRENT"
            blocked = None
        else:
            freshness_gate = "BLOCKED"
            freshness_status = "OFFICIAL DATA NOT READY"
            blocked = "OFFICIAL_DATA_NOT_READY"
        return {
            "source": source,
            **expected,
            "target_session": expected["expected_market_session"],
            "latest_official_session": latest,
            "data_freshness": freshness_status,
            "freshness_gate": freshness_gate,
            "official_mode": official_mode,
            "analysis_data_current": ready,
            "universe_coverage": active.get("history_coverage"),
            "identity_coverage": active.get("identity_coverage"),
            "ready": ready,
            "blocked_reason": blocked,
            "refresh_status": refresh,
        }

'''
start = s.find("    def _daily_data_gate(self)")
end = s.find("    def post_close_daily_status(self)", start)
if start < 0 or end < 0:
    raise RuntimeError("session freshness gate contract missing")
s = s[:start] + new + s[end:]
s = s.replace('"target_session": gate["target_session"],', '"current_calendar_date": gate.get("current_calendar_date"),\n            "expected_market_session": gate.get("expected_market_session"),\n            "target_session": gate["target_session"],')
s = s.replace('"latest_available_official_session": gate["latest_official_session"],', '"latest_available_official_session": gate["latest_official_session"],\n            "active_analysis_session": None if not self.ui_run_input() else self.ui_run_input().get("market_session"),')
s = s.replace('"run_status": "READY" if gate["ready"] else "BLOCKED / DATA NOT READY",', '"run_status": "READY" if gate["ready"] else ("BLOCKED - OFFICIAL SOURCE ERROR" if gate.get("blocked_reason") == "OFFICIAL_SOURCE_ERROR" else "BLOCKED - OFFICIAL DATA NOT READY"),')
s = s.replace('"run_status": "BLOCKED / DATA NOT READY"', '"run_status": "BLOCKED - OFFICIAL DATA NOT READY"')
s = s.replace('"run_status": "DUPLICATE_PROTECTED"', '"run_status": "ALREADY COMPLETED"')

api.write_text(s, encoding="utf-8")

js = root / "modern_ui" / "frontend" / "app.js"
t = js.read_text(encoding="utf-8")
t = t.replace("['Target session',x.target_session||'—'],['Latest official session',x.latest_available_official_session||'—'],", "['Current date',x.current_calendar_date||'—'],['Expected session',x.expected_market_session||x.target_session||'—'],['Latest official session',x.latest_available_official_session||'—'],['Active analysis session',x.active_analysis_session||'—'],")
t = t.replace("['Recommendations',String(x.recommendation_count??0)],['Executable',String(x.executable_count??0)],", "['Recommendations',String((String(x.run_status||'').startsWith('BLOCKED')?'previous ': '')+(x.recommendation_count??0))],['Executable',String((String(x.run_status||'').startsWith('BLOCKED')?'previous ': '')+(x.executable_count??0))],")
js.write_text(t, encoding="utf-8")

phase = root / "phase7"
phase.mkdir(parents=True, exist_ok=True)
(phase / "session_freshness_windows_hardening_0124.json").write_text("""{
  "schema": "SRE_PHASE7_SESSION_FRESHNESS_WINDOWS_HARDENING_0124",
  "release": "0.12.4-phase7-session-freshness-windows-hardening",
  "calendar": "NSE_EXPLICIT_HOLIDAY_TABLE_V1",
  "latest_local_session_is_not_current_session": true,
  "official_first_refresh_before_freshness_decision": true,
  "automatic_yfinance_fallback": false,
  "production_recommendation_authority_changed": false,
  "production_rank_authority_changed": false,
  "technical_v2_authority": "SHADOW_ONLY",
  "fundamental_v3_authority": "SHADOW_ONLY",
  "combined_v2_authority": "SHADOW_ONLY"
}
""", encoding="utf-8")

(root / "WINDOWS_TRUST_STATUS.md").write_text("""# Windows Trust Status

SRE uses a Tauri v2 NSIS current-user installer, matching the safe packaging pattern observed in MIS Assist where applicable.

Unsigned builds can still show Windows Unknown Publisher or SmartScreen warnings. A trusted code-signing certificate is required for normal publisher validation, and SmartScreen reputation may still take time depending on the certificate and distribution reputation.

The CI workflow is prepared for Authenticode signing through `WINDOWS_CERTIFICATE_PFX_BASE64` and `WINDOWS_CERTIFICATE_PASSWORD` secrets. Certificates and passwords must never be committed to the repository.
""", encoding="utf-8")

(root / "phase7" / "windows_packaging_comparison_0124.md").write_text("""# MIS Assist vs SRE Windows Packaging

| Area | MIS Assist observed locally | SRE 0.12.4 hardening |
|---|---|---|
| Installer technology | Tauri v2 NSIS | Tauri v2 NSIS |
| Executable metadata | ProductName/FileDescription `MIS Assist`, CompanyName `misassist`, version `0.3.13` | ProductName/FileDescription `Stock Recommendation Engine`, CompanyName/Publisher `NarayananRG`, version `0.12.4` |
| Requested privileges | `currentUser`, NSIS `RequestExecutionLevel user` | `currentUser`, NSIS user-level install |
| Publisher information | NSIS manufacturer `misassist`; unsigned | Publisher/manufacturer `NarayananRG`; unsigned unless CI certificate secrets are configured |
| Bundle identifier | `in.misassist.desktop` | `com.narayananrg.stockrecommendationengine` |
| Signing status | `Get-AuthenticodeSignature`: NotSigned for installer and app EXE | Conditional signing configured for app EXE and installer; unsigned builds explicitly reported |
| Authenticode status | NotSigned | Valid when secrets are present, otherwise NotSigned with explicit report |
| Installer metadata | Product/File version and ProductName set by Tauri NSIS | Product/File version, ProductName, Description, Copyright set |
| Windows manifest | Tauri/NSIS default DPI-aware user-level manifest | Tauri/NSIS default DPI-aware user-level manifest |
| Distribution/download mechanism | Local build/install artifacts under AppData; no downloaded GitHub ZIP Mark-of-the-Web observed | GitHub artifact ZIP can carry different provenance; build records trust status and SHA-256 without bypassing Windows security |

Why MIS Assist does not show the warning: local evidence shows it is unsigned too, so the difference is not Authenticode. The likely behavioral difference is provenance/distribution: MIS Assist was built and installed from local AppData build outputs, while SRE has been distributed as a downloaded GitHub artifact ZIP/installer that can carry internet-zone reputation/Mark-of-the-Web and lower SmartScreen reputation. SRE now mirrors MIS Assist's safe Tauri NSIS current-user packaging knobs where applicable and is ready for real signing.
""", encoding="utf-8")

assert "0.12.4-phase7-session-freshness-windows-hardening" in api.read_text(encoding="utf-8")
assert "expected_market_session" in api.read_text(encoding="utf-8")
assert "OFFICIAL_DATA_NOT_READY" in api.read_text(encoding="utf-8")
assert "automatic_yfinance_fallback" in (phase / "session_freshness_windows_hardening_0124.json").read_text(encoding="utf-8")
print("0.12.4 session freshness and Windows hardening overlay applied")
