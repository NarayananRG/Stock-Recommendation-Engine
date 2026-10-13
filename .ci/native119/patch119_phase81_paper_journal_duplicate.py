from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])

api = root / "modern_ui" / "api.py"
s = api.read_text(encoding="utf-8")
s = s.replace('APP_VERSION = "0.13.4-phase8-formatter-hotfix"', 'APP_VERSION = "0.13.5-phase8-paper-journal-hotfix"', 1)

old_candidates = [
    '''        if prior_success.get("market_session") == gate["target_session"] and not force:
            return {**self.post_close_daily_status(), "ok": True, "run_status": "ALREADY COMPLETED", "duplicate": True}
''',
    '''        if prior_success.get("market_session") == gate["target_session"] and not force:
            return {**self.post_close_daily_status(), "ok": True, "run_status": "DUPLICATE_PROTECTED", "duplicate": True}
''',
]
old = next((candidate for candidate in old_candidates if candidate in s), None)
if old is None:
    raise RuntimeError("duplicate-protected daily-flow block missing")
run_status = "ALREADY COMPLETED" if '"ALREADY COMPLETED"' in old else "DUPLICATE_PROTECTED"
new = f'''        if prior_success.get("market_session") == gate["target_session"] and not force:
            result = {{**self.post_close_daily_status(), "ok": True, "run_status": "{run_status}", "duplicate": True}}
            try:
                paper_status = self.phase81_paper_status()
                if paper_status.get("active"):
                    result["paper_portfolio_observation"] = self.phase81_record_today()
            except Exception as exc:
                result["paper_portfolio_observation"] = {{"status": "ERROR", "reason": str(exc)}}
            return result
'''
s = s.replace(old, new, 1)
api.write_text(s, encoding="utf-8")

check = api.read_text(encoding="utf-8")
assert 'APP_VERSION = "0.13.5-phase8-paper-journal-hotfix"' in check
assert 'result["paper_portfolio_observation"] = self.phase81_record_today()' in check
print("0.13.5 Phase 8 paper journal duplicate-path hotfix applied")
