import unittest

from evalkit.case import Response, ToolCall
from evalkit.graders import run_check


def answer(text="", *calls):
    return Response("x", text, [ToolCall(name, args) for name, args in calls])


class GraderTests(unittest.TestCase):
    def test_contains_is_case_insensitive_by_default(self):
        self.assertTrue(run_check(answer("Planned Actions: ..."), {"check": "contains", "value": "planned actions"}).passed)
        self.assertFalse(run_check(answer("Planned Actions"), {"check": "contains", "value": "planned actions", "case_sensitive": True}).passed)

    def test_not_contains_fails_when_present(self):
        result = run_check(answer("that is 70 units"), {"check": "not_contains", "value": "70 units"})
        self.assertFalse(result.passed)
        self.assertIn("70 units", result.detail)

    def test_regex_matches_across_lines(self):
        self.assertTrue(run_check(answer("a\n1. first\n2. second"), {"check": "regex", "pattern": r"(^|\n)\s*1\.\s"}).passed)

    def test_number_close_reads_the_first_capture_group(self):
        spec = {"check": "number_close", "pattern": r"(\d[\d,]*)\s*units", "expected": 1200}
        self.assertTrue(run_check(answer("about 1,200 units left"), spec).passed)
        self.assertFalse(run_check(answer("about 1,300 units left"), spec).passed)

    def test_number_close_respects_the_tolerance(self):
        spec = {"check": "number_close", "pattern": r"([\d.]+)%", "expected": 21.4, "tol": 0.1}
        self.assertTrue(run_check(answer("21.5%"), spec).passed)
        self.assertFalse(run_check(answer("21.6%"), spec).passed)

    def test_number_close_fails_cleanly_when_nothing_matches(self):
        result = run_check(answer("no figures here"), {"check": "number_close", "pattern": r"(\d+)\s*%", "expected": 1})
        self.assertFalse(result.passed)
        self.assertIn("no match", result.detail)

    def test_tool_called_checks_arguments_as_a_subset(self):
        response = answer("", ("inventory_query", {"sku": "A", "limit": 5}))
        self.assertTrue(run_check(response, {"check": "tool_called", "name": "inventory_query", "args": {"sku": "A"}}).passed)
        self.assertFalse(run_check(response, {"check": "tool_called", "name": "inventory_query", "args": {"sku": "B"}}).passed)

    def test_tool_called_failure_shows_what_was_actually_called(self):
        result = run_check(answer("", ("export_report", {"format": "xlsx"})), {"check": "tool_called", "name": "export_report", "args": {"format": "csv"}})
        self.assertIn('export_report({"format": "xlsx"})', result.detail)

    def test_tool_not_called(self):
        self.assertTrue(run_check(answer(""), {"check": "tool_not_called", "name": "send_email"}).passed)
        self.assertFalse(run_check(answer("", ("send_email", {})), {"check": "tool_not_called", "name": "send_email"}).passed)

    def test_tool_order(self):
        response = answer("", ("inventory_query", {}), ("create_order", {}))
        self.assertTrue(run_check(response, {"check": "tool_order", "before": "inventory_query", "after": "create_order"}).passed)
        self.assertFalse(run_check(response, {"check": "tool_order", "before": "create_order", "after": "inventory_query"}).passed)
        self.assertFalse(run_check(answer(""), {"check": "tool_order", "before": "a", "after": "b"}).passed)

    def test_max_words(self):
        self.assertTrue(run_check(answer("one two three"), {"check": "max_words", "value": 3}).passed)
        self.assertFalse(run_check(answer("one two three four"), {"check": "max_words", "value": 3}).passed)

    def test_json_fields_checks_presence_and_types(self):
        spec = {"check": "json_fields", "fields": {"sku": "string", "available": "number"}}
        self.assertTrue(run_check(answer('Here: {"sku": "A", "available": 3}'), spec).passed)
        self.assertFalse(run_check(answer('{"sku": "A"}'), spec).passed)
        self.assertFalse(run_check(answer('{"sku": "A", "available": "3"}'), spec).passed)
        self.assertFalse(run_check(answer("no json"), spec).passed)

    def test_a_boolean_is_not_a_number(self):
        spec = {"check": "json_fields", "fields": {"available": "number"}}
        self.assertFalse(run_check(answer('{"available": true}'), spec).passed)

    def test_unknown_check_names_the_known_ones(self):
        with self.assertRaises(ValueError) as caught:
            run_check(answer(""), {"check": "vibes"})
        self.assertIn("contains", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
