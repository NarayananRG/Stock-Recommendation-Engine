from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])

api = root / "modern_ui" / "api.py"
s = api.read_text(encoding="utf-8")
s = s.replace('APP_VERSION = "0.13.2-phase8-validation-complete"', 'APP_VERSION = "0.13.3-phase8-runtime-fix"', 1)

old = '''            source = self.data_source_status()
            latest = (source.get("active") or {}).get("latest_session")
            if source.get("mode") == "REAL_OFFICIAL_DATA" and latest == expected:
                status = "PASS"
            elif refresh.get("status") == "OFFICIAL_NOT_READY":
                status = "NOT_READY"
            else:
                status = "ERROR"
'''
new = '''            source = self.data_source_status()
            latest = (source.get("active") or {}).get("latest_session")
            verified_latest = refresh.get("verified_latest_session")
            verified_contract = (
                refresh.get("status") == "REFRESHED_AND_VERIFIED"
                and verified_latest == expected
                and bool(refresh.get("persisted"))
            )
            if verified_contract:
                active_now = dict(source.get("active") or {})
                active_now["latest_session"] = expected
                source = {**source, "active": active_now}
                latest = expected
                status = "PASS"
            elif source.get("mode") == "REAL_OFFICIAL_DATA" and latest == expected:
                status = "PASS"
            elif refresh.get("status") == "OFFICIAL_NOT_READY":
                status = "NOT_READY"
            else:
                status = "ERROR"
'''
if old not in s:
    raise RuntimeError("daily refresh verification block missing")
s = s.replace(old, new, 1)

old = '''        if not status.get("active"):
            status = self.phase81_start_paper(100000.0)
        gate = self._daily_data_gate()
'''
new = '''        if not status.get("active"):
            return {
                "schema": "SRE_PHASE81_PROSPECTIVE_OBSERVATION_V1",
                "active": False,
                "status": "PAPER_PORTFOLIO_INACTIVE",
                "recorded": False,
            }
        gate = self._daily_data_gate()
'''
if old not in s:
    raise RuntimeError("paper inactive auto-start block missing")
s = s.replace(old, new, 1)
api.write_text(s, encoding="utf-8")

js = root / "modern_ui" / "frontend" / "app.js"
t = js.read_text(encoding="utf-8")
runtime = r'''
function phase81SetValidationRoute(active){
  const validation=document.getElementById('validationPage');
  if(!validation)return;
  const main=validation.parentElement;
  if(!main)return;
  Array.from(main.children).forEach((child)=>{
    if(child===validation)return;
    if(active){
      if(!child.hasAttribute('data-phase81-prev-display')){
        child.setAttribute('data-phase81-prev-display',child.style.display||'');
      }
      child.style.setProperty('display','none','important');
    }else if(child.hasAttribute('data-phase81-prev-display')){
      const prev=child.getAttribute('data-phase81-prev-display')||'';
      child.removeAttribute('data-phase81-prev-display');
      if(prev)child.style.setProperty('display',prev);else child.style.removeProperty('display');
    }
  });
  validation.classList.toggle('phase81-route-active',!!active);
  validation.classList.toggle('hidden',!active);
  if(active){
    validation.style.setProperty('display','block','important');
  }else{
    validation.style.removeProperty('display');
  }
  document.querySelectorAll('.nav-item[data-page]').forEach((node)=>{
    node.classList.toggle('active',active && node.dataset.page==='validation');
  });
}
function phase81ActivateValidation(){
  phase81SetValidationRoute(true);
  setValidationTab('replay');
  loadValidation();
  window.scrollTo({top:0,behavior:'auto'});
}
if(!window.__phase81RouteBound){
  window.__phase81RouteBound=true;
  document.addEventListener('click',(event)=>{
    const nav=event.target && event.target.closest ? event.target.closest('.nav-item[data-page]') : null;
    if(!nav)return;
    if(nav.dataset.page==='validation'){
      event.preventDefault();
      event.stopImmediatePropagation();
      phase81ActivateValidation();
    }else{
      phase81SetValidationRoute(false);
    }
  },true);
  document.addEventListener('DOMContentLoaded',()=>phase81SetValidationRoute(false));
}
'''
if "function phase81SetValidationRoute(active)" not in t:
    t += "\n" + runtime + "\n"
js.write_text(t, encoding="utf-8")

css = root / "modern_ui" / "frontend" / "styles.css"
c = css.read_text(encoding="utf-8")
if "#validationPage.phase81-route-active" not in c:
    c += "\n#validationPage{display:none!important}#validationPage.phase81-route-active{display:block!important}\n"
css.write_text(c, encoding="utf-8")

assert 'APP_VERSION = "0.13.3-phase8-runtime-fix"' in api.read_text(encoding="utf-8")
assert "verified_contract" in api.read_text(encoding="utf-8")
assert "PAPER_PORTFOLIO_INACTIVE" in api.read_text(encoding="utf-8")
assert "phase81SetValidationRoute" in js.read_text(encoding="utf-8")
assert "#validationPage.phase81-route-active" in css.read_text(encoding="utf-8")
print("0.13.3 Phase 8 runtime fix applied")
