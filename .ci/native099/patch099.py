from pathlib import Path
import os

root = Path(os.environ['SRE_ENGINE_ROOT'])

def repl(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f'{label} patch point missing')
    return text.replace(old, new, 1)

# stock_app/allocation.py
p = root / 'stock_app' / 'allocation.py'
s = p.read_text(encoding='utf-8')
s = repl(s,
    'POLICY_VERSION = "LEG6_PORTFOLIO_ALLOCATION_POLICY_V1"',
    'POLICY_VERSION = "LEG6_PORTFOLIO_ALLOCATION_POLICY_V2_SMALL_CAP_SINGLE_STOCK"',
    'policy version')
s = repl(s,
    '''    "SECTOR_CONCENTRATION_LIMIT": "Deferred to avoid exceeding the sector concentration limit.",
}''',
    '''    "SECTOR_CONCENTRATION_LIMIT": "Deferred to avoid exceeding the sector concentration limit.",
    "SINGLE_ELIGIBLE_FULL_CAPITAL": "Only one new model-executable stock is cash-affordable, so the normal concentration cap is relaxed for that stock; whole shares, available-cash and no-leverage rules still apply.",
}''',
    'reason label')
s = repl(s,
    '''        "max_position_capital_fraction": MAX_POSITION_CAPITAL_FRACTION,
        "max_sector_exposure_fraction": MAX_SECTOR_EXPOSURE_FRACTION,''',
    '''        "max_position_capital_fraction": MAX_POSITION_CAPITAL_FRACTION,
        "single_eligible_stock_exception": True,
        "single_eligible_stock_max_capital_fraction": 1.0,
        "single_eligible_stock_rule": "If exactly one new model-executable candidate is cash-affordable, the normal per-stock concentration cap is relaxed up to available deployable cash; whole shares and no leverage still apply.",
        "max_sector_exposure_fraction": MAX_SECTOR_EXPOSURE_FRACTION,''',
    'policy fields')
s = repl(s,
    '''    max_abs_correlation_to_holdings: float | None
    source_decision: str
''',
    '''    max_abs_correlation_to_holdings: float | None
    source_decision: str
    single_stock_exception_applied: bool = False
''',
    'allocation row')
anchor = '''    def allocate(self, request: AllocationRequest, candidates: list[AllocationInput], holdings: list[Holding] | None = None) -> dict[str, Any]:
'''
helper = '''    def execution_preview(self, request: AllocationRequest, candidates: list[AllocationInput], holdings: list[Holding] | None = None) -> dict[str, dict[str, Any]]:
        # Exact same allocation policy used by Capital Plan, exposed to Opportunities.
        result = self.allocate(request, candidates, holdings)
        preview: dict[str, dict[str, Any]] = {}
        for row in result.get("rows", []):
            price = _float_or_none(row.get("reference_price"))
            cash_affordable_qty = 0 if price is None or price <= 0 else int(request.deployable_capital // price)
            preview[normalize_symbol(row.get("symbol", ""))] = {
                "cash_affordable": cash_affordable_qty > 0,
                "cash_affordable_qty": cash_affordable_qty,
                "executable": row.get("action") == "BUY",
                "executable_qty": int(row.get("shares") or 0),
                "execution_action": row.get("action"),
                "execution_reason_code": row.get("reason_code"),
                "execution_reason": explain_reason_code(str(row.get("reason_code") or "")),
                "single_stock_exception_applied": bool(row.get("single_stock_exception_applied")),
            }
        return preview

'''
if helper not in s:
    if anchor not in s:
        raise RuntimeError('execution preview insertion point missing')
    s = s.replace(anchor, helper + anchor, 1)
s = repl(s,
    '''        cash = request.deployable_capital
        rows: list[AllocationRow] = []
        buys: list[AllocationRow] = []

        for candidate in sorted(candidates, key=lambda c: (c.rank, c.symbol)):
''',
    '''        cash = request.deployable_capital
        rows: list[AllocationRow] = []
        buys: list[AllocationRow] = []

        # If exactly one NEW model-executable candidate is cash-affordable,
        # relax the normal 35% position cap for that stock only.
        viable_new_symbols: list[str] = []
        for candidate in sorted(candidates, key=lambda c: (c.rank, c.symbol)):
            if candidate.symbol in held_symbols or not self._is_executable(candidate):
                continue
            price = candidate.latest_close
            if price is None:
                price, _ = self.history.latest_close(candidate.symbol)
            if price is not None and price > 0 and int(request.deployable_capital // price) >= 1:
                viable_new_symbols.append(candidate.symbol)
        single_eligible_symbol = viable_new_symbols[0] if len(viable_new_symbols) == 1 else None

        for candidate in sorted(candidates, key=lambda c: (c.rank, c.symbol)):
''',
    'single eligible pool')
s = repl(s,
    '''                "source_decision": candidate.opportunity_status,
            }
''',
    '''                "source_decision": candidate.opportunity_status,
                "single_stock_exception_applied": False,
            }
''',
    'row common')
s = repl(s,
    '''            position_budget = min(cash, request.deployable_capital * MAX_POSITION_CAPITAL_FRACTION)
            qty = int(position_budget // price)
''',
    '''            single_stock_exception = candidate.symbol == single_eligible_symbol
            position_budget = cash if single_stock_exception else min(cash, request.deployable_capital * MAX_POSITION_CAPITAL_FRACTION)
            qty = int(position_budget // price)
''',
    'position budget')
s = repl(s,
    '''            proposed_buys = buys + [AllocationRow(action="BUY", shares=qty, estimated_cost=cost, remaining_cash_after=round(cash - cost, 2), reason_code="WHOLE_SHARE_AFFORDABLE", existing_holding=False, **common)]
''',
    '''            buy_common = dict(common)
            buy_common["single_stock_exception_applied"] = single_stock_exception
            reason_code = "SINGLE_ELIGIBLE_FULL_CAPITAL" if single_stock_exception else "WHOLE_SHARE_AFFORDABLE"
            proposed_buys = buys + [AllocationRow(action="BUY", shares=qty, estimated_cost=cost, remaining_cash_after=round(cash - cost, 2), reason_code=reason_code, existing_holding=False, **buy_common)]
''',
    'buy row')
s = repl(s,
    '''            "capital_summary": {
                "deployable_capital": request.deployable_capital,
''',
    '''            "capital_summary": {
                "deployable_capital": request.deployable_capital,
                "normal_position_cap_fraction": MAX_POSITION_CAPITAL_FRACTION,
                "single_eligible_stock_exception_available": True,
                "single_eligible_symbol": single_eligible_symbol,
''',
    'capital summary')
p.write_text(s, encoding='utf-8')

# stock_app/historical.py - market index is context, never an equity recommendation candidate
p = root / 'stock_app' / 'historical.py'
s = p.read_text(encoding='utf-8')
s = repl(s,
    '''            for path in sorted(root.glob("*.csv")):
                symbol = path.stem.replace(".NS", "")
                if symbol in seen:
                    continue
''',
    '''            for path in sorted(root.glob("*.csv")):
                raw_stem = path.stem.upper()
                symbol = raw_stem.replace(".NS", "").replace(".BO", "")
                if raw_stem.startswith("INDEX_") or symbol.startswith("INDEX_") or symbol in {"NSEI", "NIFTY", "NIFTY50", "NIFTY_50"}:
                    continue
                if symbol in seen:
                    continue
''',
    'equity universe')
p.write_text(s, encoding='utf-8')

# modern_ui/api.py
p = root / 'modern_ui' / 'api.py'
s = p.read_text(encoding='utf-8')
s = repl(s,
    'APP_VERSION = "0.9.8-correctness-state"',
    'APP_VERSION = "0.9.9-allocation-executability-v2"',
    'app version')
anchor = '''    def _inspect_data_repo(self, root: Path) -> dict[str, Any]:
'''
helper = '''    @staticmethod
    def _history_file_kind(path: Path) -> str:
        name = path.name.upper()
        stem = path.stem.upper().replace(".NS", "").replace(".BO", "")
        if name.startswith("INDEX_") or stem.startswith("INDEX_") or stem in {"NSEI", "NIFTY", "NIFTY50", "NIFTY_50"}:
            return "INDEX"
        return "EQUITY"

'''
if helper not in s:
    if anchor not in s:
        raise RuntimeError('history classifier insertion point missing')
    s = s.replace(anchor, helper + anchor, 1)
s = repl(s,
    '''        files: list[Path] = []
        latest = None
''',
    '''        files: list[Path] = []
        equity_files: list[Path] = []
        index_files: list[Path] = []
        latest = None
''',
    'inspect lists')
s = repl(s,
    '''            files.extend(cache_files)
            for path in cache_files:
''',
    '''            files.extend(cache_files)
            equity_files.extend(path for path in cache_files if self._history_file_kind(path) == "EQUITY")
            index_files.extend(path for path in cache_files if self._history_file_kind(path) == "INDEX")
            for path in cache_files:
''',
    'inspect classify')
s = repl(s,
    '''            "ohlcv_ready": bool(files),
            "stock_files": len({p.name for p in files}),
            "latest_session": latest,
''',
    '''            "ohlcv_ready": bool(equity_files),
            "stock_files": len({p.name for p in equity_files}),
            "index_files": len({p.name for p in index_files}),
            "index_file_names": sorted({p.name for p in index_files}),
            "history_files_total": len({p.name for p in files}),
            "latest_session": latest,
''',
    'inspect result')
s = repl(s,
    '''            for path in root.glob("*.csv"):
                symbols.add(path.stem.replace(".NS", "").replace(".BO", "").upper())
''',
    '''            for path in root.glob("*.csv"):
                if self._history_file_kind(path) != "EQUITY":
                    continue
                symbols.add(path.stem.replace(".NS", "").replace(".BO", "").upper())
''',
    'symbols equity only')
anchor = '''    def latest_prediction_rows(self, limit: int = 20) -> list[dict[str, Any]]:
'''
helper = '''    def _execution_preview_for_active_run(self) -> dict[str, dict[str, Any]]:
        active = self.active_prediction_run()
        if not active:
            return {}
        run = active.get("run") or {}
        try:
            request = AllocationRequest(float(run.get("capital") or 0.0), int(run.get("horizon_sessions") or 20), _finite(run.get("target_return")))
            all_inputs = self.allocator.candidates_from_latest_run(active)
            executable_inputs = [row for row in all_inputs if is_executable_decision(row.opportunity_status)]
            preview = self.allocator.execution_preview(request, executable_inputs, self.allocator.holdings_from_portfolio())
            for candidate in all_inputs:
                symbol = candidate.symbol
                price = candidate.latest_close
                if price is None:
                    price, _ = self.allocator.history.latest_close(symbol)
                cash_qty = 0 if price is None or price <= 0 else int(request.deployable_capital // price)
                if symbol not in preview:
                    preview[symbol] = {
                        "cash_affordable": cash_qty > 0,
                        "cash_affordable_qty": cash_qty,
                        "executable": False,
                        "executable_qty": 0,
                        "execution_action": "EXCLUDED",
                        "execution_reason_code": "NON_EXECUTABLE_MODEL_STATUS",
                        "execution_reason": explain_reason_code("NON_EXECUTABLE_MODEL_STATUS"),
                        "single_stock_exception_applied": False,
                    }
                else:
                    preview[symbol]["cash_affordable"] = cash_qty > 0
                    preview[symbol]["cash_affordable_qty"] = cash_qty
            return preview
        except Exception:
            return {}

'''
if helper not in s:
    if anchor not in s:
        raise RuntimeError('execution preview insertion point missing')
    s = s.replace(anchor, helper + anchor, 1)
s = repl(s,
    '''        out = []
        for row in rows:
''',
    '''        execution_preview = self._execution_preview_for_active_run() if active else {}
        out = []
        for row in rows:
''',
    'prediction execution map')
s = repl(s,
    '''            except Exception:
                item["raw"] = {}
            out.append(item)
''',
    '''            except Exception:
                item["raw"] = {}
            execution = execution_preview.get(str(item.get("symbol") or "").upper().replace(".NS", ""), {})
            item.update({
                "cash_affordable": bool(execution.get("cash_affordable")),
                "cash_affordable_qty": int(execution.get("cash_affordable_qty") or 0),
                "executable": bool(execution.get("executable")),
                "executable_qty": int(execution.get("executable_qty") or 0),
                "execution_action": execution.get("execution_action"),
                "execution_reason_code": execution.get("execution_reason_code"),
                "execution_reason": execution.get("execution_reason"),
                "single_stock_exception_applied": bool(execution.get("single_stock_exception_applied")),
            })
            if item["executable"]:
                item["execution_status"] = "EXECUTABLE ×" + str(item["executable_qty"])
            elif item["cash_affordable"] and not is_executable_decision(item.get("opportunity_status")):
                item["execution_status"] = "CASH AFFORDABLE · MODEL WATCH"
            elif item["cash_affordable"]:
                item["execution_status"] = "CASH AFFORDABLE · BLOCKED"
            else:
                item["execution_status"] = "NOT EXECUTABLE"
            out.append(item)
''',
    'prediction annotations')
s = repl(s,
    '''        elif result.get("new_buys"):
            max_pos = float(getattr(self.allocator, "policy", {}).get("max_position_capital_fraction", 0.35) or 0.35)
            summary["unused_cash_explanation"] = (
                f"Cash is intentionally left unallocated. The allocator does not force 100% deployment: each new stock is capped at {max_pos*100:.0f}% of deployable capital, "
                "only executable BUY candidates receive capital, and whole-share/sector constraints can leave a residual cash balance."
            )
        else:
            summary["unused_cash_explanation"] = "No candidate was executable under the current combined-decision and whole-share portfolio constraints; cash is therefore retained."
''',
    '''        elif result.get("new_buys"):
            exception_rows = [row for row in result.get("new_buys", []) if row.get("single_stock_exception_applied")]
            if exception_rows:
                row = exception_rows[0]
                summary["unused_cash_explanation"] = (
                    "Only one new model-executable stock was cash-affordable, so Phase 2 relaxed the normal 35% concentration cap for " + str(row.get("symbol")) + ". "
                    + "The plan proposes " + str(int(row.get("shares") or 0)) + " whole share(s) without leverage; remaining cash is the whole-share residual."
                )
            else:
                max_pos = float(getattr(self.allocator, "policy", {}).get("max_position_capital_fraction", 0.35) or 0.35)
                summary["unused_cash_explanation"] = (
                    f"Cash is intentionally left unallocated. With multiple executable stocks, each new stock remains capped at {max_pos*100:.0f}% of deployable capital; "
                    "whole-share and sector constraints can leave a residual cash balance."
                )
        else:
            details = ", ".join(f"{code}: {count}" for code, count in sorted(reason_counts.items())) or "no executable combined-decision rows"
            summary["unused_cash_explanation"] = "No stock was executable for these exact inputs. Allocator reasons — " + details + "."
''',
    'unused cash explanation')
p.write_text(s, encoding='utf-8')

# frontend/app.js
p = root / 'modern_ui' / 'frontend' / 'app.js'
s = p.read_text(encoding='utf-8')
s = repl(s,
    "function dataSourceLabel(ds){const a=ds?.active||{};if(ds?.mode==='REAL_OFFICIAL_DATA')return `Official NSE OHLCV · ${a.stock_files||0} stocks · ${a.latest_session||'—'}`;if(ds?.mode==='REAL_FROZEN_HISTORY')return `Frozen historical OHLCV · ${a.stock_files||0} stocks · ${a.latest_session||'—'}`;return 'No real OHLCV repository connected';}",
    "function dataSourceLabel(ds){const a=ds?.active||{},idx=+a.index_files||0,extra=idx?` · ${idx} market index${idx===1?'':'es'}`:'';if(ds?.mode==='REAL_OFFICIAL_DATA')return `Official NSE OHLCV · ${a.stock_files||0} equities${extra} · ${a.latest_session||'—'}`;if(ds?.mode==='REAL_FROZEN_HISTORY')return `Frozen historical OHLCV · ${a.stock_files||0} equities${extra} · ${a.latest_session||'—'}`;return 'No real OHLCV repository connected';}",
    'data source label')
s = repl(s,
    "  if(f==='affordable') rows=rows.filter(x=>(+x.affordable_qty||0)>0);",
    "  if(f==='cash-affordable') rows=rows.filter(x=>(+x.cash_affordable_qty||0)>0);\n  if(f==='executable') rows=rows.filter(x=>x.executable===true&&(+x.executable_qty||0)>0);",
    'filters')
s = repl(s,
    '''  t.innerHTML=`<div class="table-row table-header"><span>Rank</span><span>Stock</span><span>Decision</span><span>Expected</span><span>Target check</span><span>Profit rate</span><span>Downside</span><span></span></div>`+
    (items||[]).map(i=>`<div class="table-row" data-symbol="${escapeHtml(i.symbol)}"><span>#${i.rank}</span><strong>${escapeHtml(i.symbol)}</strong><span>${escapeHtml(i.opportunity_status||'—')}</span><strong class="${(+i.expected_return||0)>=0?'positive-text':'negative-text'}">${fmtPctFraction(i.expected_return)}</strong><strong class="${i.target_status==='MEETS TARGET'?'positive-text':i.target_status==='BELOW TARGET'?'negative-text':''}">${escapeHtml(i.target_status||'NO TARGET')}</strong><span>${fmtPctFraction(i.profit_probability)}</span><span>${fmtPctFraction(i.downside_risk)}</span><span>→</span></div>`).join('');
''',
    '''  t.innerHTML=`<div class="table-row table-header"><span>Rank</span><span>Stock</span><span>Decision</span><span>Expected</span><span>Target check</span><span>Execution</span><span>Profit rate</span><span>Downside</span><span></span></div>`+
    (items||[]).map(i=>{const execCls=i.executable?'positive-text':i.cash_affordable?'':'negative-text';const execTitle=escapeHtml(i.execution_reason||'');return `<div class="table-row" data-symbol="${escapeHtml(i.symbol)}"><span>#${i.rank}</span><strong>${escapeHtml(i.symbol)}</strong><span>${escapeHtml(i.opportunity_status||'—')}</span><strong class="${(+i.expected_return||0)>=0?'positive-text':'negative-text'}">${fmtPctFraction(i.expected_return)}</strong><strong class="${i.target_status==='MEETS TARGET'?'positive-text':i.target_status==='BELOW TARGET'?'negative-text':''}">${escapeHtml(i.target_status||'NO TARGET')}</strong><strong class="${execCls}" title="${execTitle}">${escapeHtml(i.execution_status||'NOT EVALUATED')}</strong><span>${fmtPctFraction(i.profit_probability)}</span><span>${fmtPctFraction(i.downside_risk)}</span><span>→</span></div>`}).join('');
''',
    'opportunity execution column')
s = s.replace("${d.new_buys?.length||0} eligible buys · ${d.excluded?.length||0} excluded/audit rows", "${d.new_buys?.length||0} executable buys · ${d.excluded?.length||0} blocked/audit rows", 1)
s = s.replace("`${a.stock_files||0} stock histories · latest session ${a.latest_session||'—'}`", "`${a.stock_files||0} equity histories${(+a.index_files||0)?` · ${a.index_files} market index`:''} · latest session ${a.latest_session||'—'}`", 1)
p.write_text(s, encoding='utf-8')

# frontend/index.html
p = root / 'modern_ui' / 'frontend' / 'index.html'
s = p.read_text(encoding='utf-8')
s = repl(s,
    '<button class="filter-pill" data-opp-filter="affordable">Affordable</button>',
    '<button class="filter-pill" data-opp-filter="cash-affordable">Cash affordable</button><button class="filter-pill" data-opp-filter="executable">Executable</button>',
    'filter buttons')
p.write_text(s, encoding='utf-8')

# frontend/styles.css
p = root / 'modern_ui' / 'frontend' / 'styles.css'
s = p.read_text(encoding='utf-8')
if '#opportunityTable .table-row' not in s:
    s += '\n/* Phase 2: Opportunities exposes allocator executability explicitly. */\n#opportunityTable .table-row{grid-template-columns:52px .75fr 1.15fr .75fr .9fr 1.15fr .75fr .75fr 36px}\n'
p.write_text(s, encoding='utf-8')

# Build-time contracts
assert '0.9.9-allocation-executability-v2' in (root/'modern_ui/api.py').read_text(encoding='utf-8')
assert 'SINGLE_ELIGIBLE_FULL_CAPITAL' in (root/'stock_app/allocation.py').read_text(encoding='utf-8')
assert 'raw_stem.startswith("INDEX_")' in (root/'stock_app/historical.py').read_text(encoding='utf-8')
assert 'data-opp-filter="executable"' in (root/'modern_ui/frontend/index.html').read_text(encoding='utf-8')
print('0.9.9 Phase 2 patch applied')
