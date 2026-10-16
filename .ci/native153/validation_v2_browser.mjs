import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import path from 'node:path';

const port=Number(process.env.SRE_V2_BROWSER_PORT||8896);
const appData=path.resolve(process.env.SRE_V2_BROWSER_APP_DATA);
const server=spawn('python',['.ci/native145/serve_runtime.py'],{
  cwd:process.cwd(),
  env:{...process.env,SRE_BROWSER_PORT:String(port),SRE_BROWSER_APP_DATA:appData},
  stdio:['ignore','inherit','inherit'],
});
const stop=()=>{if(!server.killed)server.kill()};
process.on('exit',stop);
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const assert=(x,m)=>{if(!x)throw new Error(m)};
const json=body=>({status:200,contentType:'application/json',body:JSON.stringify(body)});

for(let i=0;i<120;i++){
  try{if((await fetch('http://127.0.0.1:'+port+'/api/health')).ok)break}catch{}
  if(i===119)throw new Error('runtime did not start');
  await sleep(250);
}

let active=false;
let recorded=false;
const portfolioInactive={
  schema:'SRE_VALIDATION_V2_PAPER_STATUS',schema_version:2,active:false,legacy_v1_excluded:true,portfolios:[]
};
const portfolioActive=()=>({
  schema:'SRE_VALIDATION_V2_PAPER_STATUS',schema_version:2,active:true,
  portfolio_id:'SREV2P_TEST',start_session:'2026-10-15',start_production_run_id:'RUN-V2',
  app_version:'0.14.12-validation-v2',starting_capital:100000,cash:recorded?70000:100000,
  nav:100000,realized_pnl:0,unrealized_pnl:0,legacy_v1_excluded:true,
  positions:[],pending_orders:recorded?[{
    order_id:'SREV2O_HINDZINC',symbol:'HINDZINC',side:'BUY',state:'PENDING_NEXT_OPEN',
    signal_session:'2026-10-15',production_run_id:'RUN-V2',reserved_capital:30000
  }]:[],
  journal:recorded?[{
    market_session:'2026-10-15',event_type:'BUY_SIGNAL',symbol:'HINDZINC',
    production_run_id:'RUN-V2',decision:'PENDING_NEXT_OPEN'
  }]:[],
  portfolios:[{portfolio_id:'SREV2P_TEST',start_session:'2026-10-15',status:'ACTIVE'}],
  legacy_validation_v1:{status:'LEGACY_VALIDATION_V1',read_only:true,excluded_from_v2_performance:true}
});
const replay={
  schema:'SRE_VALIDATION_V2_HISTORICAL_REPLAY',label:'POINT-IN-TIME HISTORICAL SIMULATION',status:'COMPLETED',
  requested_range:{start:'2026-09-01',end:'2026-10-15'},
  trustworthy_replayable_range:{start:'2026-09-01',end:'2026-10-15'},
  pit_completeness:{replayable_sessions:30,excluded_sessions:0},
  universe_policy:'CURRENT_UNIVERSE_SURVIVORSHIP_BIAS',survivorship_bias_warning:true,
  execution_assumptions:{starting_capital:100000,whole_shares:true,slippage_bps:10,transaction_cost_bps:5,entry:'NEXT_OFFICIAL_OPEN',exit:'NEXT_OFFICIAL_OPEN',broker_execution:false},
  benchmark:{name:'NIFTY 50',source:'OFFICIAL_INDEX_HISTORY',flat_placeholder:false},
  metrics:{portfolio_return:0.04,benchmark_return:0.03,excess_return:0.01,maximum_drawdown:-0.02,buy_signals:3,filled_entries:2,filled_exits:1,win_rate:1,replayable_sessions:30},
  sessions:[{session:'2026-10-15',pit_status:'FULL_PIT_VALID',universe_size:200,reconstructed_symbols:200,executable_buy_count:2,allocated_buy_count:1,portfolio_nav:104000,benchmark_nav:103000,valuation_quality:'CURRENT_OFFICIAL_MARKS'}]
};

const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});

await page.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()),method=req.method();
  if(url.pathname==='/api/dashboard')return route.fulfill(json({data_source:{mode:'REAL_OFFICIAL_DATA',active:{latest_session:'2026-10-15'}},opportunities:[],positions:[],target_state:{explicit:false},active_run:null}));
  if(url.pathname==='/api/ui-consistency')return route.fulfill(json({analysis_complete:true,latest_official_session:'2026-10-15'}));
  if(url.pathname==='/api/data-source')return route.fulfill(json({mode:'REAL_OFFICIAL_DATA',active:{latest_session:'2026-10-15',stock_files:200,index_files:1}}));
  if(url.pathname==='/api/symbols')return route.fulfill(json({items:[]}));
  if(url.pathname==='/api/opportunities')return route.fulfill(json({items:[],count:0,run:null,target_state:{explicit:false}}));
  if(url.pathname==='/api/capital-plan'&&method==='GET')return route.fulfill(json({latest_run:null}));
  if(url.pathname==='/api/portfolio')return route.fulfill(json({summary:{},items:[]}));
  if(url.pathname==='/api/today')return route.fulfill(json({post_close_daily:{run_status:'READY'},actions:[],action_counts:{},health_counts:{}}));
  if(url.pathname==='/api/history')return route.fulfill(json({prediction_runs:[],monitoring:[]}));
  if(url.pathname==='/api/system')return route.fulfill(json({health:{overall_status:'HEALTHY',checks:[]}}));
  if(url.pathname==='/api/glossary')return route.fulfill(json({items:[]}));
  if(url.pathname==='/api/validation/historical-replay')return route.fulfill(json(replay));
  if(url.pathname==='/api/validation/paper-portfolio'&&method==='GET')return route.fulfill(json(active?portfolioActive():portfolioInactive));
  if(url.pathname==='/api/validation/paper-portfolio/start'&&method==='POST'){active=true;return route.fulfill(json(portfolioActive()))}
  if(url.pathname==='/api/validation/paper-portfolio/record-today'&&method==='POST'){recorded=true;return route.fulfill(json({status:'RECORDED',portfolio:portfolioActive()}))}
  if(url.pathname==='/api/validation/authority')return route.fulfill(json({production_recommendation_authority:'LIVE_DECISION_V1'}));
  return route.fulfill({status:404,contentType:'application/json',body:'{}'});
});

await page.goto('http://127.0.0.1:'+port,{waitUntil:'networkidle'});
await page.locator('.nav-item[data-page="validation"]').click();
await page.waitForTimeout(250);

const replayText=String(await page.locator('#validationReplayPanel').textContent());
assert(replayText.includes('POINT-IN-TIME HISTORICAL SIMULATION'),'V2 replay label missing: '+replayText);
assert(replayText.includes('CURRENT_UNIVERSE_SURVIVORSHIP_BIAS'),'Survivorship warning missing');
assert(replayText.includes('4.00%'),'Portfolio replay metric missing');
assert(replayText.includes('3.00%'),'Actual benchmark metric missing');

await page.locator('#validationPaperTab').click();
await page.waitForTimeout(100);
let paperText=String(await page.locator('#validationPaperPanel').textContent());
assert(paperText.includes('PAPER PORTFOLIO V2'),'V2 paper label missing');
assert(paperText.includes('START NEW PAPER PORTFOLIO'),'Clean start action missing');

page.once('dialog',async dialog=>await dialog.accept('100000'));
await page.locator('#startPaperPortfolio').click();
await page.waitForTimeout(150);
paperText=String(await page.locator('#validationPaperPanel').textContent());
assert(paperText.includes('SREV2P_TEST'),'Portfolio identity missing after start');
assert(paperText.includes('Legacy Validation V1'),'Legacy read-only notice missing');
assert(paperText.includes('RUN-V2'),'Starting production run missing');

await page.locator('#recordPaperToday').click();
await page.waitForTimeout(150);
paperText=String(await page.locator('#validationPaperPanel').textContent());
assert(paperText.includes('HINDZINC'),'Pending BUY not rendered');
assert(paperText.includes('PENDING_NEXT_OPEN'),'Next-open state missing');
assert(paperText.includes('BUY SIGNAL'),'Humanized journal event missing');

assert(errors.length===0,'Browser errors: '+errors.join('\n'));
console.log('0.14.12 VALIDATION V2 BROWSER PASS');
console.log('Clean start PASS; pending next-open PASS; replay truth labels PASS; zero browser errors');
await browser.close();
stop();
