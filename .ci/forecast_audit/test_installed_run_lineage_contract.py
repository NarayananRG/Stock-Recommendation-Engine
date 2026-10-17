"""Prevent stale pre-refresh Run ID assertions after post-close daily flow."""
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[2] / ".github/workflows/build-native-desktop-01413.yml").read_text(encoding="utf-8")

class InstalledRunLineageContract(unittest.TestCase):
    def test_current_run_consistency_after_daily_refresh(self):
        start = SOURCE.index('$duplicatePaper = Invoke-RestMethod "http://127.0.0.1:$port/api/post-close-daily-flow"')
        end = SOURCE.index('if ($stockPhase.technical_v2.schema', start)
        stage = SOURCE[start:end]
        self.assertIn('if (!$dashboardRunId) { throw "Installed Dashboard lost active Run ID after post-close" }',stage)
        self.assertIn('if ([string]$stockPhase.active_run.run_id -ne $dashboardRunId)',stage)
        self.assertIn('if ([string]$dash.active_run.market_session -ne [string]$run.run.market_session)',stage)
        self.assertNotIn('if ([string]$dash.active_run.run_id -ne $installedRunId)',stage)
        self.assertNotIn('if ([string]$stockPhase.active_run.run_id -ne $installedRunId)',stage)
        self.assertIn('Duplicate daily flow duplicated a decision, order, fill, or snapshot',stage)

if __name__ == "__main__":
    unittest.main()
