"""Deterministic evidence-condition classification for LIVE_DECISION_V1.

This module describes evidence; it never changes decision thresholds or actions.
"""
from __future__ import annotations

from typing import Any


CONDITIONS = {
    "MISSING_SOURCE_DATA",
    "SOURCE_AVAILABLE_BUT_UNMAPPED",
    "PRESENT_BUT_UNFAVORABLE",
    "INSUFFICIENT_PIT_HISTORY",
    "NOT_APPLICABLE_FOR_DOMAIN",
    "POLICY_NOT_VALIDATED",
    "STALE_OR_OUT_OF_ORDER",
    "PARSER_OR_SCHEMA_FAILURE",
    "PRESENT_AND_SUPPORTIVE",
}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _entry(condition: str, value: Any = None, *, detail: str = "", source: Any = None) -> dict[str, Any]:
    if condition not in CONDITIONS:
        raise ValueError(f"UNKNOWN_EVIDENCE_CONDITION:{condition}")
    return {"condition": condition, "value": value, "detail": detail, "source": source}


def domain_name(fundamental: dict[str, Any]) -> str:
    raw = str(fundamental.get("domain") or "").upper()
    if "BANK" in raw:
        return "bank"
    if "NBFC" in raw or "NON_BANK" in raw:
        return "NBFC"
    if any(token in raw for token in ("FINANC", "INSUR")):
        return "other financial"
    return "corporate"


def _ordinary(value: Any, *, unfavorable: bool = False, detail: str = "") -> dict[str, Any]:
    if _number(value) is None:
        return _entry("MISSING_SOURCE_DATA", value, detail=detail or "No usable official PIT value")
    return _entry("PRESENT_BUT_UNFAVORABLE" if unfavorable else "PRESENT_AND_SUPPORTIVE", value, detail=detail)


def classify_live_decision(live: dict[str, Any], leverage_diagnostic: str | None = None) -> dict[str, Any]:
    fundamental = ((live.get("evidence") or {}).get("fundamental") or {})
    profile = domain_name(fundamental)
    financial = profile != "corporate"
    stale = fundamental.get("filing_freshness") == "STALE"
    growth = fundamental.get("growth") or {}
    profitability = fundamental.get("profitability") or {}
    cash = fundamental.get("cash_flow") or {}
    balance = fundamental.get("balance_sheet") or {}
    valuation = fundamental.get("valuation") or {}
    feature = fundamental.get("feature_coverage") or {}

    result: dict[str, Any] = {"domain": profile, "families": {}}
    families = result["families"]
    for label, value_key, growth_key in (
        ("Revenue", "revenue", "revenue_yoy_symmetric_pct"),
        ("PAT", "pat", "pat_yoy_symmetric_pct"),
        ("EPS", "eps", "eps_yoy_symmetric_pct"),
    ):
        value = _number(profitability.get(value_key))
        trend = _number(growth.get(growth_key))
        if stale:
            families[label] = _entry("STALE_OR_OUT_OF_ORDER", value, detail="Latest eligible filing is stale")
        elif value is None or trend is None:
            families[label] = _entry("MISSING_SOURCE_DATA", value, detail="Current value or comparable PIT trend is unavailable")
        else:
            unfavorable = value <= 0 or trend < -5
            families[label] = _entry("PRESENT_BUT_UNFAVORABLE" if unfavorable else "PRESENT_AND_SUPPORTIVE", value,
                                     detail=f"YoY symmetric trend={trend}")

    ocf = _number(cash.get("latest_operating_cash_flow"))
    if financial:
        families["Operating cash flow"] = _entry("NOT_APPLICABLE_FOR_DOMAIN", ocf,
                                                  detail="Industrial cash-flow safety is not applied to financial companies")
    elif stale:
        families["Operating cash flow"] = _entry("STALE_OR_OUT_OF_ORDER", ocf, source=cash.get("source"))
    elif ocf is None:
        families["Operating cash flow"] = _entry("MISSING_SOURCE_DATA", source=cash.get("source"))
    elif live.get("cash_flow_state") in ("WEAK", "DANGEROUS"):
        families["Operating cash flow"] = _entry("PRESENT_BUT_UNFAVORABLE", ocf, source=cash.get("source"),
                                                  detail=str(live.get("cash_flow_state")))
    else:
        families["Operating cash flow"] = _entry("PRESENT_AND_SUPPORTIVE", ocf, source=cash.get("source"),
                                                  detail=str(live.get("cash_flow_state")))

    for label, key, source_key in (
        ("Cash / equivalents", "cash_and_equivalents", "cash_and_equivalents"),
        ("Total assets", "total_assets", "total_assets"),
    ):
        if financial:
            families[label] = _entry("NOT_APPLICABLE_FOR_DOMAIN", balance.get(key),
                                     detail="Industrial balance-sheet safety is not applied to financial companies")
        elif stale:
            families[label] = _entry("STALE_OR_OUT_OF_ORDER", balance.get(key), source=(balance.get("sources") or {}).get(source_key))
        else:
            families[label] = (
                _entry("MISSING_SOURCE_DATA", source=(balance.get("sources") or {}).get(source_key))
                if _number(balance.get(key)) is None else
                _entry("PRESENT_AND_SUPPORTIVE", _number(balance.get(key)), source=(balance.get("sources") or {}).get(source_key))
            )

    debt = _number(balance.get("debt_equity_ratio"))
    if financial:
        families["Debt / leverage / DebtEquityRatio"] = _entry(
            "NOT_APPLICABLE_FOR_DOMAIN", debt,
            detail="Corporate leverage rule is prohibited for bank/NBFC domains")
    elif stale:
        families["Debt / leverage / DebtEquityRatio"] = _entry("STALE_OR_OUT_OF_ORDER", debt)
    elif debt is None:
        condition = "SOURCE_AVAILABLE_BUT_UNMAPPED" if leverage_diagnostic in {
            "NO_HUMAN_DISPLAY_VALUE", "DISPLAY_XBRL_MISMATCH", "AMBIGUOUS_XBRL_VALUES"
        } else "PARSER_OR_SCHEMA_FAILURE" if leverage_diagnostic == "FETCH_OR_PARSE_ERROR" else "MISSING_SOURCE_DATA"
        families["Debt / leverage / DebtEquityRatio"] = _entry(condition, detail=leverage_diagnostic or "No validated equivalent concept")
    elif live.get("balance_sheet_state") in ("CAUTION", "STRESSED"):
        families["Debt / leverage / DebtEquityRatio"] = _entry("PRESENT_BUT_UNFAVORABLE", debt,
                                                                detail=str(live.get("balance_sheet_state")),
                                                                source=(balance.get("sources") or {}).get("debt_equity_ratio"))
    else:
        families["Debt / leverage / DebtEquityRatio"] = _entry("PRESENT_AND_SUPPORTIVE", debt,
                                                                detail=str(live.get("balance_sheet_state")),
                                                                source=(balance.get("sources") or {}).get("debt_equity_ratio"))

    current_key = "implied_pb" if financial else "implied_pe_from_ttm_eps"
    current = _number(valuation.get(current_key))
    eps = _number(profitability.get("eps"))
    if current is None:
        condition = "PRESENT_BUT_UNFAVORABLE" if not financial and eps is not None and eps <= 0 else "MISSING_SOURCE_DATA"
        families["PE / earnings valuation" if not financial else "PB valuation"] = _entry(condition, current,
                                                                                           detail="Non-positive earnings" if condition == "PRESENT_BUT_UNFAVORABLE" else "Current PIT multiple unavailable")
    else:
        families["PE / earnings valuation" if not financial else "PB valuation"] = _entry("PRESENT_AND_SUPPORTIVE", current)

    observations = list(valuation.get("pit_comparison_observations") or [])
    reference = _number(valuation.get("pit_historical_pb_reference" if financial else "pit_historical_pe_reference"))
    if stale:
        historical = _entry("STALE_OR_OUT_OF_ORDER", reference, detail="Current eligible filing is stale")
    elif current is None:
        current_family = families["PB valuation" if financial else "PE / earnings valuation"]
        historical = _entry(current_family["condition"], detail="Current valuation is unavailable")
    elif len(observations) < 4:
        historical = _entry("INSUFFICIENT_PIT_HISTORY", reference, detail=f"{len(observations)} usable observations; minimum is 4")
    elif reference is None:
        historical = _entry("PARSER_OR_SCHEMA_FAILURE", reference, detail="Observation minimum met but reference is unavailable")
    else:
        historical = _entry("PRESENT_AND_SUPPORTIVE", reference, detail=f"{len(observations)} PIT observations")
    families["Historical PIT valuation reference"] = historical

    adapter = fundamental.get("financial_domain_adapter") or {}
    financial_metrics = {}
    if financial:
        for group, item in (adapter.get("metrics") or {}).items():
            financial_metrics[group] = {
                "condition": "POLICY_NOT_VALIDATED" if (item or {}).get("status") == "AVAILABLE" else "MISSING_SOURCE_DATA",
                "observed_status": (item or {}).get("status", "MISSING"),
                "values": (item or {}).get("values") or {},
            }
        result["financial_domain"] = {
            "condition": "POLICY_NOT_VALIDATED",
            "production_ready": False,
            "industrial_rules_used": False,
            "metrics": financial_metrics,
        }
    else:
        result["financial_domain"] = {"condition": "NOT_APPLICABLE_FOR_DOMAIN", "production_ready": False,
                                      "industrial_rules_used": False, "metrics": {}}
    result["missing"] = [name for name, item in families.items() if item["condition"] in {
        "MISSING_SOURCE_DATA", "SOURCE_AVAILABLE_BUT_UNMAPPED", "INSUFFICIENT_PIT_HISTORY",
        "STALE_OR_OUT_OF_ORDER", "PARSER_OR_SCHEMA_FAILURE", "POLICY_NOT_VALIDATED"
    }]
    result["unfavorable"] = [name for name, item in families.items() if item["condition"] == "PRESENT_BUT_UNFAVORABLE"]
    return result

