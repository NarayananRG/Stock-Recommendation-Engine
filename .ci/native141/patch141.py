from pathlib import Path
import os


root = Path(os.environ["SRE_ENGINE_ROOT"])


def edit(relative: str, old: str, new: str) -> None:
    path = root / relative
    text = path.read_text(encoding="utf-8-sig")
    if old not in text:
        raise RuntimeError(f"{relative}: missing patch point {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


edit("modern_ui/api.py", 'APP_VERSION = "0.14.0-live-dual-strategy-v1"',
     'APP_VERSION = "0.14.1-fundamental-coverage-ui-repair"')
edit("stock_app/live_decision_v1.py", 'MODEL = "0.14.0-live-dual-strategy-v1"',
     'MODEL = "0.14.1-fundamental-coverage-ui-repair"')
edit("modern_ui/api.py", 'hashlib.sha256(run_id.encode()).hexdigest()',
     'hashlib.sha256((APP_VERSION + ":" + run_id).encode()).hexdigest()')

# Sparse balance-sheet and cash-flow facts are often reported only in annual or
# half-year filings. Use the newest fact that was genuinely available at the
# decision cutoff, while retaining its filing date and age. Never fill with zero.
edit("stock_app/fundamental_v3.py", "def _ttm(rows: list[dict[str, Any]], feature: str) -> float | None:\n", '''def _latest_pit_feature(rows: list[dict[str, Any]], feature: str, cutoff: datetime) -> tuple[float | None, dict[str, Any]]:
    for row in reversed(rows):
        value = _usable_feature(row, feature)
        available = _dt(row.get("availability_ts") or row.get("effective_availability_ts"))
        if value is None or available is None or available > cutoff:
            continue
        age = max(0, (cutoff.date() - available.date()).days)
        if age > STALE_FILING_DAYS:
            return None, {"status": "STALE", "as_of": available.isoformat(), "age_days": age}
        return value, {"status": "AVAILABLE", "as_of": available.isoformat(), "age_days": age,
                       "quarter_end": row.get("quarter_end") or row.get("current_quarter_end"),
                       "concept": row.get(f"{feature}__concept")}
    return None, {"status": "MISSING", "as_of": None, "age_days": None}


def _ttm(rows: list[dict[str, Any]], feature: str) -> float | None:
''')
edit("stock_app/fundamental_v3.py", "    price: float | None,\n) -> dict[str, Any]:", "    price: float | None,\n    cutoff: datetime,\n) -> dict[str, Any]:")
edit("stock_app/fundamental_v3.py", '''    latest_ocf = _usable_feature(latest, "OPERATING_CASH_FLOW")
    latest_cash = _usable_feature(latest, "CASH_AND_EQUIVALENTS")
    latest_assets = _usable_feature(latest, "TOTAL_ASSETS")
    debt_equity = _usable_feature(latest, "DEBT_EQUITY_RATIO")
    cash_assets = _ratio(latest_cash, latest_assets, 100.0)
''', '''    latest_ocf, ocf_source = _latest_pit_feature(history, "OPERATING_CASH_FLOW", cutoff)
    latest_cash, cash_source = _latest_pit_feature(history, "CASH_AND_EQUIVALENTS", cutoff)
    latest_assets, assets_source = _latest_pit_feature(history, "TOTAL_ASSETS", cutoff)
    debt_equity, debt_source = _latest_pit_feature(history, "DEBT_EQUITY_RATIO", cutoff)
    cash_assets = _ratio(latest_cash, latest_assets, 100.0)
''')
edit("stock_app/fundamental_v3.py", '''        "cash_flow": {
            "latest_operating_cash_flow": _round(latest_ocf, 2),
            "ocf_yoy_symmetric_pct": _round(ocf_yoy, 4),
        },
        "balance_sheet": {
            "cash_and_equivalents": _round(latest_cash, 2),
            "total_assets": _round(latest_assets, 2),
            "cash_to_assets_pct": _round(cash_assets, 4),
            "debt_equity_ratio": _round(debt_equity, 4),
        },
''', '''        "cash_flow": {
            "latest_operating_cash_flow": _round(latest_ocf, 2),
            "ocf_yoy_symmetric_pct": _round(ocf_yoy, 4),
            "source": ocf_source,
        },
        "balance_sheet": {
            "cash_and_equivalents": _round(latest_cash, 2),
            "total_assets": _round(latest_assets, 2),
            "cash_to_assets_pct": _round(cash_assets, 4),
            "debt_equity_ratio": _round(debt_equity, 4),
            "sources": {"cash_and_equivalents": cash_source, "total_assets": assets_source,
                        "debt_equity_ratio": debt_source},
        },
''')
edit("stock_app/fundamental_v3.py", '    scored = _score(latest, history, events, risk, _num(latest_price))',
     '    scored = _score(latest, history, events, risk, _num(latest_price), cutoff)')

coverage_code = '''    feature_values = {
        "Revenue": scored["ttm"].get("revenue"), "PAT": scored["ttm"].get("pat"),
        "PBT": scored["ttm"].get("pbt"), "EPS": scored["ttm"].get("eps"),
        "Margins": scored["ttm"].get("pat_margin_pct"),
        "Operating Cash Flow": scored["cash_flow"].get("latest_operating_cash_flow"),
        "Cash": scored["balance_sheet"].get("cash_and_equivalents"),
        "Debt/Leverage": scored["balance_sheet"].get("debt_equity_ratio"),
        "Finance Cost": _usable_feature(latest, "FINANCE_COST"),
        "ROE": _usable_feature(latest, "ROE"), "ROCE": _usable_feature(latest, "ROCE"),
        "ROIC": _usable_feature(latest, "ROIC"), "Free Cash Flow": _usable_feature(latest, "FREE_CASH_FLOW"),
        "PE": scored["valuation"].get("implied_pe_from_ttm_eps"),
        "PB": _usable_feature(latest, "PB_RATIO"), "EV/EBITDA": _usable_feature(latest, "EV_EBITDA"),
        "PIT relative valuation reference": None,
        "Risk-event profile": (risk or {}).get("event_profile"),
        "Filing freshness": freshness, "Sector/domain classification": domain or None,
    }
    feature_coverage = {}
    for name, value in feature_values.items():
        stale = name == "Filing freshness" and freshness == "STALE"
        feature_coverage[name] = {"status": "STALE" if stale else "AVAILABLE" if value not in (None, "") else "MISSING",
                                  "value": value}
    bank_required = {
        "Asset quality": ("GNPA", "NNPA"), "Capital adequacy": ("CAPITAL_ADEQUACY_RATIO",),
        "Funding/liquidity": ("LOAN_DEPOSIT_RATIO",), "Credit cost/provisioning": ("CREDIT_COST", "PROVISION_COVERAGE_RATIO"),
        "NIM/spread": ("NIM",), "ROA": ("ROA",), "ROE": ("ROE",),
    }
    financial_metrics = {}
    for group, names in bank_required.items():
        values = {name: _usable_feature(latest, name) for name in names}
        financial_metrics[group] = {"status": "AVAILABLE" if any(v is not None for v in values.values()) else "MISSING",
                                    "values": {k: v for k, v in values.items() if v is not None}}
    financial_missing = [name for name, item in financial_metrics.items() if item["status"] != "AVAILABLE"]
    financial_adapter = {
        "domain": domain, "applicable": financial_domain, "metrics": financial_metrics,
        "missing_required_groups": financial_missing,
        "safety_ready": bool(financial_domain and not financial_missing),
        "status": "READY" if financial_domain and not financial_missing else "INSUFFICIENT_COVERAGE" if financial_domain else "NOT_APPLICABLE",
        "industrial_cashflow_or_leverage_used": False,
    }
    scored["valuation"]["implied_pb"] = _usable_feature(latest, "PB_RATIO")
    scored["valuation"]["pb_basis"] = "PIT_REPORTED_PB" if scored["valuation"]["implied_pb"] is not None else "UNAVAILABLE"

'''
edit("stock_app/fundamental_v3.py", '    independent_validation = None\n', coverage_code + '    independent_validation = None\n')
edit("stock_app/fundamental_v3.py", '        "risk_event": {\n', '        "feature_coverage": feature_coverage,\n        "financial_domain_adapter": financial_adapter,\n        "risk_event": {\n')

# Add domain-aware safety without treating bank debt or operating cash flow as
# industrial evidence. Current data remains insufficient, so this does not force
# any financial-domain BUY.
edit("stock_app/live_decision_v1.py", '    financial = f.get("sector_profile") == "FINANCIAL_DOMAIN_CONSERVATIVE"\n',
     '    financial = f.get("sector_profile") == "FINANCIAL_DOMAIN_CONSERVATIVE"\n    financial_adapter = f.get("financial_domain_adapter") or {}\n    financial_ready = financial_adapter.get("safety_ready") is True\n')
edit("stock_app/live_decision_v1.py", '''                fundamental_data_quality=quality, financial_domain=financial)
''', '''                fundamental_data_quality=quality, financial_domain=financial,
                financial_domain_state=financial_adapter.get("status", "NOT_APPLICABLE"),
                financial_domain_ready=financial_ready)
''')
edit("stock_app/live_decision_v1.py", '''    pe = number(valuation.get("implied_pe_from_ttm_eps"))
    reference = number(valuation.get("pit_historical_pe_reference")) if valuation.get("pit_comparison_available") is True else None
    valuation_state = "UNAVAILABLE"
    if pe is not None and pe > 0 and reference is not None and reference > 0:
        ratio = pe / reference
''', '''    current_valuation = number(valuation.get("implied_pb" if financial else "implied_pe_from_ttm_eps"))
    reference = number(valuation.get("pit_historical_pb_reference" if financial else "pit_historical_pe_reference")) if valuation.get("pit_comparison_available") is True else None
    valuation_state = "UNAVAILABLE"
    if current_valuation is not None and current_valuation > 0 and reference is not None and reference > 0:
        ratio = current_valuation / reference
''')
edit("stock_app/live_decision_v1.py", '''    if states["financial_domain"]:
        parts.append("Industrial debt and cash-flow rules do not apply; banking-specific PIT data is insufficient for a Recovery BUY.")
''', '''    if states["financial_domain"]:
        adapter = f.get("financial_domain_adapter") or {}
        missing = adapter.get("missing_required_groups") or []
        parts.append("Industrial debt and cash-flow rules do not apply. Financial-domain PIT safety is " + states["financial_domain_state"].lower() + ".")
        if missing:
            parts.append("Missing financial-domain evidence: " + ", ".join(missing) + ".")
''')
edit("stock_app/live_decision_v1.py", '''    momentum_valid = (strong and safety and fundamental_ready and atr is not None and 0 <= atr <= 6 and
                      (s["financial_domain"] or (balance_ready and cash_ready)) and regime in ("BULL", "MIXED"))
''', '''    domain_safety_ready = s["financial_domain_ready"] if s["financial_domain"] else (balance_ready and cash_ready)
    momentum_valid = (strong and safety and fundamental_ready and atr is not None and 0 <= atr <= 6 and
                      domain_safety_ready and regime in ("BULL", "MIXED"))
''')
edit("stock_app/live_decision_v1.py", '''    recovery_valid = (depressed and safety and fundamental_ready and cash_ready and balance_ready
                      and not s["financial_domain"] and downside_controlled
                      and s["valuation_state"] in ("ATTRACTIVE", "REASONABLE"))
''', '''    recovery_fundamental_ready = s["financial_domain_ready"] if s["financial_domain"] else (cash_ready and balance_ready)
    recovery_valid = (depressed and safety and fundamental_ready and recovery_fundamental_ready
                      and downside_controlled and s["valuation_state"] in ("ATTRACTIVE", "REASONABLE"))
''')
edit("stock_app/live_decision_v1.py", '    if s["financial_domain"]: reasons.append("BANKING_SPECIFIC_PIT_METRICS_UNAVAILABLE_FOR_RECOVERY")\n',
     '    if s["financial_domain"] and not s["financial_domain_ready"]: reasons.append("FINANCIAL_DOMAIN_PIT_SAFETY_INCOMPLETE")\n')
edit("stock_app/live_decision_v1.py", '''    if not strong: reasons.append("MOMENTUM_CONFIRMATION_INCOMPLETE")
''', '''    if not strong: reasons.append("MOMENTUM_CONFIRMATION_INCOMPLETE")
    missing_evidence = []
    coverage = fundamental.get("feature_coverage") or {}
    for name, item in coverage.items():
        if (item or {}).get("status") != "AVAILABLE": missing_evidence.append(name)
    if s["financial_domain"]:
        missing_evidence += list((fundamental.get("financial_domain_adapter") or {}).get("missing_required_groups") or [])
    missing_evidence = list(dict.fromkeys(missing_evidence))
''')
edit("stock_app/live_decision_v1.py", '                reason_codes=reasons, target_used_in_score=False, **s,\n',
     '                reason_codes=list(dict.fromkeys(reasons)), missing_evidence=missing_evidence, target_used_in_score=False, **s,\n')

# Fill the valuation coverage flag only after the historical company-specific
# reference has been calculated by the materializer.
edit("modern_ui/api.py", '            pe_history = []\n', '            pe_history = []\n            pb_history = []\n')
edit("modern_ui/api.py", '''                if past.get("point_in_time_safe") and past.get("filing_freshness") == "CURRENT_FOR_DECISION_TIME" and pe is not None and pe > 0:
                    pe_history.append({"session": prior["date"], "pe": pe, "availability_ts": past.get("effective_availability_ts")})
''', '''                if past.get("point_in_time_safe") and past.get("filing_freshness") == "CURRENT_FOR_DECISION_TIME" and pe is not None and pe > 0:
                    pe_history.append({"session": prior["date"], "pe": pe, "availability_ts": past.get("effective_availability_ts")})
                pb = _finite((past.get("valuation") or {}).get("implied_pb"))
                if past.get("point_in_time_safe") and past.get("filing_freshness") == "CURRENT_FOR_DECISION_TIME" and pb is not None and pb > 0:
                    pb_history.append({"session": prior["date"], "pb": pb, "availability_ts": past.get("effective_availability_ts")})
''')
edit("modern_ui/api.py", '''            fundamental["valuation"] = {**(fundamental.get("valuation") or {}),
                                       "pit_comparison_available": len(pe_history) >= 4,
                                       "pit_historical_pe_reference": median([p["pe"] for p in pe_history]) if len(pe_history) >= 4 else None,
                                       "pit_comparison_observations": pe_history}
''', '''            fundamental["valuation"] = {**(fundamental.get("valuation") or {}),
                                       "pit_comparison_available": len(pb_history) >= 4 if fundamental.get("sector_profile") == "FINANCIAL_DOMAIN_CONSERVATIVE" else len(pe_history) >= 4,
                                       "pit_historical_pe_reference": median([p["pe"] for p in pe_history]) if len(pe_history) >= 4 else None,
                                       "pit_historical_pb_reference": median([p["pb"] for p in pb_history]) if len(pb_history) >= 4 else None,
                                       "pit_comparison_observations": pb_history if fundamental.get("sector_profile") == "FINANCIAL_DOMAIN_CONSERVATIVE" else pe_history}
            fundamental.setdefault("feature_coverage", {})["PIT relative valuation reference"] = {
                "status": "AVAILABLE" if fundamental["valuation"]["pit_comparison_available"] else "MISSING",
                "value": fundamental["valuation"]["pit_historical_pb_reference"] if fundamental.get("sector_profile") == "FINANCIAL_DOMAIN_CONSERVATIVE" else fundamental["valuation"]["pit_historical_pe_reference"],
                "observations": len(pb_history) if fundamental.get("sector_profile") == "FINANCIAL_DOMAIN_CONSERVATIVE" else len(pe_history),
            }
''')

# Coverage diagnostics are computed from the exact immutable active run.
coverage_method = '''    def live_coverage(self) -> dict[str, Any]:
        from collections import Counter
        rows = self.latest_prediction_rows(limit=200)
        features: dict[str, Counter] = {}
        blockers = Counter()
        ready = partial = unavailable = financial = 0
        symbols = []
        for row in rows:
            live = row.get("live_decision") or {}
            fundamental = ((live.get("evidence") or {}).get("fundamental") or {})
            adapter = fundamental.get("financial_domain_adapter") or {}
            is_financial = adapter.get("applicable") is True or live.get("financial_domain") is True
            financial += int(is_financial)
            if not fundamental.get("available"):
                unavailable += 1
            elif (adapter.get("safety_ready") if is_financial else
                  live.get("cash_flow_state") in ("ADEQUATE", "SUPPORTIVE") and
                  live.get("balance_sheet_state") in ("HEALTHY", "ACCEPTABLE")):
                ready += 1
            else:
                partial += 1
            for code in live.get("reason_codes") or []:
                blockers[str(code)] += 1
            per_symbol = {}
            for name, item in (fundamental.get("feature_coverage") or {}).items():
                status = str((item or {}).get("status") or "MISSING").upper()
                status = status if status in ("AVAILABLE", "MISSING", "STALE") else "MISSING"
                features.setdefault(name, Counter())[status] += 1
                per_symbol[name] = status
            symbols.append({"symbol": row.get("symbol"), "final_action": live.get("final_action"),
                            "missing_evidence": live.get("missing_evidence") or [], "features": per_symbol})
        for counts in features.values():
            counts["MISSING"] += len(rows) - sum(counts.values())
        lane = (self.active_prediction_run() or {}).get("run", {}).get("lane_counts") or {}
        return {"authority": "LIVE_DECISION_V1", "model_version": APP_VERSION, "universe_size": len(rows),
                "fundamental_ready": ready, "fundamental_partial": partial,
                "fundamental_unavailable": unavailable, "financial_domain_count": financial,
                "nonfinancial_count": len(rows) - financial, "lane_counts": lane,
                "blocker_counts": dict(blockers.most_common()),
                "feature_coverage_counts": {name: dict(counts) for name, counts in sorted(features.items())},
                "symbols": symbols}

'''
edit("modern_ui/api.py", '    def latest_run_input(self) -> dict[str, Any] | None:\n', coverage_method + '    def latest_run_input(self) -> dict[str, Any] | None:\n')
edit("modern_ui/api.py", '''    @app.get("/api/portfolio")
''', '''    @app.get("/api/live/coverage")
    def live_coverage() -> dict[str, Any]:
        return ctx.live_coverage()

    @app.get("/api/portfolio")
''')

# Capital Plan language and diagnostics now reflect the live authority.
edit("modern_ui/api.py", '"no executable combined-decision rows"',
     '"no executable LIVE_DECISION_V1 BUY opportunities"')
edit("modern_ui/api.py", '''        result["capital_summary"] = summary
        return result
''', '''        live_rows = list(active_run.get("candidates") or [])
        lane_counts = (active_run.get("run") or {}).get("lane_counts") or {}
        from collections import Counter
        blocker_counts = Counter(code for row in live_rows for code in ((row.get("live_decision") or {}).get("reason_codes") or []))
        summary["live_lane_counts"] = lane_counts
        summary["top_blockers"] = dict(blocker_counts.most_common(8))
        if not result.get("new_buys"):
            summary["unused_cash_explanation"] = "No executable LIVE_DECISION_V1 BUY opportunities for the selected inputs. Cash is retained."
        result["capital_summary"] = summary
        return result
''')

print("0.14.1 fundamental coverage and API repair applied")
