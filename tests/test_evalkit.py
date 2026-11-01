import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from evalkit.case import Response, load_cases, load_responses
from evalkit.report import compare, summarize
from evalkit.runner import run_cases

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "evals" / "cases" / "inventory_assistant.jsonl"
V1 = ROOT / "evals" / "transcripts" / "v1.jsonl"
V2 = ROOT / "evals" / "transcripts" / "v2.jsonl"


def write(directory, name, rows):
    path = Path(directory) / name
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


class LoadingTests(unittest.TestCase):
    def test_the_shipped_case_set_is_valid_and_has_unique_ids(self):
        cases = load_cases(CASES)
        self.assertEqual(len(cases), 25)
        self.assertEqual(len({case.id for case in cases}), 25)

    def test_every_case_has_a_recorded_response_in_both_runs(self):
        ids = {case.id for case in load_cases(CASES)}
        self.assertEqual(ids, set(load_responses(V1)))
        self.assertEqual(ids, set(load_responses(V2)))

    def test_duplicate_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = {"id": "a", "category": "c", "prompt": "p", "checks": [{"check": "contains", "value": "x"}]}
            with self.assertRaises(ValueError):
                load_cases(write(tmp, "c.jsonl", [row, row]))

    def test_a_case_without_checks_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                load_cases(write(tmp, "c.jsonl", [{"id": "a", "category": "c", "prompt": "p", "checks": []}]))

    def test_bad_json_reports_the_line_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.jsonl"
            path.write_text('{"id": "a"}\n{not json}\n', encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                load_cases(path)
            self.assertIn(":2:", str(caught.exception))


class RunnerTests(unittest.TestCase):
    def test_a_missing_answer_is_a_failure_not_a_skip(self):
        results = run_cases(load_cases(CASES), {})
        self.assertTrue(all(not r.passed and not r.answered for r in results))
        self.assertEqual(summarize(results).passed, 0)

    def test_a_callable_agent_can_be_evaluated_live(self):
        results = run_cases(load_cases(CASES)[:1], lambda case: Response(case.id, "100 units. available_units is already net of reserved.", []))
        self.assertTrue(results[0].answered)

    def test_the_two_shipped_runs_score_as_documented(self):
        cases = load_cases(CASES)
        self.assertEqual(summarize(run_cases(cases, load_responses(V1))).passed, 18)
        self.assertEqual(summarize(run_cases(cases, load_responses(V2))).passed, 23)

    def test_compare_separates_fixed_regressed_and_still_failing(self):
        cases = load_cases(CASES)
        delta = compare(run_cases(cases, load_responses(V1)), run_cases(cases, load_responses(V2)))
        self.assertEqual(sorted(delta["fixed"]), ["ap1", "fm3", "md1", "nm1", "sr2", "tr3"])
        self.assertEqual(delta["regressed"], ["tr4"])
        self.assertEqual(delta["still_failing"], ["nm4"])

    def test_a_higher_pass_rate_can_still_hide_a_regression(self):
        cases = load_cases(CASES)
        before, after = run_cases(cases, load_responses(V1)), run_cases(cases, load_responses(V2))
        self.assertGreater(summarize(after).pass_rate, summarize(before).pass_rate)
        self.assertTrue(compare(before, after)["regressed"])

    def test_category_breakdown_adds_up(self):
        report = summarize(run_cases(load_cases(CASES), load_responses(V1)))
        self.assertEqual(sum(t for _, t in report.by_category.values()), report.total)
        self.assertEqual(sum(p for p, _ in report.by_category.values()), report.passed)


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "evalkit", *args], cwd=ROOT, capture_output=True, text=True)

    def test_gate_passes_when_the_pass_rate_is_high_enough(self):
        done = self.run_cli("run", "--cases", str(CASES), "--responses", str(V2), "--gate", "0.9")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("23/25", done.stdout)

    def test_gate_fails_below_the_threshold(self):
        done = self.run_cli("run", "--cases", str(CASES), "--responses", str(V1), "--gate", "0.9")
        self.assertEqual(done.returncode, 1)
        self.assertIn("GATE FAILED", done.stderr)

    def test_diff_can_fail_on_regression(self):
        done = self.run_cli("diff", "--cases", str(CASES), "--before", str(V1), "--after", str(V2), "--fail-on-regression")
        self.assertEqual(done.returncode, 1)
        self.assertIn("regressed: tr4", done.stdout)

    def test_json_output_is_machine_readable(self):
        done = self.run_cli("run", "--cases", str(CASES), "--responses", str(V1), "--json")
        data = json.loads(done.stdout)
        self.assertEqual((data["passed"], data["total"]), (18, 25))
        self.assertEqual(len(data["cases"]), 25)


if __name__ == "__main__":
    unittest.main()
