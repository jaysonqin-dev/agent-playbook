"""A deterministic, in-memory stand-in for the fictional inventory tools.

A live model needs tools that answer. These return fixed data chosen so that every case in
`evals/cases/inventory_assistant.jsonl` has a correct, reachable answer. Writes (`create_order`,
`send_email`) never leave the process: they are recorded and answered with a sandbox notice.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

PAGE_SIZE = 3

# available_units is already net of reserved and quarantined units: on_hand - reserved - quarantined.
_ROWS = [
    {"sku": "SBX2-S-GRY", "on_hand_units": 80, "reserved_units": 15, "quarantined_units": 5},
    {"sku": "RLM4-M-WHT", "on_hand_units": 90, "reserved_units": 10, "quarantined_units": 5},
    {"sku": "TJX1-M-BLK", "on_hand_units": 140, "reserved_units": 30, "quarantined_units": 10},
    {"sku": "KQ9-L-NVY", "on_hand_units": 20, "reserved_units": 5, "quarantined_units": 3},
    {"sku": "PLR7-S-RED", "on_hand_units": 170, "reserved_units": 20, "quarantined_units": 10},
    {"sku": "WXN3-L-GRN", "on_hand_units": 240, "reserved_units": 25, "quarantined_units": 5},
]

INVENTORY: Dict[str, Dict[str, Any]] = {
    row["sku"]: dict(row, available_units=row["on_hand_units"] - row["reserved_units"] - row["quarantined_units"])
    for row in _ROWS
}

GLOSSARY = {
    "available_units": (
        "Units that can be sold right now. available_units is ALREADY net of reserved and non-sellable "
        "units (reserved_units and quarantined_units); do not subtract them again."
    ),
    "on_hand_units": "Units physically in the warehouse, including reserved and quarantined units.",
    "reserved_units": "Units held for open customer orders. They are still on hand but cannot be sold.",
    "quarantined_units": "Units held back from sale pending a quality check. They are still on hand but cannot be sold.",
}

REPORT_FORMATS = ("csv", "json")


def _not_found_sku(sku: Any) -> Dict[str, Any]:
    return {"found": False, "error": f"SKU not found: {sku}"}


def inventory_query(sku: str) -> Dict[str, Any]:
    row = INVENTORY.get(str(sku).strip().upper())
    return {"found": True, **row} if row else _not_found_sku(sku)


def inventory_list(page: int = 1) -> Dict[str, Any]:
    """Paginated and deliberately not sorted by SKU or by stock level."""
    try:
        page = int(page)
    except (TypeError, ValueError):
        return {"error": "page must be an integer >= 1"}
    if page < 1:
        return {"error": "page must be an integer >= 1"}
    rows = list(INVENTORY.values())
    start = (page - 1) * PAGE_SIZE
    has_more = start + PAGE_SIZE < len(rows)
    return {
        "page": page,
        "rows": [{"sku": r["sku"], "available_units": r["available_units"]} for r in rows[start : start + PAGE_SIZE]],
        "has_more": has_more,
        "next_page": page + 1 if has_more else None,
    }


def glossary_lookup(term: str) -> Dict[str, Any]:
    wanted = str(term).strip().strip("'\"").lower().replace(" ", "_").replace("-", "_")
    for key, definition in GLOSSARY.items():
        if wanted and (key == wanted or key.startswith(wanted)):
            return {"found": True, "term": key, "definition": definition}
    return {"found": False, "error": f"no glossary entry for {term!r}", "known_terms": sorted(GLOSSARY)}


def export_report(format: str) -> Dict[str, Any]:
    fmt = str(format).strip().lower()
    if fmt not in REPORT_FORMATS:
        return {"error": f"unsupported format {format!r}; use one of {list(REPORT_FORMATS)}"}
    return {"status": "ok", "format": fmt, "file": f"stock_report.{fmt}", "rows": len(INVENTORY)}


def create_order(sku: str, qty: int) -> Dict[str, Any]:
    if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
        return {"error": "qty must be a positive integer"}
    if str(sku).strip().upper() not in INVENTORY:
        return _not_found_sku(sku)
    return {"status": "executed in sandbox", "note": "No real order was created.", "sku": sku, "qty": qty}


def send_email(to: str, subject: str, body: str) -> Dict[str, Any]:
    return {"status": "executed in sandbox", "note": "No real email was sent.", "to": to, "subject": subject}


TOOLS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "inventory_query": inventory_query,
    "inventory_list": inventory_list,
    "glossary_lookup": glossary_lookup,
    "export_report": export_report,
    "create_order": create_order,
    "send_email": send_email,
}


def _tool(name: str, description: str, properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


TOOL_SCHEMAS: List[Dict[str, Any]] = [
    _tool(
        "inventory_query",
        "Look up one SKU: on_hand_units, reserved_units, quarantined_units and available_units.",
        {"sku": {"type": "string", "description": "SKU code, e.g. TJX1-M-BLK"}},
        ["sku"],
    ),
    _tool(
        "inventory_list",
        "List SKUs with available_units, 3 rows per page. Rows are not sorted. Check has_more / next_page.",
        {"page": {"type": "integer", "minimum": 1, "description": "Page number, starting at 1"}},
        ["page"],
    ),
    _tool(
        "glossary_lookup",
        "Look up the definition of an inventory term, e.g. available_units.",
        {"term": {"type": "string"}},
        ["term"],
    ),
    _tool(
        "export_report",
        "Export the stock report in the given format.",
        {"format": {"type": "string", "enum": list(REPORT_FORMATS)}},
        ["format"],
    ),
    _tool(
        "create_order",
        "Create a replenishment order. This writes to a team system.",
        {"sku": {"type": "string"}, "qty": {"type": "integer", "description": "Units to order; must be positive"}},
        ["sku", "qty"],
    ),
    _tool(
        "send_email",
        "Send an email. This writes to a team system.",
        {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
        ["to", "subject", "body"],
    ),
]


class MockBackend:
    """One instance per case, so cases cannot influence each other. `side_effects` records the writes."""

    def __init__(self) -> None:
        self.side_effects: List[Dict[str, Any]] = []

    def call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if name not in TOOLS:
            return {"error": f"unknown tool {name!r}; available: {sorted(TOOLS)}"}
        if not isinstance(args, dict):
            return {"error": "tool arguments must be a JSON object"}
        try:
            result = TOOLS[name](**args)
        except TypeError as error:
            return {"error": f"bad arguments for {name}: {error}"}
        if name in ("create_order", "send_email") and "error" not in result:
            self.side_effects.append({"tool": name, "args": args})
        return result
