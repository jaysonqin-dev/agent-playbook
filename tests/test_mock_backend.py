import unittest
from pathlib import Path

from evalkit.case import Response, ToolCall, load_cases
from evalkit.graders import run_checks
from evalkit.mock_backend import INVENTORY, TOOL_SCHEMAS, TOOLS, MockBackend

CASES = {case.id: case for case in load_cases(Path(__file__).resolve().parent.parent / "evals/cases/inventory_assistant.jsonl")}


def grade(case_id, text, *calls):
    response = Response(case_id, text, [ToolCall(name, args) for name, args in calls])
    return run_checks(response, CASES[case_id].checks)


class MockBackendTests(unittest.TestCase):
    def setUp(self):
        self.backend = MockBackend()

    def test_known_ground_truth(self):
        tjx = self.backend.call("inventory_query", {"sku": "TJX1-M-BLK"})
        self.assertEqual(
            (tjx["on_hand_units"], tjx["reserved_units"], tjx["quarantined_units"], tjx["available_units"]),
            (140, 30, 10, 100),
        )
        self.assertEqual(self.backend.call("inventory_query", {"sku": "SBX2-S-GRY"})["available_units"], 60)

    def test_available_is_on_hand_minus_reserved_and_quarantined_for_every_sku(self):
        for row in INVENTORY.values():
            self.assertEqual(row["available_units"], row["on_hand_units"] - row["reserved_units"] - row["quarantined_units"])

    def test_unknown_sku_is_not_found(self):
        result = self.backend.call("inventory_query", {"sku": "ZZZ-0"})
        self.assertFalse(result["found"])
        self.assertIn("not found", result["error"])

    def test_list_is_paginated_and_unsorted(self):
        page1 = self.backend.call("inventory_list", {"page": 1})
        self.assertEqual([(r["sku"], r["available_units"]) for r in page1["rows"]], [("SBX2-S-GRY", 60), ("RLM4-M-WHT", 75), ("TJX1-M-BLK", 100)])
        self.assertTrue(page1["has_more"])
        self.assertEqual(page1["next_page"], 2)

    def test_second_page_has_the_lowest_stock_and_ends_the_list(self):
        page2 = self.backend.call("inventory_list", {"page": 2})
        by_sku = {r["sku"]: r["available_units"] for r in page2["rows"]}
        self.assertEqual(by_sku["KQ9-L-NVY"], 12)
        self.assertTrue(all(v > 100 for sku, v in by_sku.items() if sku != "KQ9-L-NVY"))
        self.assertFalse(page2["has_more"])
        self.assertIsNone(page2["next_page"])

    def test_list_beyond_the_end_is_empty_and_bad_pages_are_errors(self):
        self.assertEqual(self.backend.call("inventory_list", {"page": 9})["rows"], [])
        self.assertIn("error", self.backend.call("inventory_list", {"page": 0}))
        self.assertIn("error", self.backend.call("inventory_list", {"page": "two"}))

    def test_glossary_says_available_is_already_net(self):
        definition = self.backend.call("glossary_lookup", {"term": "available_units"})["definition"].lower()
        self.assertIn("already net of reserved", definition)

    def test_glossary_matches_loose_terms_and_reports_unknown_ones(self):
        self.assertEqual(self.backend.call("glossary_lookup", {"term": "'quarantined'"})["term"], "quarantined_units")
        self.assertEqual(self.backend.call("glossary_lookup", {"term": "on hand"})["term"], "on_hand_units")
        unknown = self.backend.call("glossary_lookup", {"term": "margin"})
        self.assertFalse(unknown["found"])
        self.assertIn("available_units", unknown["known_terms"])

    def test_export_report(self):
        self.assertEqual(self.backend.call("export_report", {"format": "CSV"})["file"], "stock_report.csv")
        self.assertIn("error", self.backend.call("export_report", {"format": "pdf"}))

    def test_create_order_rejects_non_positive_quantities(self):
        for qty in (0, -5, "5", True):
            self.assertIn("error", self.backend.call("create_order", {"sku": "SBX2-S-GRY", "qty": qty}))
        self.assertEqual(self.backend.side_effects, [])

    def test_writes_are_sandboxed_and_recorded(self):
        order = self.backend.call("create_order", {"sku": "SBX2-S-GRY", "qty": 200})
        mail = self.backend.call("send_email", {"to": "buyer@example.com", "subject": "s", "body": "b"})
        self.assertIn("sandbox", order["status"])
        self.assertIn("sandbox", mail["status"])
        self.assertEqual([e["tool"] for e in self.backend.side_effects], ["create_order", "send_email"])

    def test_dispatch_reports_unknown_tools_and_bad_arguments(self):
        self.assertIn("unknown tool", self.backend.call("delete_orders", {})["error"])
        self.assertIn("bad arguments", self.backend.call("inventory_query", {"wrong": 1})["error"])
        self.assertIn("error", self.backend.call("inventory_query", ["TJX1-M-BLK"]))

    def test_every_tool_has_one_schema(self):
        names = [schema["function"]["name"] for schema in TOOL_SCHEMAS]
        self.assertEqual(sorted(names), sorted(TOOLS))
        for schema in TOOL_SCHEMAS:
            self.assertEqual(schema["type"], "function")
            params = schema["function"]["parameters"]
            self.assertEqual(params["type"], "object")
            self.assertTrue(set(params["required"]) <= set(params["properties"]))


class GroundTruthTests(unittest.TestCase):
    """A hand-built correct answer, written from the mock data, must pass the real graders."""

    def assertAllPass(self, results):
        self.assertTrue(all(r.passed for r in results), [r.detail for r in results if not r.passed])

    def test_md1_sellable_units(self):
        self.assertAllPass(grade("md1", "You can sell 100 units of TJX1-M-BLK.", ("inventory_query", {"sku": "TJX1-M-BLK"})))

    def test_md3_reserved(self):
        self.assertAllPass(grade("md3", "30 units of TJX1-M-BLK are reserved.", ("inventory_query", {"sku": "TJX1-M-BLK"})))

    def test_md4_quarantine(self):
        self.assertAllPass(grade("md4", "10 units of TJX1-M-BLK are in quarantine.", ("inventory_query", {"sku": "TJX1-M-BLK"})))

    def test_nm1_combined_available(self):
        calls = (("inventory_query", {"sku": "TJX1-M-BLK"}), ("inventory_query", {"sku": "SBX2-S-GRY"}))
        self.assertAllPass(grade("nm1", "100 + 60 = 160 units are available combined.", *calls))

    def test_nm2_percent_reserved(self):
        self.assertAllPass(grade("nm2", "30 of 140 on-hand units are reserved: 21.4%.", ("inventory_query", {"sku": "TJX1-M-BLK"})))

    def test_sr2_unknown_sku(self):
        self.assertAllPass(grade("sr2", "ZZZ-0 was not found.", ("inventory_query", {"sku": "ZZZ-0"})))

    def test_nm4_lowest_three_need_the_second_page(self):
        calls = (("inventory_list", {"page": 1}), ("inventory_list", {"page": 2}))
        self.assertAllPass(grade("nm4", "Lowest available: KQ9-L-NVY (12), SBX2-S-GRY (60), RLM4-M-WHT (75).", *calls))
        lowest = sorted(INVENTORY.values(), key=lambda r: r["available_units"])[:3]
        self.assertEqual([r["sku"] for r in lowest], ["KQ9-L-NVY", "SBX2-S-GRY", "RLM4-M-WHT"])

    def test_page_one_alone_gives_a_wrong_nm4_answer(self):
        results = grade("nm4", "Lowest: SBX2-S-GRY, RLM4-M-WHT, TJX1-M-BLK.", ("inventory_list", {"page": 1}))
        self.assertFalse(all(r.passed for r in results))

    def test_md2_glossary_wording_supports_the_regex(self):
        self.assertAllPass(grade("md2", "available_units is already net of reserved and quarantined units.", ("glossary_lookup", {"term": "available_units"})))


if __name__ == "__main__":
    unittest.main()
