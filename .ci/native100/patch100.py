from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])

def repl(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"{label} contract missing")
    return text.replace(old, new, 1)

# Phase 3A/3 foundation: explicit freshness + provenance contract.
api = root / "modern_ui" / "api.py"
s = api.read_text(encoding="utf-8")
s = repl(
    s,
    'APP_VERSION = "0.9.9-allocation-executability-v2"',
    'APP_VERSION = "0.9.10-phase3-foundation"',
    "phase3 app version",
)

anchor = '''    def _inspect_data_repo(self, root: Path) -> dict[str, Any]:
'''
helper = '''    @staticmethod
    def _phase3_freshness_contract(latest_session: str | None, data_mode: str) -> dict[str, Any]:
        import datetime as _dt

        base = {
            "freshness_status": "UNAVAILABLE",
            "freshness_gate": "FAIL",
            "business_day_lag": None,
            "freshness_reason": "No market session is available.",
            "analysis_data_current": False,
        }
        if not latest_session:
            return base
        try:
            latest = _dt.date.fromisoformat(str(latest_session)[:10])
        except Exception:
            base["freshness_reason"] = "Latest market session is not a valid ISO date."
            return base

        today = _dt.date.today()
        lag = 0
        cursor = latest + _dt.timedelta(days=1)
        while cursor <= today:
            if cursor.weekday() < 5:
                lag += 1
            cursor += _dt.timedelta(days=1)

        base["business_day_lag"] = lag
        if data_mode == "REAL_OFFICIAL_DATA":
            if lag <= 2:
                base.update(
                    freshness_status="CURRENT",
                    freshness_gate="PASS",
                    freshness_reason=f"Official market data is within {lag} business day(s) of today.",
                    analysis_data_current=True,
                )
            else:
                base.update(
                    freshness_status="STALE",
                    freshness_gate="FAIL",
                    freshness_reason=f"Official market data is {lag} business day(s) behind today.",
                    analysis_data_current=False,
                )
        elif data_mode == "REAL_FROZEN_HISTORY":
            base.update(
                freshness_status="STALE_FROZEN",
                freshness_gate="WARN",
                freshness_reason="Frozen historical data is retained for deterministic analysis and is not current market data.",
                analysis_data_current=False,
            )
        else:
            base["freshness_reason"] = "No official current-market data source is connected."
        return base

'''
if helper not in s:
    if anchor not in s:
        raise RuntimeError("Phase 3 freshness insertion point missing")
    s = s.replace(anchor, helper + anchor, 1)

needle = '''            "provenance": provenance,
'''
replacement = '''            "provenance": provenance,
            **self._phase3_freshness_contract(latest, data_mode),
'''
s = repl(s, needle, replacement, "Phase 3 freshness fields")
api.write_text(s, encoding="utf-8")

# Surface freshness directly in the existing data-source label.
js = root / "modern_ui" / "frontend" / "app.js"
t = js.read_text(encoding="utf-8")
fn_start = t.index("function dataSourceLabel(ds){")
candidates = [
    t.find("\nfunction ", fn_start + 1),
    t.find("\nasync function ", fn_start + 1),
]
fn_end = min(pos for pos in candidates if pos > fn_start) if any(pos > fn_start for pos in candidates) else -1
if fn_end < 0:
    raise RuntimeError("Phase 3 data-source label end marker missing")
new_fn = """function dataSourceLabel(ds){const a=ds?.active||{},idx=+a.index_files||0,extra=idx?` · ${idx} market index${idx===1?'':'es'}`:'';const gate=a.freshness_gate||'FAIL',fresh=a.freshness_status||'UNAVAILABLE',freshTag=` · freshness ${gate}/${fresh}`;if(ds?.mode==='REAL_OFFICIAL_DATA')return `Official NSE OHLCV · ${a.stock_files||0} equities${extra} · ${a.latest_session||'—'}${freshTag}`;if(ds?.mode==='REAL_FROZEN_HISTORY')return `Frozen historical OHLCV · ${a.stock_files||0} equities${extra} · ${a.latest_session||'—'}${freshTag}`;return 'No real OHLCV repository connected · freshness FAIL/UNAVAILABLE';}"""
t = t[:fn_start] + new_fn + t[fn_end:]
js.write_text(t, encoding="utf-8")

# Machine-readable Phase 3 policy shipped with the engine.
policy_dir = root / "phase3"
policy_dir.mkdir(parents=True, exist_ok=True)
(policy_dir / "data_foundation_policy_v1.json").write_text(
    """{
  "schema": "SRE_PHASE3_DATA_FOUNDATION_POLICY_V1",
  "version": "0.9.10-phase3-foundation",
  "official_first": true,
  "automatic_yfinance_fallback": false,
  "freshness": {
    "official_pass_max_business_day_lag": 2,
    "frozen_history_gate": "WARN",
    "missing_data_gate": "FAIL"
  },
  "authority": "DATA_FOUNDATION_ONLY_NO_SCORE_CHANGE",
  "requirements": [
    "Explicit provenance",
    "Latest-session freshness gate",
    "Equity/index separation",
    "No silent fallback",
    "Point-in-time fundamental timestamps before future promotion"
  ]
}
""",
    encoding="utf-8",
)

assert 'APP_VERSION = "0.9.10-phase3-foundation"' in api.read_text(encoding="utf-8")
assert "_phase3_freshness_contract" in api.read_text(encoding="utf-8")
assert "freshness_gate" in js.read_text(encoding="utf-8")
print("0.9.10 Phase 3 foundation patch applied")
