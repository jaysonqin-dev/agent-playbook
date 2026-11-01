"""Data model: an evaluation case, and what an agent answered."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Response:
    """What the agent produced for one case: the visible answer and the tools it called, in order."""

    case_id: str
    text: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)  # present on live runs: model, timestamp, steps, ...


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    prompt: str
    checks: List[Dict[str, Any]]


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{number}: not valid JSON ({error.msg})") from error
    return rows


def load_cases(path: Path) -> List[Case]:
    cases = []
    seen = set()
    for row in _read_jsonl(path):
        missing = {"id", "category", "prompt", "checks"} - row.keys()
        if missing:
            raise ValueError(f"case {row.get('id', '?')}: missing {sorted(missing)}")
        if row["id"] in seen:
            raise ValueError(f"duplicate case id {row['id']}")
        if not row["checks"]:
            raise ValueError(f"case {row['id']}: a case needs at least one check")
        seen.add(row["id"])
        cases.append(Case(row["id"], row["category"], row["prompt"], row["checks"]))
    return cases


def load_responses(path: Path) -> Dict[str, Response]:
    responses = {}
    for row in _read_jsonl(path):
        calls = [ToolCall(call["name"], call.get("args", {})) for call in row.get("tool_calls", [])]
        responses[row["id"]] = Response(row["id"], row.get("text", ""), calls, row.get("meta") or {})
    return responses
