from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])


def edit(relative: str, old: str, new: str, label: str) -> None:
    path = root / relative
    text = path.read_text(encoding="utf-8-sig")
    if old not in text:
        raise RuntimeError(f"{label}: missing patch point {old[:140]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Release identity only; LIVE_DECISION_V1 qualification logic is intentionally unchanged.
edit(
    "modern_ui/api.py",
    'APP_VERSION = "0.14.1-fundamental-coverage-ui-repair"',
    'APP_VERSION = "0.14.2-session-truth-ux-repair"',
    "backend version",
)
edit(
    "stock_app/live_decision_v1.py",
    'MODEL = "0.14.1-fundamental-coverage-ui-repair"',
    'MODEL = "0.14.2-session-truth-ux-repair"',
    "live decision release identity",
)

api = root / "modern_ui" / "api.py"
s = api.read_text(encoding="utf-8")

# One canonical, read-only UI state.  A persisted successful daily run and an
# immutable active live run are valid proof that the official session was
# accepted, even if an older data-source cache still reports an earlier date.
anchor = "    def live_coverage(self) -> dict[str, Any]:\n"
if anchor not in s:
    raise RuntimeError("canonical UI state insertion point missing")

canonical = '''    def canonical_ui_state(self) -> dict[str, Any]:
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
        active_analysis = run_session or success_session
        analysis_complete = bool(run_id and active.get("candidates") is not None)
        stale_active = bool(active_analysis and latest_official and active_analysis != latest_official)

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
            "lane_counts": dict(run.get("lane_counts") or {}),
            "source_mode": source.get("mode"),
            "source_reported_latest_session": source_session,
        }

'''
s = s.replace(anchor, canonical + anchor, 1)

# Dashboard, Opportunities and Capital Plan expose the exact same canonical
# session object.  Existing fields are kept for backwards compatibility.
old = '            "data_source": ctx.data_source_status(),\n'
if old not in s:
    raise RuntimeError("dashboard data-source field missing")
s = s.replace(old, old + '            "ui_state": ctx.canonical_ui_state(),\n', 1)

old = '        return {"items": rows, "count": len(rows), "run": ctx.ui_run_input(), "target_state": ctx.active_target_state()}\n'
if old not in s:
    raise RuntimeError("opportunities GET response missing")
s = s.replace(old, '        return {"items": rows, "count": len(rows), "run": ctx.ui_run_input(), "target_state": ctx.active_target_state(), "ui_state": ctx.canonical_ui_state()}\n', 1)

old = '        return {"ok": True, "items": rows, "count": len(rows), "fundamentals": None, "run": ctx.ui_run_input(), "target_state": ctx.active_target_state(), "reused_run": reused}\n'
if old in s:
    s = s.replace(old, '        return {"ok": True, "items": rows, "count": len(rows), "fundamentals": None, "run": ctx.ui_run_input(), "target_state": ctx.active_target_state(), "reused_run": reused, "ui_state": ctx.canonical_ui_state()}\n', 1)

# Capital blocker counts were occurrence counts.  Replace them with unique
# affected-symbol counts and preserve explicit semantics.
old = '''        from collections import Counter
        blocker_counts = Counter(code for row in live_rows for code in ((row.get("live_decision") or {}).get("reason_codes") or []))
        summary["live_lane_counts"] = lane_counts
        summary["top_blockers"] = dict(blocker_counts.most_common(8))
'''
new = '''        blocker_symbols: dict[str, set[str]] = {}
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
        summary["live_universe_size"] = len(live_rows)
        summary["ui_state"] = self.canonical_ui_state()
'''
if old not in s:
    raise RuntimeError("capital blocker aggregation block missing")
s = s.replace(old, new, 1)

# Add a diagnostic consistency endpoint used by CI and available to the UI.
route_anchor = '    @app.get("/api/portfolio")\n'
if route_anchor not in s:
    raise RuntimeError("UI consistency route insertion point missing")
route = '''    @app.get("/api/ui-consistency")
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

'''
s = s.replace(route_anchor, route + route_anchor, 1)

api.write_text(s, encoding="utf-8")

check = api.read_text(encoding="utf-8")
assert 'APP_VERSION = "0.14.2-session-truth-ux-repair"' in check
assert "def canonical_ui_state" in check
assert '"blocker_count_semantics"] = "UNIQUE_SYMBOLS"' in check
assert '@app.get("/api/ui-consistency")' in check
print("0.14.2 canonical session truth and blocker semantics applied")
