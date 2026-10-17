"""Catch malformed embedded Python before expensive Windows packaging."""
import ast
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/build-native-desktop-01413.yml"

class EmbeddedPythonAcceptanceTests(unittest.TestCase):
    def test_installed_paper_seed_python_compiles(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        anchor = 'SRE_ACCEPTANCE_SEED_RESULT = $seedResultPath'
        self.assertEqual(source.count(anchor), 1)
        start = source.index("          @'\n", source.index(anchor)) + len("          @'\n")
        end = source.index("          '@ | python -", start)
        lines = source[start:end].splitlines()
        self.assertTrue(lines)
        for i, line in enumerate(lines, 1):
            if line.strip():
                self.assertTrue(line.startswith("          "), f"YAML line {i} below 10-space baseline")
        script = "\n".join(line[10:] if line.strip() else "" for line in lines)
        self.assertTrue(script.startswith("import json\n"), "Embedded script must start at column zero")
        ast.parse(script)

if __name__ == "__main__":
    unittest.main()
