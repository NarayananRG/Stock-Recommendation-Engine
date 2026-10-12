from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str], **kwargs) -> None:
    subprocess.run(cmd, check=True, cwd=ROOT, **kwargs)


def seed_phase6_engine() -> Path:
    temp = Path(tempfile.mkdtemp(prefix="sre_phase7_"))
    engine = temp / "engine"
    (engine / "stock_app").mkdir(parents=True)
    (engine / "modern_ui/frontend").mkdir(parents=True)
    (engine / "phase6").mkdir(parents=True)
    env = os.environ.copy()
    env["SRE_ENGINE_ROOT"] = str(engine)
    _run([sys.executable, str(ROOT / ".ci/native106/patch106.py")], env=env)
    app = engine / "modern_ui/frontend/app.js"
    app.write_text(
        """function renderCombinedV2(x){
  $('#combinedV2Decision').textContent=(x.shadow_decision||'NO SIGNAL').replaceAll('_',' ');
  $('#combinedV2Reasons').textContent=(x.reason_codes||[]).length?(x.reason_codes||[]).map(function(v){return String(v).replaceAll('_',' ');}).join(' · '):'Target never enters the Combined V2 score.';
}
""",
        encoding="utf-8",
    )
    (engine / "modern_ui/frontend/styles.css").write_text("", encoding="utf-8")
    _run([sys.executable, str(ROOT / ".ci/native108/patch108_combined_explainability.py")], env=env)
    return engine


def load_module(engine: Path):
    path = engine / "stock_app" / "combined_prediction_v2.py"
    spec = importlib.util.spec_from_file_location("combined_prediction_v2", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    engine = seed_phase6_engine()
    try:
        combined = load_module(engine)
        result = combined.combine(
            {"expected_return": 0.14, "profit_probability": 0.72, "confidence_label": "HIGH"},
            {"technical_score": 76, "evidence_coverage": 0.80, "market_context": {"nifty_regime": "BULL"}},
            {"available": True, "fundamental_score": 34, "score_component_coverage": 0.55},
            analysis_data_current=False,
        )
        exp = result["explainability"]
        cases = [
            ("schema", exp["schema"] == "SRE_COMBINED_V2_EXPLAINABILITY_V1"),
            ("shadow authority", exp["authority"] == "SHADOW_ONLY"),
            ("target excluded", result["target_used_in_score"] is False and "excluded" in exp["target_policy"].lower()),
            ("production authority unchanged", exp["production_authority_changed"] is False),
            ("ranking authority unchanged", exp["ranking_authority_changed"] is False),
            ("promotion blocked", exp["promotion_allowed"] is False),
            ("component summaries", len(exp["component_summaries"]) == 4),
            ("mixed evidence", exp["consensus"] == "MIXED_EVIDENCE"),
            ("data freshness warning", "MARKET_DATA_NOT_CURRENT" in exp["warnings"]),
            ("ui patched", "combinedV2Explainability" in (engine / "modern_ui/frontend/app.js").read_text(encoding="utf-8")),
            ("policy written", "\"active_model_changed\": false" in (engine / "phase7/combined_v2_explainability_policy.json").read_text(encoding="utf-8")),
        ]
        failed = [name for name, ok in cases if not ok]
        for name, ok in cases:
            print(f"{name}: {'PASS' if ok else 'FAIL'}")
        return 1 if failed else 0
    finally:
        shutil.rmtree(engine.parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
