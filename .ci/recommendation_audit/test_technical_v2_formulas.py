from __future__ import annotations

import ast
import math
from pathlib import Path
import types
import unittest

import numpy as np
import pandas as pd


def _load_generated_module():
    source_path = Path(__file__).parents[1] / "native104" / "patch104.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    generated = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "technical_module" for t in node.targets):
            generated = ast.literal_eval(node.value)
            break
    if generated is None:
        raise AssertionError("technical_module source not found")
    module = types.ModuleType("generated_technical_v2")
    exec(compile(generated, "technical_v2.py", "exec"), module.__dict__)
    return module


TECH = _load_generated_module()


class TechnicalFormulaTests(unittest.TestCase):
    def test_numeric_hygiene_rejects_boolean_and_nonfinite(self):
        self.assertIsNone(TECH._finite(True))
        self.assertIsNone(TECH._finite(np.bool_(False)))
        self.assertIsNone(TECH._finite(float("inf")))
        self.assertEqual(TECH._finite("2.5"), 2.5)

    def test_core_formulas_match_independent_pandas_calculation(self):
        index = pd.bdate_range("2024-01-01", periods=280)
        close = pd.Series(100.0 + np.arange(280) * 0.2 + np.sin(np.arange(280) / 7.0), index=index)
        frame = pd.DataFrame(
            {"Open": close - 0.2, "High": close + 1.0, "Low": close - 1.0, "Close": close, "Volume": 1_000_000 + np.arange(280) * 100},
            index=index,
        )
        actual = TECH.compute_features(frame)
        expected_ema20 = close.ewm(span=20, adjust=False, min_periods=20).mean().iloc[-1]
        expected_roc20 = close.pct_change(20).iloc[-1] * 100.0
        expected_macd = (
            close.ewm(span=12, adjust=False, min_periods=12).mean()
            - close.ewm(span=26, adjust=False, min_periods=26).mean()
        ).iloc[-1]
        self.assertTrue(math.isclose(actual["EMA20"].iloc[-1], expected_ema20, rel_tol=0.0, abs_tol=1e-12))
        self.assertTrue(math.isclose(actual["ROC20"].iloc[-1], expected_roc20, rel_tol=0.0, abs_tol=1e-12))
        self.assertTrue(math.isclose(actual["MACD"].iloc[-1], expected_macd, rel_tol=0.0, abs_tol=1e-12))
        self.assertGreaterEqual(actual["RSI14"].iloc[-1], 0.0)
        self.assertLessEqual(actual["RSI14"].iloc[-1], 100.0)

    def test_weekly_join_uses_immediately_prior_completed_week(self):
        index = pd.bdate_range("2023-01-02", periods=420)
        close = pd.Series(100.0 + np.arange(420) * 0.1, index=index)
        frame = pd.DataFrame(
            {"Open": close, "High": close + 1.0, "Low": close - 1.0, "Close": close, "Volume": 1_000.0},
            index=index,
        )
        weekly = frame.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
        expected = weekly["Close"].ewm(span=20, adjust=False, min_periods=20).mean()
        joined = TECH._completed_weekly_features(frame)
        thursday = next(day for day in reversed(index) if day.weekday() == 3)
        prior_friday = expected.index[expected.index < thursday][-1]
        self.assertTrue(math.isclose(joined.loc[thursday, "WeeklyEMA20"], expected.loc[prior_friday], rel_tol=0.0, abs_tol=1e-12))
        friday = next(day for day in reversed(index) if day.weekday() == 4)
        prior_to_friday = expected.index[expected.index < friday][-1]
        self.assertTrue(math.isclose(joined.loc[friday, "WeeklyEMA20"], expected.loc[prior_to_friday], rel_tol=0.0, abs_tol=1e-12))


if __name__ == "__main__":
    unittest.main()
