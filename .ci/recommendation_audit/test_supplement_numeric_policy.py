from __future__ import annotations

import ast
import math
from pathlib import Path
import unittest


def _load_validator():
    source_path = Path(__file__).parents[1] / "native150" / "build_official_safety_supplement.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "valid_corporate_debt_equity"
    )
    namespace = {"math": math}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source_path), "exec"), namespace)
    return namespace["valid_corporate_debt_equity"]


VALID = _load_validator()


class SupplementNumericPolicyTests(unittest.TestCase):
    def test_accepts_zero_and_realistic_positive_value(self):
        self.assertTrue(VALID(0.0))
        self.assertTrue(VALID("1.17"))

    def test_rejects_negative_ratios(self):
        self.assertFalse(VALID(-0.25))
        self.assertFalse(VALID(-30.39))

    def test_rejects_boolean_nonfinite_and_extreme_values(self):
        self.assertFalse(VALID(True))
        self.assertFalse(VALID(float("nan")))
        self.assertFalse(VALID(float("inf")))
        self.assertFalse(VALID(100.01))


if __name__ == "__main__":
    unittest.main()
