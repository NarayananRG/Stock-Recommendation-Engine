from pathlib import Path
import json
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])

def repl(text, old, new, label):
    if old not in text:
        raise RuntimeError(label + " contract missing")
    return text.replace(old, new, 1)

api = root / "modern_ui" / "api.py"
s = api.read_text(encoding="utf-8")
s = repl(s, 'APP_VERSION = "0.11.0-phase5-fundamental-v3"', 'APP_VERSION = "0.12.0-phase6-combined-prediction-v2"', "version")

anchor = '        self.active_analysis_file = self.config.app_data_dir / "active_analysis_run.json"\n'
if "_phase6_run_selected_in_session" not in s:
    s = repl(s, anchor, anchor + '        self._phase6_run_selected_in_session = False\n', "session state")

old = '''    def _set_active_run(self, run_id: str) -> dict[str, Any] | None:
        data = self._prediction_run_by_id(run_id)
        if not data:
            return None
        self.active_analysis_file.parent.mkdir(parents=True, exist_ok=True)
        self.active_analysis_file.write_text(
            json.dumps({"run_id": run_id, "updated_at": datetime.now().isoformat(timespec="seconds")}, indent=2),
            encoding="utf-8",
        )
        return data

'''
new = '''    def _active_run_metadata(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.active_analysis_file.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}

    def _set_active_run(
        self,
        run_id: str,
        *,
        target_explicit: bool | None = None,
        target_origin: str | None = None,
        selected_in_session: bool = False,
    ) -> dict[str, Any] | None:
        data = self._prediction_run_by_id(run_id)
        if not data:
            return None
        previous = self._active_run_metadata()
        payload = {"run_id": run_id, "updated_at": datetime.now().isoformat(timespec="seconds")}
        if previous.get("run_id") == run_id:
            for key in ("target_explicit", "target_origin"):
                if key in previous:
                    payload[key] = previous[key]
        if target_explicit is not None:
            payload["target_explicit"] = bool(target_explicit)
        if target_origin is not None:
            payload["target_origin"] = str(target_origin)
        self.active_analysis_file.parent.mkdir(parents=True, exist_ok=True)
        self.active_analysis_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if selected_in_session:
            self._phase6_run_selected_in_session = True
        return data

'''
s = repl(s, old, new, "active run metadata")

old = '''    def active_prediction_run(self) -> dict[str, Any] | None:
        saved = self._prediction_run_by_id(self._saved_active_run_id())
        if saved:
            return saved
        latest = self.historical.get_latest_run()
        if latest and latest.get("run", {}).get("run_id"):
            return self._set_active_run(str(latest["run"]["run_id"]))
        return None

'''
new = '''    def active_prediction_run(self) -> dict[str, Any] | None:
        return self._prediction_run_by_id(self._saved_active_run_id())

    def active_target_state(self) -> dict[str, Any]:
        active = self.active_prediction_run()
        run = {} if not active else dict(active.get("run") or {})
        raw_target = _finite(run.get("target_return"))
        meta = self._active_run_metadata()
        same_run = bool(run.get("run_id")) and str(meta.get("run_id") or "") == str(run.get("run_id") or "")
        explicit = bool(same_run and meta.get("target_explicit") is True and raw_target is not None)
        legacy_unconfirmed = bool(raw_target is not None and not explicit)
        restored = bool(explicit and not self._phase6_run_selected_in_session)
        if explicit:
            origin = "RESTORED_EXPLICIT_USER_TARGET" if restored else str(meta.get("target_origin") or "USER_SUPPLIED")
        elif legacy_unconfirmed:
            origin = "LEGACY_RESTORED_UNCONFIRMED"
        else:
            origin = "NONE"
        return {
            "explicit": explicit,
            "value": raw_target if explicit else None,
            "raw_persisted_value": raw_target,
            "origin": origin,
            "restored": restored,
            "legacy_unconfirmed": legacy_unconfirmed,
            "display_status": "EXPLICIT_TARGET" if explicit else "NO_TARGET",
        }

    def ui_run_input(self) -> dict[str, Any] | None:
        active = self.active_prediction_run()
        if not active:
            return None
        run = dict(active.get("run") or {})
        state = self.active_target_state()
        if not state["explicit"]:
            run["target_return"] = None
        run["target_explicit"] = state["explicit"]
        run["target_origin"] = state["origin"]
        run["target_restored"] = state["restored"]
        return run

'''
s = repl(s, old, new, "first launch state")
s = repl(s, '            self._set_active_run(str(match["run"]["run_id"]))\n', '            self._set_active_run(str(match["run"]["run_id"]), target_explicit=target is not None, target_origin="USER_SUPPLIED" if target is not None else "NONE", selected_in_session=True)\n', "matched run")
s = repl(s, '        self._set_active_run(run.run_id)\n', '        self._set_active_run(run.run_id, target_explicit=target is not None, target_origin="USER_SUPPLIED" if target is not None else "NONE", selected_in_session=True)\n', "new run")

old = '''            item["target_return_request"] = run["target_return"]
            expected = _finite(item.get("expected_return"))
            requested = _finite(run.get("target_return"))
            item["meets_target"] = None if requested is None or expected is None else expected >= requested
            item["target_gap"] = None if requested is None or expected is None else expected - requested
            item["target_status"] = "NO TARGET" if requested is None else ("MEETS TARGET" if item["meets_target"] else "BELOW TARGET")
'''
new = '''            target_state = self.active_target_state()
            item["target_return_request"] = run["target_return"] if target_state.get("explicit") else None
            item["target_explicit"] = bool(target_state.get("explicit"))
            item["target_origin"] = target_state.get("origin")
            item["target_restored"] = bool(target_state.get("restored"))
            expected = _finite(item.get("expected_return"))
            requested = _finite(run.get("target_return")) if target_state.get("explicit") else None
            item["meets_target"] = None if requested is None or expected is None else expected >= requested
            item["target_gap"] = None if requested is None or expected is None else expected - requested
            item["target_status"] = "NO TARGET" if requested is None else ("MEETS TARGET" if item["meets_target"] else "BELOW TARGET")
'''
s = repl(s, old, new, "target display")

needle = '        prediction = dict(pred) if pred else None\n'
addition = '''        prediction = dict(pred) if pred else None
        if prediction:
            target_state = self.active_target_state()
            prediction["target_explicit"] = bool(target_state.get("explicit"))
            prediction["target_origin"] = target_state.get("origin")
            prediction["target_restored"] = bool(target_state.get("restored"))
            if not target_state.get("explicit"):
                prediction["target_return_request"] = None
                prediction["target_status"] = "NO TARGET"
'''
s = repl(s, needle, addition, "stock target state")

stock_anchor = '    def stock_context(self, symbol: str, limit: int) -> dict[str, Any]:\n'
helper = '''    def combined_v2_context(
        self,
        symbol: str,
        prediction: dict[str, Any] | None = None,
        bars: list[dict[str, Any]] | None = None,
        latest_price: float | None = None,
    ) -> dict[str, Any]:
        from stock_app.combined_prediction_v2 import combine
        symbol = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        source_bars = list(bars) if bars is not None else self.prices.history(symbol, limit=5000)
        if latest_price is None and source_bars:
            latest_price = _finite(source_bars[-1].get("close"))
        if prediction is None:
            prediction = next((row for row in self.latest_prediction_rows(limit=100) if str(row.get("symbol") or "").upper().replace(".NS", "").replace(".BO", "") == symbol), None)
        technical = self.technical_v2_context(symbol, source_bars)
        decision_timestamp = (prediction or {}).get("market_session") or (source_bars[-1].get("date") if source_bars else None)
        fundamental = self.fundamental_v3_context(symbol, latest_price, decision_timestamp)
        current = bool((self.data_source_status().get("active") or {}).get("analysis_data_current"))
        return combine(prediction, technical, fundamental, analysis_data_current=current)

'''
if "def combined_v2_context" not in s:
    s = repl(s, stock_anchor, helper + stock_anchor, "combined helper")

old = '''            "fundamental_v3": self.fundamental_v3_context(
                symbol,
                close,
                (prediction or {}).get("market_session") or last.get("date"),
            ),
        }
'''
new = '''            "fundamental_v3": self.fundamental_v3_context(
                symbol,
                close,
                (prediction or {}).get("market_session") or last.get("date"),
            ),
            "combined_v2": self.combined_v2_context(symbol, prediction, bars, close),
        }
'''
s = repl(s, old, new, "stock response")

fund_route = '''    @app.get("/api/stocks/{symbol}/fundamental-v3")
    def stock_fundamental_v3(symbol: str) -> dict[str, Any]:
        bars = ctx.prices.history(symbol, limit=2)
        latest_price = float(bars[-1]["close"]) if bars else None
        active = ctx.latest_run_input() or {}
        decision_timestamp = active.get("market_session") or (bars[-1]["date"] if bars else None)
        return ctx.fundamental_v3_context(symbol, latest_price, decision_timestamp)

'''
route = fund_route + '''    @app.get("/api/stocks/{symbol}/combined-v2")
    def stock_combined_v2(symbol: str) -> dict[str, Any]:
        bars = ctx.prices.history(symbol, limit=5000)
        latest_price = float(bars[-1]["close"]) if bars else None
        clean = symbol.upper().replace(".NS", "").replace(".BO", "")
        prediction = next((row for row in ctx.latest_prediction_rows(limit=100) if str(row.get("symbol") or "").upper().replace(".NS", "").replace(".BO", "") == clean), None)
        return ctx.combined_v2_context(symbol, prediction, bars, latest_price)

'''
s = repl(s, fund_route, route, "combined endpoint")
s = repl(s, '        return {"items": rows, "count": len(rows), "run": ctx.latest_run_input()}\n', '        return {"items": rows, "count": len(rows), "run": ctx.ui_run_input(), "target_state": ctx.active_target_state()}\n', "opportunities get")
s = repl(s, '        return {"ok": True, "items": rows, "count": len(rows), "fundamentals": None, "run": dict(active.get("run") or {}), "reused_run": reused}\n', '        return {"ok": True, "items": rows, "count": len(rows), "fundamentals": None, "run": ctx.ui_run_input(), "target_state": ctx.active_target_state(), "reused_run": reused}\n', "opportunities post")
s = repl(s, '        latest = ctx.latest_run_input()\n        return {"latest_run": latest}\n', '        latest = ctx.ui_run_input()\n        return {"latest_run": latest, "target_state": ctx.active_target_state()}\n', "capital default")
s = repl(s, '            "active_run": ctx.latest_run_input(),\n            "data_source": ctx.data_source_status(),\n', '            "active_run": ctx.ui_run_input(),\n            "target_state": ctx.active_target_state(),\n            "data_source": ctx.data_source_status(),\n', "dashboard state")

api.write_text(s, encoding="utf-8")
assert "LEGACY_RESTORED_UNCONFIRMED" in s
assert "combined_v2" in s
assert "0.12.0-phase6-combined-prediction-v2" in s
print("Phase 6 API integration applied")
