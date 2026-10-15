import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(process.env.SRE_ENGINE_ROOT);
const port = Number(process.env.SRE_BROWSER_PORT || 8875);
const appData = path.resolve(process.env.SRE_BROWSER_APP_DATA);
const server = spawn('python', ['.ci/native145/serve_runtime.py'], {
  cwd: process.cwd(),
  env: { ...process.env, SRE_BROWSER_PORT: String(port), SRE_BROWSER_APP_DATA: appData },
  stdio: ['ignore', 'inherit', 'inherit'],
});
const stopServer = () => { if (!server.killed) server.kill(); };
process.on('exit', stopServer);

const assert = (condition, message) => { if (!condition) throw new Error(message); };
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const json = body => ({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
const sha = bytes => createHash('sha256').update(bytes).digest('hex');

for (let attempt = 0; attempt < 120; attempt += 1) {
  try { if ((await fetch(`http://127.0.0.1:${port}/api/health`)).ok) break; } catch {}
  if (attempt === 119) throw new Error('FastAPI runtime did not start');
  await sleep(250);
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const browserErrors = [];
const requests = [];
page.on('pageerror', error => browserErrors.push(`pageerror: ${error.message}`));
page.on('console', message => { if (message.type() === 'error') browserErrors.push(`console: ${message.text()}`); });

const run = { run_id: 'interaction-run', market_session: '2026-10-14', capital: 100000, horizon_sessions: 20, target_return: null };
const rows = Array.from({ length: 30 }, (_, index) => ({
  rank: index + 1,
  symbol: index === 0 ? 'INFY' : `STOCK${String(index + 1).padStart(2, '0')}`,
  opportunity_status: index === 0 ? 'WATCH' : 'NO OPPORTUNITY',
  final_action: index === 0 ? 'WATCH' : 'NO OPPORTUNITY',
  executable: false,
  executable_qty: 0,
  latest_close: 1000 + index,
  live_decision: {
    final_action: index === 0 ? 'WATCH' : 'NO OPPORTUNITY', strategy_style: 'NONE',
    confidence: 'LOW', priority: 'LOW', technical_state: 'NOT READY', executable: false,
    business_health: 'UNAVAILABLE', earnings_direction: 'UNAVAILABLE', cash_flow_state: 'UNAVAILABLE',
    balance_sheet_state: 'UNAVAILABLE', valuation_state: 'UNAVAILABLE', fundamental_event_state: 'UNAVAILABLE',
    fundamental_data_quality: 'UNAVAILABLE', reason_codes: ['FUNDAMENTALS_UNAVAILABLE'], missing_evidence: ['FUNDAMENTALS'],
  },
}));
const dataSource = { mode: 'REAL_FROZEN_HISTORY', active: { path: root, stock_files: 30, index_files: 1, latest_session: '2026-10-14', freshness_gate: 'PASS', freshness_status: 'CURRENT' }, candidates: [] };
const dashboard = { data_source: dataSource, ui_state: { latest_official_session: '2026-10-14' }, engine_status: { latest_session: '2026-10-14' }, opportunities: [], positions: [], target_state: { explicit: false }, active_run: run };
const today = { post_close_daily: { run_status: 'READY', freshness_gate: 'PASS' }, action_counts: {}, health_counts: {}, actions: [{ symbol: 'INFY', action: 'HOLD', thesis_health: 'HEALTHY', reason_codes: [] }], qualified_replacements: 0, stale_count: 0 };
const stock = {
  symbol: 'INFY', quote: { date: '2026-10-14', close: 1000, open: 990, high: 1010, low: 980, volume: 100000, change: 10, change_pct: 1, high_52w: 1100, low_52w: 800 },
  history: { source_mode: 'REAL_FROZEN_HISTORY', first_session: '2026-10-13', last_session: '2026-10-14', bars_returned: 2 },
  bars: [{ date: '2026-10-13', open: 980, high: 1000, low: 970, close: 990, volume: 90000 }, { date: '2026-10-14', open: 990, high: 1010, low: 980, close: 1000, volume: 100000 }],
  overlays: [], performance: {}, prediction: {}, recommendation: {}, live_decision: null, technical_v2: {}, fundamental_v3: {}, combined_v2: {}, active_run: run,
};

await page.route('**/api/**', async route => {
  const request = route.request();
  const url = new URL(request.url());
  const key = `${request.method()} ${url.pathname}`;
  requests.push(key);
  const method = request.method();
  if (url.pathname === '/api/data-source') return route.fulfill(json(dataSource));
  if (url.pathname === '/api/dashboard') return route.fulfill(json(dashboard));
  if (url.pathname === '/api/ui-consistency') return route.fulfill(json({ analysis_complete: true, latest_official_session: '2026-10-14', lane_counts: { momentum_buy: 0, recovery_buy: 0, both: 0, watch: 1 } }));
  if (url.pathname === '/api/symbols') return route.fulfill(json({ items: [{ symbol: 'INFY', company_name: 'Infosys' }] }));
  if (url.pathname === '/api/opportunities/run') return route.fulfill(json({ items: rows, count: rows.length, run, target_state: { explicit: false }, reused_run: false }));
  if (url.pathname === '/api/opportunities') return route.fulfill(json({ items: rows, count: rows.length, run, target_state: { explicit: false } }));
  if (url.pathname === '/api/portfolio' && method === 'GET') return route.fulfill(json({ summary: { holding_count: 1, priced_count: 1 }, items: [{ id: 1, symbol: 'INFY', quantity: 1, buy_price: 900, latest_close: 1000, current_value: 1000, pnl_pct: 11.1, position_status: 'OPEN' }] }));
  if (url.pathname === '/api/portfolio') return route.fulfill(json({ ok: true }));
  if (url.pathname === '/api/capital-plan' && method === 'GET') return route.fulfill(json({ latest_run: run }));
  if (url.pathname === '/api/capital-plan') return route.fulfill(json({ source_run: run, reused_run: false, capital_summary: { deployable_capital: 100000, estimated_spend: 1000, remaining_cash: 99000, live_universe_size: 30, live_lane_counts: {}, top_blockers: {}, unused_cash_explanation: 'Qualification-driven cash retention.' }, new_buys: [{ rank: 1, symbol: 'INFY', shares: 1, reference_price: 1000, estimated_cost: 1000, remaining_cash_after: 99000 }], excluded: [] }));
  if (url.pathname === '/api/today/run') return route.fulfill(json(today));
  if (url.pathname === '/api/today') return route.fulfill(json(today));
  if (url.pathname === '/api/post-close-daily-flow') return route.fulfill(json({ run_status: 'COMPLETE', freshness_gate: 'PASS' }));
  if (url.pathname === '/api/history') return route.fulfill(json({ prediction_runs: [], monitoring: [] }));
  if (url.pathname === '/api/system') return route.fulfill(json({ health: { overall_status: 'HEALTHY', checks: [] } }));
  if (url.pathname === '/api/system/backup') return route.fulfill(json({ path: 'test-backup' }));
  if (url.pathname === '/api/system/support-bundle') return route.fulfill(json({ path: 'test-support' }));
  if (url.pathname === '/api/glossary') return route.fulfill(json({ items: [{ category: 'Test', term: 'BUY', definition: 'Qualified action', where: 'Opportunities' }] }));
  if (url.pathname.startsWith('/api/stocks/')) return route.fulfill(json(stock));
  if (url.pathname === '/api/validation/historical-replay') return route.fulfill(json({ metrics: {}, pit_audit: {}, sessions: [] }));
  if (url.pathname === '/api/validation/paper-portfolio/start') return route.fulfill(json({ active: true }));
  if (url.pathname === '/api/validation/paper-portfolio') return route.fulfill(json({ active: false }));
  return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
});

const base = `http://127.0.0.1:${port}`;
await page.goto(base, { waitUntil: 'networkidle' });
await page.waitForTimeout(700);

const manifest = JSON.parse(fs.readFileSync(path.join(root, 'release-frontend-manifest.json'), 'utf8'));
for (const [name, expected] of Object.entries(manifest.files)) {
  const served = Buffer.from(await (await fetch(`${base}/assets/${name}`)).arrayBuffer());
  assert(sha(served) === expected, `Served ${name} differs from release manifest`);
  assert(sha(fs.readFileSync(path.join(root, 'modern_ui', 'frontend', name))) === expected, `Local ${name} differs from release manifest`);
}

assert((await page.locator('#heroDecision').textContent()).includes('NO EXECUTABLE BUY'), 'zero-BUY overview state missing');
assert((await page.locator('#heroOpen').textContent()).includes('Browse stocks'), 'Browse stocks label missing');
assert(await page.locator('#heroOpen').isEnabled(), 'Browse stocks is disabled');
await page.locator('#heroOpen').click();
await page.waitForTimeout(150);
assert(await page.locator('#page-opportunities').evaluate(el => el.classList.contains('active-page')), 'Browse stocks did not open Opportunities');
assert(await page.locator('.nav-item[data-page="opportunities"]').evaluate(el => el.classList.contains('active')), 'Opportunities sidebar state not active');
assert(await page.locator('#opportunityTable').isVisible(), 'Opportunities table not visible');

await page.locator('#runOpportunities').click();
await page.locator('#oppSearch').fill('INFY');
assert((await page.locator('#opportunityCount').textContent()).startsWith('1 rows'), 'Opportunities search did not filter');
await page.locator('#oppSearch').fill('');
await page.locator('#oppSort').selectOption('symbol');
await page.locator('#oppSortDir').click();
await page.locator('[data-opp-filter="watch"]').click();
assert((await page.locator('#opportunityCount').textContent()).startsWith('1 rows'), 'Watch filter did not apply');
await page.locator('[data-opp-filter="all"]').click();
assert(await page.locator('#oppNext').isEnabled(), 'Opportunities pagination next button disabled unexpectedly');
await page.locator('#oppNext').click();
assert((await page.locator('#oppPageLabel').textContent()).includes('Page 2'), 'Opportunities pagination did not advance');
await page.locator('#oppPrev').click();
await page.locator('#oppSearch').fill('INFY');
await page.locator('[data-opportunity-details="INFY"]').click();
assert(await page.locator('#modal').isVisible(), 'Opportunity Details modal did not open');
await page.locator('[data-open-stock-intelligence="INFY"]').click();
await page.waitForTimeout(150);
assert(await page.locator('#page-stock').evaluate(el => el.classList.contains('active-page')), 'Stock Intelligence did not open');
assert((await page.locator('#stockSymbol').textContent()) === 'INFY', 'Stock Intelligence symbol mismatch');
await page.locator('#stockBack').click();

for (const name of ['dashboard', 'opportunities', 'portfolio', 'capital', 'today', 'history', 'system', 'help']) {
  await page.locator(`.nav-item[data-page="${name}"]`).click();
  await page.waitForTimeout(80);
  assert(await page.locator(`#page-${name}`).evaluate(el => el.classList.contains('active-page')), `Sidebar ${name} did not activate its page`);
}

await page.locator('.nav-item[data-page="portfolio"]').click();
await page.locator('#refreshPortfolio').click();
await page.locator('#addHolding').click();
assert(await page.locator('#modal').isVisible(), 'Add holding modal did not open');
await page.locator('[data-modal-close]').last().click();
await page.locator('#portfolioTable [data-symbol="INFY"]').click();
await page.waitForTimeout(100);
assert((await page.locator('#stockSymbol').textContent()) === 'INFY', 'Portfolio stock link did not open Stock Intelligence');

await page.locator('.nav-item[data-page="capital"]').click();
await page.locator('#buildCapitalPlan').click();
await page.waitForTimeout(100);
assert(requests.includes('POST /api/capital-plan'), 'Build Capital Plan did not trigger its POST');
await page.locator('#capitalTable [data-symbol="INFY"]').click();
await page.waitForTimeout(100);
assert((await page.locator('#stockSymbol').textContent()) === 'INFY', 'Capital Plan stock action did not open Stock Intelligence');

await page.locator('.nav-item[data-page="today"]').click();
await page.locator('#runMonitoring').click();
await page.locator('#runPostCloseDaily').click();
await page.waitForTimeout(150);
assert(requests.includes('POST /api/today/run'), 'Run position check did not trigger');
assert(requests.includes('POST /api/post-close-daily-flow'), 'Post-close daily flow did not trigger');

await page.locator('.nav-item[data-page="history"]').click();
await page.locator('#refreshHistory').click();
await page.locator('.nav-item[data-page="system"]').click();
await page.locator('#refreshSystem').click();
await page.locator('#createBackup').click();
await page.locator('#createSupportBundle').click();
await page.locator('.nav-item[data-page="help"]').click();
await page.locator('#glossarySearch').fill('BUY');

await page.locator('.nav-item[data-page="validation"]').click();
await page.waitForTimeout(150);
assert(await page.locator('#validationPage').isVisible(), 'Validation route did not open');
await page.locator('#validationPaperTab').click();
await page.locator('#startPaperPortfolio').click();
await page.locator('#validationReplayTab').click();
await page.locator('#runHistoricalReplay').click();
assert(requests.includes('POST /api/validation/paper-portfolio/start'), 'Prospective tracking did not start');
assert(requests.includes('POST /api/validation/historical-replay'), 'Historical replay did not trigger');

await page.locator('.nav-item[data-page="dashboard"]').click();
await page.locator('#topRefresh').click();
await page.locator('#globalSearch').fill('INFY');
await page.waitForTimeout(100);
await page.locator('.search-result').first().click();
await page.waitForTimeout(100);
assert((await page.locator('#stockSymbol').textContent()) === 'INFY', 'Global search did not open Stock Intelligence');

assert(browserErrors.length === 0, `Browser errors:\n${browserErrors.join('\n')}`);
console.log('REAL FRONTEND INTERACTION PASS');
console.log('Browse stocks PASS; sidebar PASS; Opportunities PASS; Portfolio PASS; Capital Plan PASS; Today PASS; Validation PASS; Stock Intelligence PASS; zero browser errors');

await browser.close();
stopServer();
