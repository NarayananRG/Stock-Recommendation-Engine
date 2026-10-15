import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import path from 'node:path';

const port=Number(process.env.SRE_01410_BROWSER_PORT||8894);
const appData=path.resolve(process.env.SRE_01410_BROWSER_APP_DATA);
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

const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});

const run={run_id:'presentation-run',market_session:'2026-10-15',capital:10000,horizon_sessions:40,target_return:5};
const uiState={
  analysis_complete:true,stale_active_run:false,latest_official_session:'2026-10-15',
  active_analysis_session:'2026-10-15',active_run_id:run.run_id,
  live_buy_count:2,production_decision_status:'BUY_OPPORTUNITIES_AVAILABLE',
  lane_counts:{momentum_buy:0,recovery_buy:2,both:0,watch:104,avoid:30,no_opportunity:64},
};
const dataSource={mode:'REAL_OFFICIAL_DATA',active:{latest_session:'2026-10-15',stock_files:200,index_files:1,freshness_gate:'PASS',freshness_status:'CURRENT'}};
const dashboard={
  data_source:dataSource,ui_state:uiState,engine_status:{status:'NO_RESULT',latest_session:'2026-10-15'},
  opportunities:[],positions:[],target_state:{explicit:true,value:5},active_run:run
};
const rationale='Revenue direction is improving. PAT direction is improving. EPS direction is improving. Cash-flow evidence is supportive. Balance-sheet evidence is healthy. PIT valuation comparison is attractive. Price is depressed; the cause of the decline is not established by these data. Price is depressed while business, earnings, cash-flow and PIT valuation evidence support recovery. Weak technical momentum increases entry risk without invalidating this thesis. The cause of the decline is not established by these data.';
const plan={
  source_run:run,reused_run:false,
  capital_summary:{
    deployable_capital:10000,estimated_spend:9558,remaining_cash:442,live_universe_size:200,
    live_lane_counts:uiState.lane_counts,
    top_blockers:{
      MOMENTUM_CONFIRMATION_INCOMPLETE:198,
      BUSINESS_EARNINGS_OR_EVENT_EVIDENCE_INSUFFICIENT:192,
      BALANCE_SHEET_NOT_ACCEPTABLE_OR_UNAVAILABLE:107,
      PIT_RELATIVE_VALUATION_UNAVAILABLE:56,
      CASH_FLOW_NOT_SUPPORTIVE_OR_UNAVAILABLE:45,
    },
    unused_cash_explanation:'Whole-share residual.'
  },
  new_buys:[{
    rank:1,symbol:'HINDZINC',shares:18,reference_price:531,estimated_cost:9558,remaining_cash_after:442,
    final_action:'RECOVERY BUY',opportunity_status:'RECOVERY BUY',thesis:rationale,reason_text:rationale,
    confidence:'MEDIUM',technical_state:'WEAK'
  }],
  excluded:[{symbol:'GODREJCP'}]
};
const opportunities=[
 {rank:1,symbol:'HINDZINC',final_action:'RECOVERY BUY',opportunity_status:'RECOVERY BUY',executable:true,executable_qty:18,latest_close:531,
  live_decision:{final_action:'RECOVERY BUY',confidence:'MEDIUM',technical_state:'WEAK',business_health:'STRONG',earnings_direction:'IMPROVING',cash_flow_state:'SUPPORTIVE',balance_sheet_state:'HEALTHY',valuation_state:'ATTRACTIVE',fundamental_event_state:'SUPPORTIVE',fundamental_data_quality:'AVAILABLE',reason_codes:['MOMENTUM_CONFIRMATION_INCOMPLETE']}},
 {rank:2,symbol:'GODREJCP',final_action:'RECOVERY BUY',opportunity_status:'RECOVERY BUY',executable:true,executable_qty:1,latest_close:1100,
  live_decision:{final_action:'RECOVERY BUY',confidence:'MEDIUM',technical_state:'WEAK',business_health:'STRONG',earnings_direction:'IMPROVING',cash_flow_state:'SUPPORTIVE',balance_sheet_state:'HEALTHY',valuation_state:'ATTRACTIVE',fundamental_event_state:'SUPPORTIVE',fundamental_data_quality:'AVAILABLE',reason_codes:['MOMENTUM_CONFIRMATION_INCOMPLETE']}}
];

await page.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()),method=req.method();
  if(url.pathname==='/api/dashboard')return route.fulfill(json(dashboard));
  if(url.pathname==='/api/ui-consistency')return route.fulfill(json(uiState));
  if(url.pathname==='/api/data-source')return route.fulfill(json(dataSource));
  if(url.pathname==='/api/symbols')return route.fulfill(json({items:[{symbol:'HINDZINC',company_name:'Hindustan Zinc'}]}));
  if(url.pathname==='/api/opportunities')return route.fulfill(json({items:opportunities,count:2,run,target_state:{explicit:true,value:5},ui_state:uiState}));
  if(url.pathname==='/api/capital-plan'&&method==='GET')return route.fulfill(json({latest_run:run}));
  if(url.pathname==='/api/capital-plan')return route.fulfill(json(plan));
  if(url.pathname==='/api/portfolio')return route.fulfill(json({summary:{},items:[]}));
  if(url.pathname==='/api/today')return route.fulfill(json({post_close_daily:{run_status:'READY',freshness_gate:'PASS'},actions:[],action_counts:{},health_counts:{},qualified_replacements:0,stale_count:0}));
  if(url.pathname==='/api/history')return route.fulfill(json({prediction_runs:[],monitoring:[]}));
  if(url.pathname==='/api/system')return route.fulfill(json({health:{overall_status:'HEALTHY',checks:[]}}));
  if(url.pathname==='/api/glossary')return route.fulfill(json({items:[]}));
  return route.fulfill({status:404,contentType:'application/json',body:'{}'});
});

await page.goto('http://127.0.0.1:'+port,{waitUntil:'networkidle'});
await page.waitForTimeout(500);

const v1Label=page.getByText('V1 status',{exact:true});
assert(await v1Label.count()===1,'V1 status label missing');
const v1Text=String(await v1Label.locator('..').textContent());
assert(v1Text.includes('2 BUY OPPORTUNITIES'),'Overview still shows legacy NO_RESULT: '+v1Text);
assert(!v1Text.includes('NO_RESULT'),'Legacy NO_RESULT remains visible');

await page.locator('.nav-item[data-page="capital"]').click();
await page.locator('#buildCapitalPlan').click();
await page.waitForTimeout(150);
const summary=String(await page.locator('#capitalLiveSummary').textContent());
assert(summary.includes('Why other stocks were not allocated'),'Deployed-capital blocker heading is wrong: '+summary);
assert(!summary.includes('Why no capital was deployed'),'Old no-deployment heading still shown');

const tableText=String(await page.locator('#capitalTable').textContent());
assert(tableText.includes('Revenue, PAT and EPS trends are improving.'),'Condensed rationale missing');
const phrase='the cause of the decline is not established by these data';
const occurrences=(tableText.toLowerCase().match(new RegExp(phrase,'g'))||[]).length;
assert(occurrences<=1,'Repeated decline-cause sentence remains: '+occurrences);
assert(tableText.includes('Confidence: MEDIUM'),'Confidence metadata missing');
assert(tableText.includes('Technical: WEAK'),'Technical metadata missing');

assert(errors.length===0,'Browser errors: '+errors.join('\\n'));
console.log('0.14.10 PRESENTATION CONSISTENCY BROWSER PASS');
console.log('Overview live status PASS; dynamic capital heading PASS; concise rationale PASS; zero browser errors');
await browser.close();
stop();
