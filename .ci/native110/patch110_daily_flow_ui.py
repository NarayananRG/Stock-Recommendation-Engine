from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])


def repl(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(label + " contract missing")
    return text.replace(old, new, 1)


api = root / "modern_ui" / "api.py"
s = api.read_text(encoding="utf-8")
s = repl(
    s,
    'APP_VERSION = "0.12.2-phase7-first-launch-state-hotfix"',
    'APP_VERSION = "0.12.3-phase7-daily-flow-ui-hotfix"',
    "backend version",
)

s = s.replace('"MEETS TARGET"', '"RETURN THRESHOLD MET"').replace('"BELOW TARGET"', '"RETURN THRESHOLD BELOW"')
s = s.replace("'MEETS TARGET'", "'RETURN THRESHOLD MET'").replace("'BELOW TARGET'", "'RETURN THRESHOLD BELOW'")
s = s.replace('"CASH AFFORDABLE · MODEL WATCH"', '"NOT EXECUTABLE - WATCH"')

anchor = '''    def latest_prediction_rows(self, limit: int = 20) -> list[dict[str, Any]]:
'''
helper = '''    def _daily_state_file(self) -> Path:
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

    def _daily_data_gate(self) -> dict[str, Any]:
        source = self.data_source_status()
        active = dict(source.get("active") or {})
        latest = active.get("latest_session")
        freshness_gate = active.get("freshness_gate")
        freshness_status = active.get("freshness_status")
        official_mode = source.get("mode") == "REAL_OFFICIAL_DATA"
        data_current = bool(active.get("analysis_data_current"))
        universe_coverage = active.get("history_coverage")
        identity_coverage = active.get("identity_coverage")
        ready = bool(official_mode and data_current and freshness_gate == "PASS" and latest)
        return {
            "source": source,
            "target_session": latest,
            "latest_official_session": latest,
            "data_freshness": freshness_status or "UNAVAILABLE",
            "freshness_gate": freshness_gate or "FAIL",
            "official_mode": official_mode,
            "analysis_data_current": data_current,
            "universe_coverage": universe_coverage,
            "identity_coverage": identity_coverage,
            "ready": ready,
            "blocked_reason": None if ready else "DATA_NOT_READY",
        }

    def post_close_daily_status(self) -> dict[str, Any]:
        gate = self._daily_data_gate()
        state = self._read_daily_state()
        latest_success = state.get("last_successful_run")
        return {
            "schema": "SRE_POST_CLOSE_DAILY_FLOW_STATUS_V1",
            "authority": "FROZEN_PRODUCTION_RECOMMENDATIONS_UNCHANGED",
            "target_session": gate["target_session"],
            "latest_available_official_session": gate["latest_official_session"],
            "data_freshness": gate["data_freshness"],
            "freshness_gate": gate["freshness_gate"],
            "universe_coverage": gate["universe_coverage"],
            "identity_coverage": gate["identity_coverage"],
            "run_status": "READY" if gate["ready"] else "BLOCKED / DATA NOT READY",
            "recommendation_count": len(self.latest_prediction_rows(limit=100)),
            "executable_count": len([x for x in self.latest_prediction_rows(limit=100) if x.get("executable")]),
            "shadow_analysis_status": "Technical V2/Fundamental V3/Combined V2 remain SHADOW_ONLY",
            "validation_snapshot_status": "SUPPORTED_WHEN_MONITORING_ROWS_EXIST",
            "last_successful_daily_run": latest_success,
            "last_result": state.get("last_result"),
            "no_yfinance": True,
            "automatic_yfinance_fallback": False,
        }

    def run_post_close_daily_flow(self, *, force: bool = False) -> dict[str, Any]:
        gate = self._daily_data_gate()
        previous = self._read_daily_state()
        prior_success = previous.get("last_successful_run") or {}
        if not gate["ready"]:
            result = {**self.post_close_daily_status(), "ok": False, "run_status": "BLOCKED / DATA NOT READY", "blocked_reason": gate["blocked_reason"]}
            self._write_daily_state({"last_result": result, "last_successful_run": prior_success})
            return result
        if prior_success.get("market_session") == gate["target_session"] and not force:
            return {**self.post_close_daily_status(), "ok": True, "run_status": "DUPLICATE_PROTECTED", "duplicate": True}

        target_state = self.active_target_state()
        target = target_state.get("value") if target_state.get("explicit") else None
        active, reused = self.ensure_analysis_run(100000.0, 20, target)
        rows = self.latest_prediction_rows(limit=100)
        run = self.ui_run_input()
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
            "run_id": None if not run else run.get("run_id"),
            "market_session": gate["target_session"],
            "run_timestamp": datetime.now().isoformat(timespec="seconds"),
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
        result = {**self.post_close_daily_status(), "ok": True, "run_status": "SUCCESS", "duplicate": False, "last_successful_daily_run": success}
        self._write_daily_state({"last_successful_run": success, "last_result": result})
        return result

'''
s = repl(s, anchor, helper + anchor, "post-close daily helpers")

route_anchor = '''    @app.get("/api/today")
    def today() -> dict[str, Any]:
        return ctx.monitoring.summary()
'''
route_new = '''    @app.get("/api/today")
    def today() -> dict[str, Any]:
        return {**ctx.monitoring.summary(), "post_close_daily": ctx.post_close_daily_status()}

    @app.get("/api/post-close-daily-flow")
    def post_close_daily_flow_status() -> dict[str, Any]:
        return ctx.post_close_daily_status()

    @app.post("/api/post-close-daily-flow")
    def run_post_close_daily_flow(force: bool = False) -> dict[str, Any]:
        return ctx.run_post_close_daily_flow(force=force)
'''
s = repl(s, route_anchor, route_new, "post-close daily routes")

capital_text = '''        if not result.get("new_buys") and [row for row in result.get("excluded", []) if row.get("reason_code") == "NON_EXECUTABLE_MODEL_STATUS"]:
            summary["target_non_executable_explanation"] = "These stocks meet your requested return threshold, but none are executable BUY recommendations under the current production decision rules."
'''
s = repl(
    s,
    '        return result\n\n',
    capital_text + '        return result\n\n',
    "capital non-executable explanation",
)

api.write_text(s, encoding="utf-8")

html = root / "modern_ui" / "frontend" / "index.html"
h = html.read_text(encoding="utf-8")
h = repl(
    h,
    '<div class="page-heading compact"><div><div class="eyebrow">MONITOR</div><h1>Today</h1><p>The original Leg 7 anti-churn monitoring logic, with HOLD / WEAKENING / EXIT evidence surfaced clearly.</p></div><div class="page-actions"><button id="runMonitoring" class="secondary-btn">Run position check</button><button id="runDailyWorkflow" class="primary-btn">Run full daily workflow</button></div></div>',
    '<div class="page-heading compact"><div><div class="eyebrow">MONITOR</div><h1>Today</h1><p>Post-close official-data workflow and portfolio monitoring, with no broker execution.</p></div><div class="page-actions"><button id="runMonitoring" class="secondary-btn">Run position check</button><button id="runPostCloseDaily" class="primary-btn">RUN POST-CLOSE DAILY FLOW</button></div></div>',
    "today heading",
)
h = repl(
    h,
    '<article class="panel-card today-banner"><div class="action-ring"><span>✓</span></div><div><span class="card-label">NO AUTOMATIC TRADING</span><h3 id="todayHeadline">Waiting for portfolio assessment</h3><p id="todaySubtext">Run the position check to evaluate current holdings against the frozen lifecycle rules.</p></div></article>',
    '<article class="panel-card today-banner"><div class="action-ring"><span>✓</span></div><div><span class="card-label">NO AUTOMATIC TRADING</span><h3 id="todayHeadline">Waiting for portfolio assessment</h3><p id="todaySubtext">Run the position check to evaluate current holdings against the frozen lifecycle rules.</p><div id="postCloseDailyStatus" class="daily-flow-grid"></div></div></article>',
    "today status panel",
)
html.write_text(h, encoding="utf-8")

js = root / "modern_ui" / "frontend" / "app.js"
t = js.read_text(encoding="utf-8")
t = t.replace("target==='MEETS TARGET'?'positive-text':target==='BELOW TARGET'?'negative-text':''", "target==='RETURN THRESHOLD MET'?'positive-text':target==='RETURN THRESHOLD BELOW'?'negative-text':''")
t = t.replace("i.target_status==='MEETS TARGET'?'positive-text':i.target_status==='BELOW TARGET'?'negative-text':''", "i.target_status==='RETURN THRESHOLD MET'?'positive-text':i.target_status==='RETURN THRESHOLD BELOW'?'negative-text':''")
t = t.replace("CASH AFFORDABLE · MODEL WATCH", "NOT EXECUTABLE - WATCH")

t = repl(
    t,
    "function renderOpportunityCard(item){\n",
    """function evidenceStatus(item){
  const raw=String(item.opportunity_status||'').toUpperCase();
  return {
    decision: raw.includes('WATCH')?'WATCH':raw.includes('BUY')?'BUY':(item.opportunity_status||'NO ACTIVE SIGNAL'),
    production_basis: raw.includes('TECHNICAL')?'TECHNICAL ONLY':'FROZEN PRODUCTION MODEL',
    technical: raw.includes('TECHNICAL')?'TECHNICAL EVIDENCE ACTIVE':'SEE TECHNICAL V2',
    fundamental: raw.includes('FUNDAMENTAL')?'INCOMPLETE':'SEE FUNDAMENTAL V3',
    combined: 'SHADOW ONLY'
  };
}
function evidenceStatusHtml(item){
  const e=evidenceStatus(item);
  return `<div class="evidence-split"><span>Decision: <strong>${escapeHtml(e.decision)}</strong></span><span>Production basis: <strong>${escapeHtml(e.production_basis)}</strong></span><span>Technical evidence: <strong>${escapeHtml(e.technical)}</strong></span><span>Fundamental coverage: <strong>${escapeHtml(e.fundamental)}</strong></span><span>Combined V2: <strong>${escapeHtml(e.combined)}</strong></span></div>`;
}
function renderOpportunityCard(item){
""",
    "evidence status helpers",
)
t = repl(
    t,
    '<div class="opp-symbol">${escapeHtml(item.symbol)}</div><div class="opp-status">${escapeHtml(decisionDisplayTitle(item.opportunity_status||\'Evidence available\'))}</div>',
    '<div class="opp-symbol">${escapeHtml(item.symbol)}</div><div class="opp-status">${evidenceStatusHtml(item)}</div>',
    "opportunity card evidence split",
)
t = repl(
    t,
    "$('#heroSub').textContent=decisionDisplayTitle(hero.opportunity_status||'Ranked evidence')+(targetState.explicit?(' · '+(hero.target_status||'NO TARGET')):'');",
    "const ev=evidenceStatus(hero);$('#heroSub').textContent='Decision: '+ev.decision+' · Production basis: '+ev.production_basis+' · Fundamental coverage: '+ev.fundamental+' · Combined V2: '+ev.combined+(targetState.explicit?(' · '+(hero.target_status||'NO TARGET')):'');",
    "hero evidence split",
)
t = repl(
    t,
    "async function loadToday(){const d=await api('/api/today');state.today=d;renderToday(d)}",
    "async function loadToday(){const d=await api('/api/today');state.today=d;renderToday(d)}\nfunction renderPostCloseDaily(x){const el=$('#postCloseDailyStatus');if(!el)return;x=x||{};const last=x.last_successful_daily_run||{};el.innerHTML=[['Target session',x.target_session||'—'],['Latest official session',x.latest_available_official_session||'—'],['Data freshness',(x.freshness_gate||'—')+' / '+(x.data_freshness||'—')],['Run status',x.run_status||'—'],['Recommendations',String(x.recommendation_count??0)],['Executable',String(x.executable_count??0)],['Shadow analysis',x.shadow_analysis_status||'—'],['Validation snapshot',x.validation_snapshot_status||'—'],['Last successful run',last.run_id?last.run_id+' · '+(last.market_session||'—'):'—']].map(([k,v])=>`<div><span>${escapeHtml(k)}</span><strong>${escapeHtml(String(v))}</strong></div>`).join('')}",
    "today load daily renderer",
)
t = repl(
    t,
    "function renderToday(d){const c=d.action_counts||{},h=d.health_counts||{},a=d.actions||[];",
    "function renderToday(d){renderPostCloseDaily(d.post_close_daily||{});const c=d.action_counts||{},h=d.health_counts||{},a=d.actions||[];",
    "today render daily status",
)
t = repl(
    t,
    "async function runFullDaily(){if(!confirm('Run the full daily workflow now? This can take longer because it checks official data and refreshes the recommendation pipeline.'))return;busy(true,'Running daily workflow','Official data → V1 → historical prediction → portfolio monitoring → saved results');try{await api('/api/daily-workflow',{method:'POST'});renderDashboard(await api('/api/dashboard'));await loadToday();toast('Daily workflow complete')}catch(e){toast(e.message)}finally{busy(false)}}",
    "async function runPostCloseDaily(force=false){busy(true,'Running post-close daily flow','Official data freshness → frozen production run → shadow evidence → validation snapshot');try{const d=await api('/api/post-close-daily-flow?force='+(force?'true':'false'),{method:'POST'});renderPostCloseDaily(d);renderDashboard(await api('/api/dashboard'));const opp=await api('/api/opportunities');state.opportunityItems=opp.items||[];applyOpportunityFilter();await loadCapitalDefaults();await loadToday();toast(d.run_status||'Post-close daily flow complete')}catch(e){toast(e.message)}finally{busy(false)}}",
    "daily button handler",
)
t = repl(
    t,
    "$('#buildCapitalPlan')?.addEventListener('click',buildCapitalPlan); $('#runMonitoring')?.addEventListener('click',runMonitoring); $('#runDailyWorkflow')?.addEventListener('click',runFullDaily);",
    "$('#buildCapitalPlan')?.addEventListener('click',buildCapitalPlan); $('#runMonitoring')?.addEventListener('click',runMonitoring); $('#runPostCloseDaily')?.addEventListener('click',()=>runPostCloseDaily(false));",
    "daily event handler",
)
js.write_text(t, encoding="utf-8")

css = root / "modern_ui" / "frontend" / "styles.css"
c = css.read_text(encoding="utf-8")
if ".evidence-split" not in c:
    c += """
/* Phase 7 UI semantics and post-close daily flow */
.evidence-split{display:grid;gap:3px;font-size:11px;line-height:1.35}.evidence-split span{opacity:.72}.evidence-split strong{opacity:1}
.daily-flow-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:12px}.daily-flow-grid>div{padding:10px;border:1px solid rgba(120,128,150,.16);border-radius:8px;background:rgba(255,255,255,.45);display:grid;gap:4px}.daily-flow-grid span{font-size:10px;font-weight:800;text-transform:uppercase;opacity:.58}.daily-flow-grid strong{font-size:12px;line-height:1.35}
@media(max-width:900px){.daily-flow-grid{grid-template-columns:1fr}}
"""
css.write_text(c, encoding="utf-8")

phase = root / "phase7"
phase.mkdir(parents=True, exist_ok=True)
(phase / "daily_flow_ui_hotfix_0123.json").write_text("""{
  "schema": "SRE_PHASE7_DAILY_FLOW_UI_HOTFIX_0123",
  "release": "0.12.3-phase7-daily-flow-ui-hotfix",
  "recommendation_authority_changed": false,
  "ranking_authority_changed": false,
  "technical_v2_authority": "SHADOW_ONLY",
  "fundamental_v3_authority": "SHADOW_ONLY",
  "combined_v2_authority": "SHADOW_ONLY",
  "automatic_yfinance_fallback": false,
  "broker_execution": false
}
""", encoding="utf-8")

assert "0.12.3-phase7-daily-flow-ui-hotfix" in api.read_text(encoding="utf-8")
assert "RETURN THRESHOLD MET" in api.read_text(encoding="utf-8")
assert "post_close_daily_status" in api.read_text(encoding="utf-8")
assert "RUN POST-CLOSE DAILY FLOW" in html.read_text(encoding="utf-8")
assert "evidenceStatusHtml" in js.read_text(encoding="utf-8")
assert '"automatic_yfinance_fallback": False' in api.read_text(encoding="utf-8")
print("0.12.3 daily flow and UI semantics hotfix applied")
