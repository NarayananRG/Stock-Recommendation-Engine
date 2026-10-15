from pathlib import Path
import os
import re

root = Path(os.environ["SRE_ENGINE_ROOT"])

def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(label + " patch point missing")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

replace_once(
    root / "modern_ui" / "api.py",
    'APP_VERSION = "0.14.4-interaction-hotfix"',
    'APP_VERSION = "0.14.5-runtime-interaction-bootstrap"',
    "api version",
)
replace_once(
    root / "stock_app" / "live_decision_v1.py",
    'MODEL = "0.14.4-interaction-hotfix"',
    'MODEL = "0.14.5-runtime-interaction-bootstrap"',
    "model version",
)

replace_once(
    root / "modern_ui" / "frontend" / "app.js",
    "Array.from(document.querySelectorAll('button,a')).filter(e=>/Open stock intelligence/i.test(e.textContent||'')).forEach(e=>{if(!b){e.textContent='Browse stocks ->';e.dataset.browseStocks='true';e.disabled=false;e.removeAttribute('disabled');e.setAttribute('aria-disabled','false')}})",
    "Array.from(document.querySelectorAll('button,a')).filter(e=>e.id==='heroOpen'||e.dataset?.browseStocks==='true'||/Open stock intelligence/i.test(e.textContent||'')).forEach(e=>{if(!b){e.textContent='Browse stocks ->';e.dataset.browseStocks='true';e.disabled=false;e.removeAttribute('disabled');e.setAttribute('aria-disabled','false')}})",
    "zero-BUY hero enabled state",
)
replace_once(
    root / "modern_ui" / "frontend" / "app.js",
    "if(sym){e.preventDefault();e.stopImmediatePropagation();openStock(sym);return}",
    "if(sym){e.preventDefault();e.stopImmediatePropagation();modalClose();openStock(sym);return}",
    "Stock Intelligence modal transition",
)

front = root / "modern_ui" / "frontend"
index = front / "index.html"
h = index.read_text(encoding="utf-8")

tag = '<script src="/assets/interaction-bootstrap.js"></script>'
if tag not in h:
    m = re.search(r'<script[^>]+src=["\'][^"\']*app\.js[^"\']*["\'][^>]*></script>', h, flags=re.I)
    if not m:
        raise RuntimeError("app.js script tag missing")
    h = h[:m.end()] + "\n    " + tag + h[m.end():]
index.write_text(h, encoding="utf-8")

bootstrap = r"""(() => {
  'use strict';

  if (window.__sreInteractionBootstrap145) return;
  window.__sreInteractionBootstrap145 = true;

  // The release overlays use switchPage() for cross-page actions while the
  // canonical frontend exposes setPage(). Bridge those names once, without
  // capture-phase click interception or DOM mutation observers.
  window.switchPage = function switchPage(name) {
    if (typeof window.setPage === 'function') {
      window.setPage(name);
      return true;
    }

    const target = document.getElementById(`page-${name}`);
    if (!target) return false;
    document.querySelectorAll('.page').forEach(page => {
      page.classList.toggle('active-page', page === target);
    });
    document.querySelectorAll('.nav-item[data-page]').forEach(item => {
      item.classList.toggle('active', item.dataset.page === name);
    });
    return true;
  };
})();
"""
(front / "interaction-bootstrap.js").write_text(bootstrap, encoding="utf-8")

print("0.14.5 runtime interaction bootstrap applied")
