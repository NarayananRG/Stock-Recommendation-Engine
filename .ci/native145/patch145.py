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

  const PAGE_IDS = {
    dashboard: 'dashboardPage',
    opportunities: 'opportunitiesPage',
    portfolio: 'portfolioPage',
    capital: 'capitalPage',
    today: 'todayPage',
    history: 'historyPage',
    system: 'systemPage',
    help: 'helpPage',
    validation: 'validationPage'
  };

  function visibleMessage(message) {
    try {
      if (typeof window.toast === 'function') { window.toast(message); return; }
    } catch (_) {}
    let box = document.getElementById('interactionBootstrapNotice');
    if (!box) {
      box = document.createElement('div');
      box.id = 'interactionBootstrapNotice';
      box.style.cssText = 'position:fixed;right:18px;bottom:18px;z-index:2147483647;padding:10px 14px;border-radius:10px;background:#111827;color:white;font:600 12px system-ui;max-width:420px;box-shadow:0 8px 30px #0003';
      document.body.appendChild(box);
    }
    box.textContent = message;
    setTimeout(() => { if (box) box.remove(); }, 4500);
  }

  function directPage(name) {
    const targetId = PAGE_IDS[name];
    if (!targetId) return false;
    const target = document.getElementById(targetId);
    if (!target) return false;

    Object.values(PAGE_IDS).forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      if (id === targetId) {
        el.classList.remove('hidden');
        el.style.removeProperty('display');
      } else {
        el.classList.add('hidden');
        el.style.setProperty('display', 'none', 'important');
      }
    });
    document.querySelectorAll('.nav-item[data-page]').forEach(node => {
      node.classList.toggle('active', node.dataset.page === name);
    });
    try { window.state && (window.state.page = name); } catch (_) {}
    return true;
  }

  function go(name) {
    try {
      if (typeof window.switchPage === 'function') {
        window.switchPage(name);
        return true;
      }
    } catch (_) {}
    return directPage(name);
  }

  function invoke(name, args = []) {
    try {
      const fn = window[name];
      if (typeof fn !== 'function') return false;
      Promise.resolve(fn(...args)).catch(err => visibleMessage(err?.message || String(err)));
      return true;
    } catch (err) {
      visibleMessage(err?.message || String(err));
      return true;
    }
  }

  function enableCriticalButtons() {
    document.querySelectorAll('button,a,[role="button"]').forEach(el => {
      const text = String(el.textContent || '').trim().toLowerCase();
      if (el.dataset?.browseStocks === 'true' || text.includes('browse stocks')) {
        el.dataset.browseStocks = 'true';
        el.disabled = false;
        el.removeAttribute('disabled');
        el.setAttribute('aria-disabled', 'false');
        el.style.pointerEvents = 'auto';
      }
    });
    ['runMonitoring','runPostCloseDaily','buildCapitalPlan'].forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      el.disabled = false;
      el.removeAttribute('disabled');
      el.setAttribute('aria-disabled','false');
      el.style.pointerEvents = 'auto';
    });
  }

  async function fallbackPostClose() {
    try {
      visibleMessage('Running post-close daily flow...');
      const r = await fetch('/api/post-close-daily-flow?force=false', { method: 'POST' });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.detail || body.message || ('HTTP ' + r.status));
      if (typeof window.renderPostCloseDaily === 'function') window.renderPostCloseDaily(body);
      if (typeof window.loadToday === 'function') await window.loadToday();
      visibleMessage(body.run_status || 'Post-close daily flow finished');
    } catch (err) {
      visibleMessage(err?.message || String(err));
    }
  }

  function handleClick(event) {
    const el = event.target?.closest?.('button,a,[role="button"]');
    if (!el) return;

    const id = el.id || '';
    const text = String(el.textContent || '').trim().toLowerCase();

    if (el.dataset?.browseStocks === 'true' || text.includes('browse stocks')) {
      event.preventDefault();
      event.stopImmediatePropagation();
      enableCriticalButtons();
      if (!go('opportunities')) visibleMessage('Could not open Opportunities.');
      return;
    }

    if (id === 'runMonitoring') {
      event.preventDefault();
      event.stopImmediatePropagation();
      if (!invoke('runMonitoring')) visibleMessage('Position-check handler is unavailable. Please reopen the app.');
      return;
    }

    if (id === 'runPostCloseDaily') {
      event.preventDefault();
      event.stopImmediatePropagation();
      if (!invoke('runPostCloseDaily', [false])) fallbackPostClose();
      return;
    }

    if (id === 'buildCapitalPlan') {
      event.preventDefault();
      event.stopImmediatePropagation();
      if (!invoke('buildCapitalPlan')) visibleMessage('Capital-plan handler is unavailable. Please reopen the app.');
      return;
    }

    if (id === 'heroOpen' && el.dataset?.symbol) {
      event.preventDefault();
      event.stopImmediatePropagation();
      if (!invoke('openStock', [el.dataset.symbol])) visibleMessage('Stock detail handler is unavailable.');
    }
  }

  if (!window.__sreInteractionBootstrap145) {
    window.__sreInteractionBootstrap145 = true;
    document.addEventListener('click', handleClick, true);
    document.addEventListener('DOMContentLoaded', enableCriticalButtons);
    window.addEventListener('load', enableCriticalButtons);
    const observer = new MutationObserver(enableCriticalButtons);
    observer.observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled','data-browse-stocks'] });
    setTimeout(enableCriticalButtons, 0);
    setTimeout(enableCriticalButtons, 500);
    setTimeout(enableCriticalButtons, 1500);
  }
})();
"""
(front / "interaction-bootstrap.js").write_text(bootstrap, encoding="utf-8")

print("0.14.5 runtime interaction bootstrap applied")
