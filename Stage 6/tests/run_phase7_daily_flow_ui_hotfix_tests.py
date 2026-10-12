from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    scratch = ROOT / "work"
    scratch.mkdir(exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="sre_phase7_daily_", dir=scratch))
    try:
        engine = temp / "engine"
        (engine / "modern_ui/frontend").mkdir(parents=True)
        (engine / "phase7").mkdir(parents=True)
        api = engine / "modern_ui/api.py"
        api.write_text(
            '''from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Any
APP_VERSION = "0.12.2-phase7-first-launch-state-hotfix"
def _finite(v): return None if v in (None, "") else float(v)
class Ctx:
    def __init__(self): pass
    def data_source_status(self): return {}
    def active_target_state(self): return {"explicit": False}
    def latest_prediction_rows(self, limit: int = 20) -> list[dict[str, Any]]:
        item = {"opportunity_status": "WATCH", "expected_return": 0.07}
        requested = 0.05
        item["meets_target"] = True
        item["target_status"] = "NO TARGET" if requested is None else ("MEETS TARGET" if item["meets_target"] else "BELOW TARGET")
        item["execution_status"] = "CASH AFFORDABLE · MODEL WATCH"
        return [item]
    def build_capital_plan(self):
        result = {"new_buys": [], "excluded": [{"reason_code": "NON_EXECUTABLE_MODEL_STATUS"}], "capital_summary": {}}
        summary = result["capital_summary"]
        return result
def create_app():
    ctx = Ctx()
    @app.get("/api/today")
    def today() -> dict[str, Any]:
        return ctx.monitoring.summary()
''',
            encoding="utf-8",
        )
        html = engine / "modern_ui/frontend/index.html"
        html.write_text(
            '<div class="page-heading compact"><div><div class="eyebrow">MONITOR</div><h1>Today</h1><p>The original Leg 7 anti-churn monitoring logic, with HOLD / WEAKENING / EXIT evidence surfaced clearly.</p></div><div class="page-actions"><button id="runMonitoring" class="secondary-btn">Run position check</button><button id="runDailyWorkflow" class="primary-btn">Run full daily workflow</button></div></div>'
            '<article class="panel-card today-banner"><div class="action-ring"><span>✓</span></div><div><span class="card-label">NO AUTOMATIC TRADING</span><h3 id="todayHeadline">Waiting for portfolio assessment</h3><p id="todaySubtext">Run the position check to evaluate current holdings against the frozen lifecycle rules.</p></div></article>',
            encoding="utf-8",
        )
        js = engine / "modern_ui/frontend/app.js"
        js.write_text(
            """function renderOpportunityCard(item){
  const target=item.target_status||'NO TARGET'; const targetCls=target==='MEETS TARGET'?'positive-text':target==='BELOW TARGET'?'negative-text':'';
  return `<div class="opp-symbol">${escapeHtml(item.symbol)}</div><div class="opp-status">${escapeHtml(decisionDisplayTitle(item.opportunity_status||'Evidence available'))}</div>`;
}
function renderDashboard(data){
  const hero=data.opportunities[0], targetState=data.target_state||{};
  $('#heroSub').textContent=decisionDisplayTitle(hero.opportunity_status||'Ranked evidence')+(targetState.explicit?(' · '+(hero.target_status||'NO TARGET')):'');
}
async function loadToday(){const d=await api('/api/today');state.today=d;renderToday(d)}
function renderToday(d){const c=d.action_counts||{},h=d.health_counts||{},a=d.actions||[];
}
async function runFullDaily(){if(!confirm('Run the full daily workflow now? This can take longer because it checks official data and refreshes the recommendation pipeline.'))return;busy(true,'Running daily workflow','Official data → V1 → historical prediction → portfolio monitoring → saved results');try{await api('/api/daily-workflow',{method:'POST'});renderDashboard(await api('/api/dashboard'));await loadToday();toast('Daily workflow complete')}catch(e){toast(e.message)}finally{busy(false)}}
$('#buildCapitalPlan')?.addEventListener('click',buildCapitalPlan); $('#runMonitoring')?.addEventListener('click',runMonitoring); $('#runDailyWorkflow')?.addEventListener('click',runFullDaily);
""",
            encoding="utf-8",
        )
        (engine / "modern_ui/frontend/styles.css").write_text("", encoding="utf-8")
        env = os.environ.copy()
        env["SRE_ENGINE_ROOT"] = str(engine)
        subprocess.run([sys.executable, str(ROOT / ".ci/native110/patch110_daily_flow_ui.py")], cwd=ROOT, env=env, check=True)
        text_api = api.read_text(encoding="utf-8")
        text_js = js.read_text(encoding="utf-8")
        text_html = html.read_text(encoding="utf-8")
        cases = [
            ("version", "0.12.3-phase7-daily-flow-ui-hotfix" in text_api),
            ("return threshold wording", "RETURN THRESHOLD MET" in text_api and "MEETS TARGET" not in text_api),
            ("watch non-executable wording", "NOT EXECUTABLE - WATCH" in text_api),
            ("post-close api", "run_post_close_daily_flow" in text_api and "DUPLICATE_PROTECTED" in text_api and "DATA_NOT_READY" in text_api),
            ("no automatic yfinance", '"automatic_yfinance_fallback": False' in text_api),
            ("authority unchanged", "FROZEN_PRODUCTION_RECOMMENDATIONS_UNCHANGED" in text_api),
            ("today button", "RUN POST-CLOSE DAILY FLOW" in text_html),
            ("split evidence UI", "evidenceStatusHtml" in text_js and "Production basis" in text_js and "Fundamental coverage" in text_js),
        ]
        for name, ok in cases:
            print(f"{name}: {'PASS' if ok else 'FAIL'}")
        return 0 if all(ok for _, ok in cases) else 1
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
