from pathlib import Path
import os

root = Path(os.environ['SRE_ENGINE_ROOT'])

def replace_once(path, old, new, label):
    text = path.read_text(encoding='utf-8')
    if old not in text:
        raise RuntimeError(label + ' patch point missing')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')

# Release identity only. Recommendation logic, thresholds and provider routing stay unchanged.
replace_once(root/'modern_ui'/'api.py', 'APP_VERSION = "0.14.3-decision-clarity-ux"', 'APP_VERSION = "0.14.4-interaction-hotfix"', 'api version')
replace_once(root/'stock_app'/'live_decision_v1.py', 'MODEL = "0.14.3-decision-clarity-ux"', 'MODEL = "0.14.4-interaction-hotfix"', 'model version')

app = root/'modern_ui'/'frontend'/'app.js'
s = app.read_text(encoding='utf-8')

# 0.14.2 converted a disabled zero-BUY hero button into Browse stocks but forgot to re-enable it.
old = "if(!b){e.textContent='Browse stocks ->';e.dataset.browseStocks='true'}"
new = "if(!b){e.textContent='Browse stocks ->';e.dataset.browseStocks='true';e.disabled=false;e.removeAttribute('disabled');e.setAttribute('aria-disabled','false')}"
if old not in s:
    raise RuntimeError('browse-stocks enablement patch point missing')
s = s.replace(old, new, 1)

# Navigate directly instead of synthesizing another click and depending on a separate nav binding.
old = "document.querySelector('.nav-item[data-page=\"opportunities\"]')?.click()"
new = "(typeof switchPage==='function'?switchPage('opportunities'):document.querySelector('.nav-item[data-page=\"opportunities\"]')?.click())"
if old not in s:
    raise RuntimeError('browse-stocks navigation patch point missing')
s = s.replace(old, new, 1)

runtime = r'''
function ui144RunAction(event){
  const el=event.target?.closest?.('button,a,[role="button"]');
  if(!el)return;
  const id=el.id||'';
  if(el.dataset?.browseStocks==='true'){
    event.preventDefault();event.stopImmediatePropagation();
    if(typeof switchPage==='function')switchPage('opportunities');
    else document.querySelector('.nav-item[data-page="opportunities"]')?.click();
    return;
  }
  if(id==='runMonitoring'){
    event.preventDefault();event.stopImmediatePropagation();
    if(typeof runMonitoring==='function')runMonitoring();
    return;
  }
  if(id==='runPostCloseDaily'){
    event.preventDefault();event.stopImmediatePropagation();
    if(typeof runPostCloseDaily==='function')runPostCloseDaily(false);
    return;
  }
  if(id==='buildCapitalPlan'){
    event.preventDefault();event.stopImmediatePropagation();
    if(typeof buildCapitalPlan==='function')buildCapitalPlan();
    return;
  }
  if(id==='heroOpen' && el.dataset?.symbol){
    event.preventDefault();event.stopImmediatePropagation();
    if(typeof openStock==='function')openStock(el.dataset.symbol);
  }
}
if(!window.__sre0144InteractionBound){
  window.__sre0144InteractionBound=true;
  document.addEventListener('click',ui144RunAction,true);
}
'''
if 'function ui144RunAction(event)' not in s:
    s += '\n' + runtime + '\n'

app.write_text(s, encoding='utf-8')
print('0.14.4 interaction hotfix applied')
