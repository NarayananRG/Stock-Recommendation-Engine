import { chromium } from 'playwright';
import { spawn } from 'node:child_process';

const port = Number(process.env.SRE_V2_E2E_PORT || 8896);
const base = `http://127.0.0.1:${port}`;
const server = spawn('python', ['.ci/native152/validation_v2_e2e_server.py'], {cwd: process.cwd(), env: {...process.env, SRE_V2_E2E_PORT: String(port)}, stdio: ['ignore','inherit','inherit']});
const stop = () => { if (!server.killed) server.kill(); };
process.on('exit', stop);
const assert = (ok, message) => { if (!ok) throw new Error(message); };
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
for(let i=0;i<120;i++){try{if((await fetch(`${base}/api/health`)).ok)break}catch{}if(i===119)throw new Error('Validation V2 FastAPI server did not start');await sleep(250)}

const browser = await chromium.launch({headless:true});
const page = await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
page.on('dialog',d=>d.accept());
await page.route('**/api/**', async route => {
  const path=new URL(route.request().url()).pathname;
  if(path.startsWith('/api/validation/')||path==='/api/health')return route.continue();
  const bodies={
    '/api/data-source':{mode:'REAL_OFFICIAL_DATA',active:{latest_session:'2026-10-15',members:[]}},
    '/api/dashboard':{opportunities:[],positions:[],target_state:{explicit:false},active_run:null},
    '/api/ui-consistency':{},'/api/symbols':{items:[]},'/api/opportunities':{items:[],count:0},
    '/api/portfolio':{summary:{holding_count:0},items:[]},'/api/capital-plan':{},'/api/today':{post_close_daily:{}},
    '/api/history':{prediction_runs:[],monitoring:[]},'/api/system':{health:{checks:[]}},'/api/glossary':{items:[]}
  };
  return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(bodies[path]||{})});
});
await page.goto(base,{waitUntil:'networkidle'});
await page.locator('.nav-item[data-page="validation"]').click();
await page.locator('#validationPaperTab').click();
await page.locator('#startPaperPortfolio').click();
await page.waitForFunction(()=>document.querySelectorAll('#validationPaperPanel table tbody tr').length>=2);
assert((await page.locator('#validationPaperPanel').textContent()).includes('PENDING_NEXT_OPEN'),'Current BUY did not become pending');
const cashBefore=await page.locator('#validationPaperPanel').textContent();
assert(cashBefore.includes('₹1,00,000'),'Signal day reduced cash');
let advance=await fetch(`${base}/api/validation/paper-portfolio/advance?session=2026-10-16`,{method:'POST'}).then(r=>r.json());
assert(advance.fills.length===2,'Next-open fills missing');
let duplicate=await fetch(`${base}/api/validation/paper-portfolio/advance?session=2026-10-16`,{method:'POST'}).then(r=>r.json());
assert(duplicate.duplicate===true,'Second daily flow was not duplicate protected');
await page.evaluate(async()=>renderValidationPaper(await api('/api/validation/paper-portfolio')));
const paperText=await page.locator('#validationPaperPanel').textContent();
assert(paperText.includes('HINDZINC')&&paperText.includes('GODREJCP'),'Current positions not visible');
assert(paperText.includes('Unrealized P&L'),'P&L not visible');
await page.locator('#validationReplayTab').click();
await page.locator('#runHistoricalReplay').click();
await page.waitForFunction(()=>document.querySelector('#validationReplayPanel')?.textContent.includes('2026-10-17'));
const replayText=await page.locator('#validationReplayPanel').textContent();
assert(replayText.includes('Trustworthy replayable range'),'Replayable range missing');
assert(replayText.includes('CURRENT_UNIVERSE_SURVIVORSHIP_BIAS'),'Survivorship warning missing');
assert(await page.locator('.validation-chart polyline').count()===2,'Actual portfolio/NIFTY NAV chart missing');
assert(errors.length===0,`Browser errors: ${errors.join('\n')}`);
console.log('VALIDATION V2 REAL FASTAPI PLAYWRIGHT PASS; browser console errors: 0');
await browser.close();
stop();
