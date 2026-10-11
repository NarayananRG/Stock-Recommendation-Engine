from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])

def repl(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"{label} contract missing")
    return text.replace(old, new, 1)

# Fix implementation details in the Phase 4 core engine before validation.
tech = root / "stock_app" / "technical_v2.py"
tt = tech.read_text(encoding="utf-8")
tt = tt.replace(
    'if i == 0 or not math.isfinite(float(atr.iloc[i])) if pd.notna(atr.iloc[i]) else True:',
    'if i == 0 or pd.isna(atr.iloc[i]) or not math.isfinite(float(atr.iloc[i])):'
)
tt = tt.replace(
    'positive_candle = [name for name in ("BullishEngulfing", "Hammer") if bool(row.get(name)) if pd.notna(row.get(name))]',
    'positive_candle = [name for name in ("BullishEngulfing", "Hammer") if pd.notna(row.get(name)) and bool(row.get(name))]'
)
tt = tt.replace(
    'negative_candle = [name for name in ("BearishEngulfing", "ShootingStar") if bool(row.get(name)) if pd.notna(row.get(name))]',
    'negative_candle = [name for name in ("BearishEngulfing", "ShootingStar") if pd.notna(row.get(name)) and bool(row.get(name))]'
)
tech.write_text(tt, encoding="utf-8")

# ---------------- API integration ----------------
api = root / "modern_ui" / "api.py"
text = api.read_text(encoding="utf-8")
text = repl(
    text,
    'APP_VERSION = "0.9.13-capital-plan-v3"',
    'APP_VERSION = "0.10.0-phase4-technical-v2"',
    "Phase 4 app version",
)

stock_anchor = '''    def stock_context(self, symbol: str, limit: int) -> dict[str, Any]:
'''
technical_helper = '''    def technical_v2_context(self, symbol: str, bars: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        import pandas as _pd
        from stock_app.technical_v2 import analyze

        symbol = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        source_bars = list(bars) if bars is not None else self.prices.history(symbol, limit=5000)
        if not source_bars:
            return {
                "schema": "SRE_TECHNICAL_INTELLIGENCE_V2",
                "authority": "SHADOW_ONLY",
                "status": "NO_DATA",
                "technical_score": None,
            }

        benchmark_bars = []
        for index_symbol in ("INDEX_NSEI", "NSEI", "^NSEI", "NIFTY"):
            try:
                candidate = self.prices.history(index_symbol, limit=5000)
            except Exception:
                candidate = []
            if candidate:
                benchmark_bars = candidate
                break

        vix_bars = []
        for vix_symbol in ("INDEX_INDIAVIX", "INDIAVIX", "INDIA_VIX"):
            try:
                candidate = self.prices.history(vix_symbol, limit=1500)
            except Exception:
                candidate = []
            if candidate:
                vix_bars = candidate
                break

        active = self.latest_run_input() or {}
        horizon = int(active.get("horizon_sessions") or 20)
        return analyze(
            _pd.DataFrame(source_bars),
            _pd.DataFrame(benchmark_bars) if benchmark_bars else None,
            horizon_sessions=horizon,
            india_vix=_pd.DataFrame(vix_bars) if vix_bars else None,
        )

'''
if technical_helper not in text:
    if stock_anchor not in text:
        raise RuntimeError("Phase 4 stock-context insertion point missing")
    text = text.replace(stock_anchor, technical_helper + stock_anchor, 1)

stock_return_anchor = '''            "positions": [dict(x) for x in positions],
            "overlays": overlays,
        }
'''
stock_return_new = '''            "positions": [dict(x) for x in positions],
            "overlays": overlays,
            "technical_v2": self.technical_v2_context(symbol, bars),
        }
'''
text = repl(text, stock_return_anchor, stock_return_new, "Phase 4 stock-context return")

route_anchor = '''    @app.get("/api/stocks/{symbol}")
    def stock(symbol: str, limit: int = Query(1300, ge=60, le=5000)) -> dict[str, Any]:
        return ctx.stock_context(symbol, limit)

'''
route_new = '''    @app.get("/api/stocks/{symbol}")
    def stock(symbol: str, limit: int = Query(1300, ge=60, le=5000)) -> dict[str, Any]:
        return ctx.stock_context(symbol, limit)

    @app.get("/api/stocks/{symbol}/technical-v2")
    def stock_technical_v2(symbol: str) -> dict[str, Any]:
        return ctx.technical_v2_context(symbol)

'''
text = repl(text, route_anchor, route_new, "Phase 4 technical endpoint")
api.write_text(text, encoding="utf-8")

# ---------------- Stock Intelligence UI ----------------
html = root / "modern_ui" / "frontend" / "index.html"
h = html.read_text(encoding="utf-8")
rail_anchor = '''            <article class="intel-card"><div class="intel-label">EVIDENCE</div><div id="evidenceTags" class="evidence-tags"></div></article>
          </aside>
        </div>
      </section>
'''
technical_panel = '''            <article class="intel-card"><div class="intel-label">EVIDENCE</div><div id="evidenceTags" class="evidence-tags"></div></article>
          </aside>
        </div>

        <article id="technicalV2Panel" class="panel-card technical-v2-panel">
          <div class="panel-head">
            <div><span class="card-label">TECHNICAL INTELLIGENCE V2</span><h3>Current setup, multi-timeframe confirmation &amp; historical analogues</h3></div>
            <div class="phase4-head-status"><span id="technicalV2Authority" class="status-pill neutral">SHADOW ONLY</span><strong id="technicalV2Score">—</strong><span>/100</span></div>
          </div>
          <div class="technical-v2-summary"><strong id="technicalV2Label">Waiting for stock data</strong><span id="technicalV2Coverage">—</span><div class="technical-v2-scorebar"><span id="technicalV2ScoreFill"></span></div></div>
          <div id="technicalV2Grid" class="technical-v2-grid"></div>
          <div class="technical-v2-foot">
            <div><span class="card-label">REGIME-CONDITIONED ANALOGUES</span><strong id="technicalV2Analogue">—</strong><span id="technicalV2AnalogueDetail">—</span></div>
            <div><span class="card-label">PROMOTION STATE</span><strong>SHADOW / EXPLANATORY</strong><span>Does not change the validated recommendation or allocator authority.</span></div>
          </div>
        </article>
      </section>
'''
h = repl(h, rail_anchor, technical_panel, "Phase 4 Stock Intelligence panel")
html.write_text(h, encoding="utf-8")

js = root / "modern_ui" / "frontend" / "app.js"
t = js.read_text(encoding="utf-8")
render_line = '''  renderPerformance(d.performance||{}); renderDecision(d.prediction,d.recommendation); renderLevels(d.overlays||[]); renderEvidence(d.prediction);
'''
render_new = '''  renderPerformance(d.performance||{}); renderDecision(d.prediction,d.recommendation); renderLevels(d.overlays||[]); renderEvidence(d.prediction); renderTechnicalV2(d.technical_v2||{});
'''
t = repl(t, render_line, render_new, "Phase 4 renderStock hook")

evidence_anchor = '''function renderEvidence(pred){
  const ev=pred?.evidence||{}; const tags=[];
  if(pred?.confidence_label)tags.push(pred.confidence_label);
  if(pred?.sample_size)tags.push(`${pred.sample_size} analogues`);
  if(ev.positive_terminal_outcomes!=null)tags.push(`${ev.positive_terminal_outcomes} positive outcomes`);
  if(pred?.target_status)tags.push(pred.target_status); if(pred?.v1_status)tags.push(pred.v1_status);
  $('#evidenceTags').innerHTML=(tags.length?tags:['No latest evidence row']).map(x=>`<span class="evidence-tag">${escapeHtml(x)}</span>`).join('');
}
'''
technical_renderer = r'''function renderEvidence(pred){
  const ev=pred?.evidence||{}; const tags=[];
  if(pred?.confidence_label)tags.push(pred.confidence_label);
  if(pred?.sample_size)tags.push(`${pred.sample_size} analogues`);
  if(ev.positive_terminal_outcomes!=null)tags.push(`${ev.positive_terminal_outcomes} positive outcomes`);
  if(pred?.target_status)tags.push(pred.target_status); if(pred?.v1_status)tags.push(pred.v1_status);
  $('#evidenceTags').innerHTML=(tags.length?tags:['No latest evidence row']).map(x=>`<span class="evidence-tag">${escapeHtml(x)}</span>`).join('');
}
function techNum(v,d=2){return v==null||!Number.isFinite(+v)?'—':Number(v).toFixed(d)}
function techPct(v,d=2){return v==null||!Number.isFinite(+v)?'—':`${Number(v)>=0?'+':''}${Number(v).toFixed(d)}%`}
function renderTechnicalV2(x){
  const panel=$('#technicalV2Panel'); if(!panel)return;
  const score=Number.isFinite(+x.technical_score)?+x.technical_score:null;
  $('#technicalV2Score').textContent=score==null?'—':score.toFixed(0);
  $('#technicalV2Label').textContent=(x.technical_label||x.status||'UNAVAILABLE').replaceAll('_',' ');
  $('#technicalV2Coverage').textContent=`Evidence coverage ${x.evidence_coverage!=null?Math.round(+x.evidence_coverage*100)+'%':'—'} · as of ${x.as_of_session||'—'}`;
  $('#technicalV2Authority').textContent=x.authority||'SHADOW ONLY';
  $('#technicalV2ScoreFill').style.width=`${Math.max(0,Math.min(100,score??0))}%`;
  const trend=x.trend||{},mom=x.momentum||{},vol=x.volatility||{},flow=x.volume_flow||{},st=x.structure||{},rs=x.relative_strength||{},mt=x.multi_timeframe||{},mc=x.market_context||{},c=x.candlestick||{};
  const patterns=[...(c.positive_patterns||[]),...(c.negative_patterns||[])].map(v=>String(v).replace(/([a-z])([A-Z])/g,'$1 $2')).join(', ')||'No major candle pattern';
  const cells=[
    ['Trend',`EMA20 ${fmtMoney(trend.ema20)} · EMA50 ${fmtMoney(trend.ema50)} · EMA200 ${fmtMoney(trend.ema200)}`,`${trend.supertrend_direction||'—'} Supertrend · EMA50 slope ${techPct(trend.ema50_slope_5d_pct)}`],
    ['Momentum',`RSI ${techNum(mom.rsi14,1)} · ADX ${techNum(mom.adx14,1)}`,`MACD hist ${techNum(mom.macd_hist,3)} · ROC20 ${techPct(mom.roc20_pct)}`],
    ['Stochastic / DMI',`%K ${techNum(mom.stoch_k14,1)} · %D ${techNum(mom.stoch_d3,1)}`,`+DI ${techNum(mom.plus_di14,1)} · −DI ${techNum(mom.minus_di14,1)}`],
    ['Volatility',`ATR ${techNum(vol.atr_pct)}% · RV20 ${techNum(vol.realized_vol_20d_pct)}%`,`BB width ${techNum(vol.bb_bandwidth_pct)}% · compression ${vol.compression===true?'YES':vol.compression===false?'NO':'—'}`],
    ['Volume flow',`CMF20 ${techNum(flow.cmf20,3)} · OBV slope ${techNum(flow.obv_slope10_pct)}%`,`A/D slope ${techNum(flow.ad_line_slope10,0)}`],
    ['Structure',`Support ${fmtMoney(st.support20)} · Resistance ${fmtMoney(st.resistance20)}`,`Breakout ${st.breakout20===true?'YES':'NO'} · retest ${st.retest20===true?'YES':'NO'}`],
    ['Relative strength',`vs NIFTY 20D ${techPct(rs.rs20_vs_nifty)} · 60D ${techPct(rs.rs60_vs_nifty)}`,rs.available?`vs sector 20D ${techPct(rs.rs20_vs_sector)}`:'Sector index unavailable'],
    ['Weekly confirmation',`RSI ${techNum(mt.weekly_rsi14,1)} · MACD hist ${techNum(mt.weekly_macd_hist,3)}`,`${mt.weekly_trend_confirmed===true?'CONFIRMED':mt.weekly_trend_confirmed===false?'NOT CONFIRMED':'—'} · prior completed week`],
    ['Candlestick',patterns,`Body ${techNum(c.body_pct_of_range,1)}% · upper wick ${techNum(c.upper_wick_pct_of_range,1)}% · lower wick ${techNum(c.lower_wick_pct_of_range,1)}%`],
    ['Market regime',`NIFTY ${mc.nifty_regime||'UNAVAILABLE'}`,mc.india_vix?.available?`India VIX ${techNum(mc.india_vix.close,2)} · ${mc.india_vix.regime}`:'India VIX unavailable']
  ];
  $('#technicalV2Grid').innerHTML=cells.map(([title,main,sub])=>`<div class="technical-v2-cell"><span>${escapeHtml(title)}</span><strong>${main}</strong><small>${sub}</small></div>`).join('');
  const a=x.historical_analogues||{};
  $('#technicalV2Analogue').textContent=a.status==='READY'||a.status==='LOW_SAMPLE'?`${a.sample_size||0} analogues · median ${fmtPctFraction(a.median_forward_return)}`:(a.status||'UNAVAILABLE').replaceAll('_',' ');
  $('#technicalV2AnalogueDetail').textContent=a.sample_size?`Positive rate ${fmtPctFraction(a.positive_rate)} · similarity ${a.similarity!=null?Math.round(+a.similarity*100)+'%':'—'} · ${a.confidence||'LOW'} confidence · ${a.regime||'—'} regime`:'Needs enough closed historical outcomes for the selected horizon.';
}
'''
t = repl(t, evidence_anchor, technical_renderer, "Phase 4 technical renderer")
js.write_text(t, encoding="utf-8")

css = root / "modern_ui" / "frontend" / "styles.css"
c = css.read_text(encoding="utf-8")
if ".technical-v2-panel" not in c:
    c += r'''
/* Phase 4 Technical Intelligence V2 */
.technical-v2-panel{margin-top:18px;padding:22px}
.phase4-head-status{display:flex;align-items:center;gap:8px}.phase4-head-status>strong{font-size:28px}.phase4-head-status>span:last-child{font-size:12px;opacity:.6}
.technical-v2-summary{display:grid;grid-template-columns:minmax(180px,1fr) auto;gap:8px 18px;align-items:center;margin:12px 0 18px}
.technical-v2-scorebar{grid-column:1/-1;height:7px;border-radius:999px;background:rgba(120,128,150,.14);overflow:hidden}.technical-v2-scorebar span{display:block;height:100%;width:0;background:linear-gradient(90deg,#6657ef,#7b61ff);border-radius:999px;transition:width .25s ease}
.technical-v2-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}
.technical-v2-cell{min-height:106px;padding:14px;border:1px solid rgba(120,128,150,.14);border-radius:14px;background:rgba(255,255,255,.38);display:flex;flex-direction:column;gap:7px}
.technical-v2-cell>span{font-size:10px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;opacity:.56}.technical-v2-cell>strong{font-size:13px;line-height:1.45}.technical-v2-cell>small{font-size:11px;line-height:1.4;opacity:.65}
.technical-v2-foot{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}.technical-v2-foot>div{padding:14px;border-radius:14px;background:rgba(120,128,150,.07);display:grid;gap:5px}.technical-v2-foot strong{font-size:13px}.technical-v2-foot span:last-child{font-size:11px;opacity:.65}
@media(max-width:1200px){.technical-v2-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:760px){.technical-v2-grid,.technical-v2-foot{grid-template-columns:1fr}}
'''
css.write_text(c, encoding="utf-8")

assert "0.10.0-phase4-technical-v2" in api.read_text(encoding="utf-8")
assert "technical_v2" in api.read_text(encoding="utf-8")
assert "technicalV2Panel" in html.read_text(encoding="utf-8")
assert "renderTechnicalV2" in js.read_text(encoding="utf-8")
print("Phase 4 Technical Intelligence V2 API/UI integration applied")
