"""Deterministic graders. Each takes a Response and its parameters and returns pass/fail with a reason.

Deterministic on purpose: a grader that is itself a model adds variance to the thing being measured.
Use a model-based judge only for what these cannot express, and calibrate it against these first.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .case import Response


@dataclass(frozen=True)
class CheckResult:
    check: str
    passed: bool
    detail: str


def _ok(check: str, detail: str = "") -> CheckResult:
    return CheckResult(check, True, detail)


def _fail(check: str, detail: str) -> CheckResult:
    return CheckResult(check, False, detail)


def contains(response: Response, value: str, case_sensitive: bool = False) -> CheckResult:
    haystack, needle = (response.text, value) if case_sensitive else (response.text.lower(), value.lower())
    return _ok("contains", value) if needle in haystack else _fail("contains", f"answer does not mention {value!r}")


def not_contains(response: Response, value: str, case_sensitive: bool = False) -> CheckResult:
    haystack, needle = (response.text, value) if case_sensitive else (response.text.lower(), value.lower())
    return _fail("not_contains", f"answer must not mention {value!r}") if needle in haystack else _ok("not_contains", value)


def regex(response: Response, pattern: str) -> CheckResult:
    return _ok("regex", pattern) if re.search(pattern, response.text, re.IGNORECASE | re.DOTALL) else _fail("regex", f"no match for /{pattern}/")


def number_close(response: Response, pattern: str, expected: float, tol: float = 0.0) -> CheckResult:
    """The first capture group of `pattern` must be a number within `tol` of `expected`."""
    match = re.search(pattern, response.text, re.IGNORECASE)
    if not match:
        return _fail("number_close", f"no match for /{pattern}/")
    try:
        found = float(match.group(1).replace(",", ""))
    except ValueError:
        return _fail("number_close", f"{match.group(1)!r} is not a number")
    if abs(found - expected) <= tol + 1e-9:  # tolerate float noise at the boundary (21.5 - 21.4 > 0.1)
        return _ok("number_close", f"{found:g}")
    return _fail("number_close", f"expected {expected:g} (±{tol:g}), got {found:g}")


def tool_called(response: Response, name: str, args: Optional[Dict[str, Any]] = None) -> CheckResult:
    for call in response.tool_calls:
        if call.name == name and all(call.args.get(k) == v for k, v in (args or {}).items()):
            return _ok("tool_called", name)
    called = ", ".join(f"{call.name}({json.dumps(call.args, sort_keys=True)})" for call in response.tool_calls) or "no tools"
    return _fail("tool_called", f"expected {name}{' with ' + json.dumps(args, sort_keys=True) if args else ''}; called {called}")


def tool_not_called(response: Response, name: str) -> CheckResult:
    return _fail("tool_not_called", f"{name} must not be called") if any(c.name == name for c in response.tool_calls) else _ok("tool_not_called", name)


def tool_order(response: Response, before: str, after: str) -> CheckResult:
    names = [call.name for call in response.tool_calls]
    if before not in names or after not in names:
        return _fail("tool_order", f"needs both {before} and {after}; called {names}")
    return _ok("tool_order", f"{before} then {after}") if names.index(before) < names.index(after) else _fail("tool_order", f"{after} came before {before}")


def max_words(response: Response, value: int) -> CheckResult:
    words = len(response.text.split())
    return _ok("max_words", f"{words} words") if words <= value else _fail("max_words", f"{words} words, limit {value}")


def json_fields(response: Response, fields: Dict[str, str]) -> CheckResult:
    """The answer must contain a JSON object whose listed fields exist with the given types."""
    match = re.search(r"\{.*\}", response.text, re.DOTALL)
    if not match:
        return _fail("json_fields", "no JSON object in the answer")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as error:
        return _fail("json_fields", f"invalid JSON ({error.msg})")
    types = {"string": str, "number": (int, float), "boolean": bool, "array": list, "object": dict}
    for name, kind in fields.items():
        if name not in data:
            return _fail("json_fields", f"missing field {name!r}")
        if kind not in types:
            raise ValueError(f"unknown field type {kind!r}")
        if isinstance(data[name], bool) and kind == "number":
            return _fail("json_fields", f"{name!r} is a boolean, expected number")
        if not isinstance(data[name], types[kind]):
            return _fail("json_fields", f"{name!r} should be {kind}")
    return _ok("json_fields", ", ".join(fields))


GRADERS: Dict[str, Callable[..., CheckResult]] = {
    "contains": contains,
    "not_contains": not_contains,
    "regex": regex,
    "number_close": number_close,
    "tool_called": tool_called,
    "tool_not_called": tool_not_called,
    "tool_order": tool_order,
    "max_words": max_words,
    "json_fields": json_fields,
}


def run_check(response: Response, spec: Dict[str, Any]) -> CheckResult:
    params = {key: value for key, value in spec.items() if key != "check"}
    name = spec.get("check")
    if name not in GRADERS:
        raise ValueError(f"unknown check {name!r}; known: {sorted(GRADERS)}")
    return GRADERS[name](response, **params)


def run_checks(response: Response, specs: List[Dict[str, Any]]) -> List[CheckResult]:
    return [run_check(response, spec) for spec in specs]
