import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from monitor.metrics import Event, alerts, parse_events, weekly_metrics

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "monitoring" / "sample_logs.jsonl"


def event(day, *, corrected=False, tool_errors=0, version="v1", latency=1000, turns=1, month=3):
    return Event(datetime(2026, month, day, 9, 0, tzinfo=timezone.utc), "s", "c", ["t"], tool_errors, corrected, turns, latency, version)


def week_of(start_day, n, corrected, errors, version="v1"):
    return [event(start_day, corrected=i < corrected, tool_errors=1 if i < errors else 0, version=version) for i in range(n)]


class MetricsTests(unittest.TestCase):
    def test_events_are_grouped_by_iso_week(self):
        metrics = weekly_metrics([event(2), event(4), event(9)])  # Mon, Wed, next Mon
        self.assertEqual([m.week for m in metrics], ["2026-W10", "2026-W11"])
        self.assertEqual([m.events for m in metrics], [2, 1])

    def test_rates_are_shares_of_events(self):
        metrics = weekly_metrics(week_of(2, 10, corrected=3, errors=2))
        self.assertAlmostEqual(metrics[0].correction_rate, 0.3)
        self.assertAlmostEqual(metrics[0].tool_error_rate, 0.2)

    def test_p95_latency_uses_the_nearest_rank(self):
        events = [event(2, latency=value) for value in range(1, 101)]
        self.assertEqual(weekly_metrics(events)[0].p95_latency_ms, 95)

    def test_versions_seen_in_a_week_are_listed(self):
        events = [event(2, version="v2"), event(3, version="v1")]
        self.assertEqual(weekly_metrics(events)[0].rules_versions, ["v1", "v2"])

    def test_median_turns(self):
        events = [event(2, turns=t) for t in (1, 2, 9)]
        self.assertEqual(weekly_metrics(events)[0].median_turns, 2)


class AlertTests(unittest.TestCase):
    def steady_then(self, corrected, errors):
        events = []
        for start in (2, 9, 16):
            events += week_of(start, 40, corrected=4, errors=2)  # 10% and 5%
        events += week_of(23, 40, corrected=corrected, errors=errors, version="v2")
        return weekly_metrics(events)

    def test_a_clear_jump_alerts_and_names_the_instruction_version(self):
        found = alerts(self.steady_then(corrected=16, errors=2))
        self.assertEqual([a.metric for a in found], ["correction rate"])
        self.assertEqual(found[0].versions, ["v2"])

    def test_a_small_move_is_not_an_alert(self):
        self.assertEqual(alerts(self.steady_then(corrected=6, errors=3)), [])  # 15% vs 10%, 7.5% vs 5%

    def test_a_relative_jump_from_a_tiny_base_is_not_an_alert(self):
        events = []
        for start in (2, 9, 16):
            events += week_of(start, 40, corrected=0, errors=0)
        events += week_of(23, 40, corrected=1, errors=1)  # 0% -> 2.5%: relatively huge, absolutely small
        self.assertEqual(alerts(weekly_metrics(events)), [])

    def test_weeks_with_too_few_events_never_alert(self):
        events = week_of(2, 40, 4, 2) + week_of(9, 40, 4, 2) + week_of(16, 5, 5, 5)
        self.assertEqual(alerts(weekly_metrics(events)), [])

    def test_the_first_weeks_have_no_baseline_so_they_cannot_alert(self):
        self.assertEqual(alerts(weekly_metrics(week_of(2, 40, 20, 20))), [])

    def test_both_metrics_can_alert_in_the_same_week(self):
        found = alerts(self.steady_then(corrected=16, errors=10))
        self.assertEqual({a.metric for a in found}, {"correction rate", "tool error rate"})


class SampleLogTests(unittest.TestCase):
    def test_the_sample_log_parses(self):
        self.assertGreater(len(parse_events(SAMPLE)), 200)

    def test_the_sample_log_alerts_only_in_the_week_of_the_bad_release(self):
        found = alerts(weekly_metrics(parse_events(SAMPLE)))
        self.assertTrue(found)
        self.assertEqual({a.week for a in found}, {"2026-W13"})
        self.assertEqual({tuple(a.versions) for a in found}, {("v14",)})

    def test_a_bad_line_reports_its_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.jsonl"
            path.write_text(json.dumps({"ts": "2026-03-02T09:00:00Z"}) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                parse_events(path)
            self.assertIn(":1:", str(caught.exception))

    def test_the_cli_exit_code_reflects_alerts_only_when_asked(self):
        base = [sys.executable, "-m", "monitor", "report", "--logs", str(SAMPLE)]
        self.assertEqual(subprocess.run(base, cwd=ROOT, capture_output=True).returncode, 0)
        self.assertEqual(subprocess.run(base + ["--fail-on-alert"], cwd=ROOT, capture_output=True).returncode, 1)


if __name__ == "__main__":
    unittest.main()
