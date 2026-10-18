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
    'APP_VERSION = "0.14.7-analysis-session-paper-repair"',
    'APP_VERSION = "0.14.8-analysis-refresh-execution-repair"',
    "release identity",
)

status_block = r'''    def post_close_daily_status(self) -> dict[str, Any]:
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

        executable = sum(
            1 for row in rows
            if (row.get("live_decision") or {}).get("executable") is True
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
            "executable_count_basis": "CURRENT_ACTIVE_LIVE_DECISION_ROWS",
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

'''
replace_between(api, "    def post_close_daily_status", "    def run_post_close_daily_flow", status_block, "status diagnostics restoration")

js = root / "modern_ui" / "frontend" / "app.js"
renderer = r'''function renderPostCloseDaily(x){const el=$('#postCloseDailyStatus');if(!el)return;x=x||{};const last=x.last_successful_daily_run||{};const analysisStale=x.analysis_current===false||String(x.run_status||'').includes('ANALYSIS REFRESH REQUIRED');const blocked=String(x.run_status||'').startsWith('BLOCKED')||analysisStale;const error=String(x.run_status||'').includes('SOURCE ERROR')||String(x.refresh_label||'').includes('FAILED')||String(x.refresh_label||'').includes('ERROR');const cls=error?'error':(blocked?'blocked':(String(x.freshness_gate||'')==='PASS'?'success':'idle'));const ring=document.querySelector('.today-banner .action-ring');if(ring){ring.classList.remove('success','blocked','error','idle');ring.classList.add(cls);const span=ring.querySelector('span');if(span)span.textContent=cls==='success'?'✓':(cls==='error'?'!':(cls==='blocked'?'!':'•'))}el.className='daily-flow-grid '+cls;const actionHint=analysisStale?'Run POST-CLOSE DAILY FLOW to recompute the accepted official session.':null;const pairs=[['Current date',x.current_calendar_date||'—'],['Expected session',x.expected_market_session||x.target_session||'—'],['Latest official session',x.latest_available_official_session||'—'],['Active analysis session',x.active_analysis_session||'—'],['Data freshness',(x.freshness_gate||'—')+' / '+(x.data_freshness||'—')],['Run status',x.run_status||'—'],['Refresh',x.refresh_label||'—'],['Source detail',x.source_detail||x.refresh_error_detail||'—'],['Recommendations',String(((blocked||analysisStale)?'previous ':'')+(x.recommendation_count??0))],['Executable',String(((blocked||analysisStale)?'previous ':'')+(x.executable_count??0))],['Shadow analysis',x.shadow_analysis_status||'—'],['Validation snapshot',x.validation_snapshot_status||'—'],['Last successful run',last.run_id?last.run_id+' · '+(last.market_session||'—'):'—']];el.innerHTML=pairs.map(function(pair){return '<div><span>'+escapeHtml(pair[0])+'</span><strong>'+escapeHtml(String(pair[1]))+'</strong></div>'}).join('')+(actionHint?'<div class="analysis-refresh-hint"><span>Action required</span><strong>'+escapeHtml(actionHint)+'</strong></div>':'')}
'''
replace_between(js, "function renderPostCloseDaily", "function renderToday", renderer, "today renderer stale-analysis semantics")

css = root / "modern_ui" / "frontend" / "styles.css"
c = css.read_text(encoding="utf-8")
if ".analysis-refresh-hint" not in c:
    c += r'''
.analysis-refresh-hint{grid-column:1/-1!important;border-color:rgba(217,119,6,.38)!important;background:rgba(254,243,199,.62)!important}
.analysis-refresh-hint strong{font-size:13px!important}
'''
css.write_text(c, encoding="utf-8")

policy = root / "phase7" / "analysis_refresh_execution_repair_0148.json"
policy.write_text('''{
  "schema": "SRE_ANALYSIS_REFRESH_EXECUTION_REPAIR_0148",
  "release": "0.14.8-analysis-refresh-execution-repair",
  "stale_analysis_status_is_warning_not_success": true,
  "status_diagnostics_restored": true,
  "post_close_execution_must_advance_analysis_to_target_session": true,
  "live_e2e_required": true,
  "recommendation_authority_changed": false,
  "model_or_threshold_changed": false,
  "provider_policy_changed": false,
  "automatic_yfinance_fallback": false
}
''', encoding="utf-8")

check = api.read_text(encoding="utf-8")
assert 'APP_VERSION = "0.14.8-analysis-refresh-execution-repair"' in check
assert '"current_calendar_date": gate.get("current_calendar_date")' in check
assert '"refresh_label": refresh_label' in check
assert '"source_detail": source_detail' in check
assert '"analysis_action": None if session_state.get("analysis_current") else "RUN_POST_CLOSE_DAILY_FLOW"' in check
j = js.read_text(encoding="utf-8")
assert "ANALYSIS REFRESH REQUIRED" in j
assert "analysis-refresh-hint" in j
print("0.14.8 analysis refresh execution UX repair applied")
