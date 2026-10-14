import json
import os
from pathlib import Path
import sys
from collections import Counter


repo = Path.cwd()
engine = repo / "work/engine/StockRecommendationEngine_0.8.5_ultra_ui_TEST_SOURCE"
sys.path.insert(0, str(engine))
os.environ["STOCK_REAL_DATA_REPO_ROOT"] = str(repo / "work/current-data")
os.environ["STOCK_MODERN_UI_PREVIEW"] = "0"

from modern_ui.api import ModernAppContext

app_data = repo / "work/accepted-session"
ctx = ModernAppContext(repo_root=engine, app_data_dir=app_data)
run_id = "leg2-20261014T141953Z-59392f33"
ctx._set_active_run(run_id, target_explicit=False, selected_in_session=True)
after = ctx._materialize_live_run(ctx._prediction_run_by_id(run_id))
coverage = ctx.live_coverage()
before = json.loads((repo / "work/final-session-results.json").read_text(encoding="utf-8"))


def summary(data):
    rows = data["candidates"]
    return {
        "universe": len(rows),
        "lane_counts": data["run"].get("lane_counts"),
        "actions": dict(Counter((row.get("live_decision") or {}).get("final_action") for row in rows)),
        "fundamental_quality": dict(Counter((row.get("live_decision") or {}).get("fundamental_data_quality") for row in rows)),
        "cash_flow": dict(Counter((row.get("live_decision") or {}).get("cash_flow_state") for row in rows)),
        "balance_sheet": dict(Counter((row.get("live_decision") or {}).get("balance_sheet_state") for row in rows)),
    }


report = {
    "release": "0.14.1-fundamental-coverage-ui-repair",
    "session": after["run"].get("market_session"),
    "before": summary(before),
    "after": summary(after),
    "coverage": coverage,
}
(repo / "work/0141-current-session-audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps({"before": report["before"], "after": report["after"],
                  "coverage_summary": {k: coverage[k] for k in ("universe_size", "fundamental_ready", "fundamental_partial", "fundamental_unavailable", "financial_domain_count", "nonfinancial_count")},
                  "top_blockers": list(coverage["blocker_counts"].items())[:15],
                  "feature_coverage_counts": coverage["feature_coverage_counts"]}, indent=2))
