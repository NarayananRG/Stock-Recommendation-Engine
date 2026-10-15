from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])

def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(label + " patch point missing")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

def replace_between(path: Path, start_marker: str, end_marker: str, replacement: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(label + " start marker missing")
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(label + " end marker missing")
    path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")

api = root / "modern_ui" / "api.py"
replace_once(
    api,
    'APP_VERSION = "0.14.6-official-data-refresh-repair"',
    'APP_VERSION = "0.14.7-analysis-session-paper-repair"',
    "release identity",
)

consistency_module = r'''from __future__ import annotations
from typing import Any

def reusable_analysis_session(candidate_session: Any, latest_official_session: Any) -> bool:
    candidate = str(candidate_session or "").strip()
    latest = str(latest_official_session or "").strip()
    return bool(candidate and latest and candidate == latest)

def analysis_session_state(*, data_ready: bool, target_session: Any, analysis_session: Any) -> dict[str, Any]:
    target = str(target_session or "").strip()
    analysis = str(analysis_session or "").strip()
    analysis_current = bool(data_ready and target and analysis == target)
    if not data_ready:
        status = "DATA_NOT_READY"
    elif not analysis:
        status = "ANALYSIS_REQUIRED"
    elif analysis != target:
        status = "ANALYSIS_REFRESH_REQUIRED"
    else:
        status = "READY"
    return {
        "data_ready": bool(data_ready),
        "target_session": target or None,
        "analysis_session": analysis or None,
        "analysis_current": analysis_current,
        "status": status,
    }
'''
(root / "stock_app" / "session_consistency.py").write_text(consistency_module, encoding="utf-8")

# A live-decision cache may only be reused for the same market session.
replace_once(
    api,
    '''        path = self._live_file(str(run["run_id"]))
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        session = str(run["market_session"])
''',
    '''        path = self._live_file(str(run["run_id"]))
        session = str(run["market_session"])
        if path.exists():
            cached = json.loads(path.read_text(encoding="utf-8"))
            cached_session = str((cached.get("run") or {}).get("market_session") or "")
            if cached_session == session:
                return cached
            # A run-id cache from an older market session must never survive a
            # newly accepted official session.
            path.unlink(missing_ok=True)
''',
    "live cache market-session guard",
)

replace_once(
    api,
    '            return self._materialize_live_run(match), True',
    '''            candidate = self._materialize_live_run(match)
            source_now = self.data_source_status()
            latest_now = (source_now.get("active") or {}).get("latest_session")
            from stock_app.session_consistency import reusable_analysis_session
            if reusable_analysis_session((candidate.get("run") or {}).get("market_session"), latest_now):
                return candidate, True
            # Same capital/horizon/target is not sufficient for reuse when the
            # official market session has advanced. Fall through and create a
            # fresh analysis run for the accepted data session.''',
    "analysis reuse market-session guard",
)

# Never use last-success metadata as a substitute for an active analysis run.
replace_once(
    api,
    "        active_analysis = run_session or success_session",
    "        active_analysis = run_session",
    "canonical active-analysis truth",
)

status_impl = r'''    def _analysis_session_state(self, gate: dict[str, Any] | None = None) -> dict[str, Any]:
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
        if not gate.get("ready"):
            run_status = f"BLOCKED - {gate.get('data_freshness') or 'OFFICIAL DATA NOT READY'}"
        elif not session_state.get("analysis_current"):
            run_status = "ANALYSIS REFRESH REQUIRED"
        else:
            run_status = "READY"
        executable = sum(
            1 for row in rows
            if (row.get("live_decision") or {}).get("executable") is True
        ) if session_state.get("analysis_current") else 0
        return {
            "schema": "SRE_POST_CLOSE_DAILY_FLOW_STATUS_V2",
            "authority": "LIVE_DECISION_V1",
            "target_session": gate.get("target_session"),
            "latest_available_official_session": gate.get("latest_official_session"),
            "active_analysis_session": session_state.get("analysis_session"),
            "analysis_current": session_state.get("analysis_current"),
            "analysis_status": session_state.get("status"),
            "data_freshness": gate.get("data_freshness"),
            "freshness_gate": gate.get("freshness_gate"),
            "universe_coverage": gate.get("universe_coverage"),
            "identity_coverage": gate.get("identity_coverage"),
            "run_status": run_status,
            "recommendation_count": len(rows),
            "recommendation_scope": "ACTIVE_LIVE_UNIVERSE",
            "recommendation_session": session_state.get("analysis_session"),
            "executable_count": executable,
            "shadow_analysis_status": "Technical V2 and Fundamental V3: LIVE_EVIDENCE; Combined V2: DIAGNOSTIC_ONLY",
            "validation_snapshot_status": "SUPPORTED_WHEN_MONITORING_ROWS_EXIST",
            "last_successful_daily_run": latest_success,
            "last_result": state.get("last_result"),
            "no_yfinance": True,
            "automatic_yfinance_fallback": False,
        }

'''
replace_between(
    api,
    "    def post_close_daily_status",
    "    def run_post_close_daily_flow",
    status_impl,
    "post-close status consistency",
)

flow_impl = r'''    def run_post_close_daily_flow(self, *, force: bool = False) -> dict[str, Any]:
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

'''
replace_between(
    api,
    "    def run_post_close_daily_flow",
    "    def _phase81_db_path",
    flow_impl,
    "post-close recompute orchestration",
)

paper = root / "stock_app" / "phase81_validation.py"
p = paper.read_text(encoding="utf-8")

old_guard = '''        previous = con.execute("select event_json from paper_journal where portfolio_id=? and market_session=? and production_run_id is ? and event_type in ('DAILY_DECISION','SIGNAL_GENERATED') order by created_at limit 1", (portfolio_id, market_session, production_run_id)).fetchone()
        if previous:
            return {**json.loads(previous[0]), "duplicate": True}
'''
new_guard = '''        previous = con.execute("select event_json from paper_journal where portfolio_id=? and market_session=? and event_type in ('DAILY_DECISION','SIGNAL_GENERATED') order by created_at limit 1", (portfolio_id, market_session)).fetchone()
        if previous:
            return {**json.loads(previous[0]), "duplicate": True}
'''
if old_guard not in p:
    raise RuntimeError("paper per-run duplicate guard missing")
p = p.replace(old_guard, new_guard, 1)

old_key = 'written = _journal(con, event, f"{portfolio_id}|{market_session}|{production_run_id}|{event_type}")'
if old_key not in p:
    raise RuntimeError("paper daily idempotency key missing")
p = p.replace(old_key, 'written = _journal(con, event, f"{portfolio_id}|{market_session}|{event_type}")', 1)

load_anchor = "def load_portfolio(db_path: Path, portfolio_id: str | None = None) -> dict[str, Any]:\n"
if load_anchor not in p:
    raise RuntimeError("paper load_portfolio anchor missing")
canonical_helper = r'''def _canonical_journal_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # DAILY_DECISION/SIGNAL_GENERATED are one forward decision per market
    # session. Preserve the earliest accepted event for audit continuity and
    # hide legacy duplicate rows created with different production run IDs.
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for event in sorted(rows, key=lambda x: str(x.get("created_at") or "")):
        event_type = str(event.get("event_type") or "")
        if event_type in {"DAILY_DECISION", "SIGNAL_GENERATED"}:
            key = (str(event.get("market_session") or ""), "DAILY_SIGNAL")
            if key in seen:
                continue
            seen.add(key)
        result.append(event)
    return sorted(result, key=lambda x: str(x.get("created_at") or ""), reverse=True)

'''
p = p.replace(load_anchor, canonical_helper + load_anchor, 1)

old_journal = '        state["journal"] = [json.loads(r[0]) for r in con.execute("select event_json from paper_journal where portfolio_id=? order by created_at desc limit 200", (portfolio_id,))]'
new_journal = '''        raw_journal = [json.loads(r[0]) for r in con.execute("select event_json from paper_journal where portfolio_id=? order by created_at desc limit 400", (portfolio_id,))]
        state["journal"] = _canonical_journal_rows(raw_journal)[:200]
        state["journal_duplicate_rows_hidden"] = max(0, len(raw_journal) - len(_canonical_journal_rows(raw_journal)))'''
if old_journal not in p:
    raise RuntimeError("paper journal load assignment missing")
p = p.replace(old_journal, new_journal, 1)
paper.write_text(p, encoding="utf-8")

# Fix the narrow 5-column decision modal that was breaking words character by character.
css = root / "modern_ui" / "frontend" / "styles.css"
c = css.read_text(encoding="utf-8")
c += r'''
/* 0.14.7 analysis consistency + readable decision modal */
.opportunity-detail-v2{max-width:900px;overflow-wrap:normal;word-break:normal}
.decision-summary-grid{grid-template-columns:repeat(3,minmax(0,1fr))!important}
.evidence-grid-v2{grid-template-columns:repeat(2,minmax(180px,1fr))!important}
.decision-summary-grid>div,.evidence-grid-v2>div{min-width:0}
.decision-summary-grid strong,.evidence-grid-v2 strong{white-space:normal;overflow-wrap:break-word;word-break:normal}
@media(max-width:720px){.decision-summary-grid,.evidence-grid-v2{grid-template-columns:1fr!important}}
'''
css.write_text(c, encoding="utf-8")

policy = root / "phase7" / "analysis_session_paper_repair_0147.json"
policy.write_text('''{
  "schema": "SRE_ANALYSIS_SESSION_PAPER_REPAIR_0147",
  "release": "0.14.7-analysis-session-paper-repair",
  "analysis_must_match_accepted_official_session": true,
  "stale_analysis_reuse_allowed": false,
  "daily_success_requires_current_analysis": true,
  "paper_daily_decision_idempotency": "PORTFOLIO_MARKET_SESSION",
  "legacy_duplicate_journal_rows_hidden": true,
  "recommendation_authority_changed": false,
  "model_or_threshold_changed": false,
  "provider_policy_changed": false,
  "automatic_yfinance_fallback": false
}
''', encoding="utf-8")

check = api.read_text(encoding="utf-8")
assert 'APP_VERSION = "0.14.7-analysis-session-paper-repair"' in check
assert "ANALYSIS REFRESH REQUIRED" in check
assert "ANALYSIS_SESSION_MISMATCH" in check
assert "active_analysis = run_session" in check
assert "limit=200" in check
assert "reusable_analysis_session" in check
assert "_canonical_journal_rows" in paper.read_text(encoding="utf-8")
print("0.14.7 analysis-session and paper-journal repair applied")
