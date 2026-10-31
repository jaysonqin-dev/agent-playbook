"""Log events and weekly metrics.

One event is one user request handled by the agent. The fields are the minimum that answers
"is the agent getting better or worse, and what changed when it did":
  ts, session, category, tools (list), tool_errors, corrected (the user had to correct the answer),
  turns (messages until the user was done), latency_ms, rules_version (which instruction version answered).
"""

from __future__ import annotations

import json
import math
import statistics
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Event:
    ts: datetime
    session: str
    category: str
    tools: List[str]
    tool_errors: int
    corrected: bool
    turns: int
    latency_ms: int
    rules_version: str


def parse_events(path: Path) -> List[Event]:
    events = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            events.append(
                Event(
                    ts=datetime.fromisoformat(row["ts"].replace("Z", "+00:00")),
                    session=row["session"],
                    category=row["category"],
                    tools=list(row.get("tools", [])),
                    tool_errors=int(row.get("tool_errors", 0)),
                    corrected=bool(row["corrected"]),
                    turns=int(row["turns"]),
                    latency_ms=int(row["latency_ms"]),
                    rules_version=row["rules_version"],
                )
            )
        except (KeyError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"{path}:{number}: bad event ({error})") from error
    return events


@dataclass(frozen=True)
class WeekMetrics:
    week: str
    events: int
    correction_rate: float
    tool_error_rate: float
    median_turns: float
    p95_latency_ms: int
    rules_versions: List[str]


def _percentile(values: List[int], pct: float) -> int:
    ordered = sorted(values)
    index = max(0, math.ceil(pct / 100 * len(ordered)) - 1)
    return ordered[index]


def weekly_metrics(events: List[Event]) -> List[WeekMetrics]:
    by_week: "OrderedDict[str, List[Event]]" = OrderedDict()
    for event in sorted(events, key=lambda e: e.ts):
        year, week, _ = event.ts.isocalendar()
        by_week.setdefault(f"{year}-W{week:02d}", []).append(event)
    metrics = []
    for week, items in by_week.items():
        metrics.append(
            WeekMetrics(
                week=week,
                events=len(items),
                correction_rate=sum(e.corrected for e in items) / len(items),
                tool_error_rate=sum(e.tool_errors > 0 for e in items) / len(items),
                median_turns=statistics.median(e.turns for e in items),
                p95_latency_ms=_percentile([e.latency_ms for e in items], 95),
                rules_versions=sorted({e.rules_version for e in items}),
            )
        )
    return metrics


@dataclass(frozen=True)
class Alert:
    week: str
    metric: str
    value: float
    baseline: float
    versions: List[str]

    def describe(self) -> str:
        return (
            f"{self.week}: {self.metric} {self.value:.0%} vs {self.baseline:.0%} before "
            f"(instructions {', '.join(self.versions)})"
        )


def alerts(
    metrics: List[WeekMetrics],
    *,
    window: int = 3,
    min_events: int = 20,
    rise: float = 0.05,
    ratio: float = 1.5,
) -> List[Alert]:
    """Flag a week whose rate is clearly above the mean of the previous `window` weeks.

    "Clearly" means both an absolute rise and a relative one, so a move from 1% to 2% is not an alert
    and neither is noise in a week with very few events.
    """
    found: List[Alert] = []
    for index, current in enumerate(metrics):
        before = [m for m in metrics[max(0, index - window) : index] if m.events >= min_events]
        if not before or current.events < min_events:
            continue
        for name in ("correction_rate", "tool_error_rate"):
            baseline = statistics.mean(getattr(m, name) for m in before)
            value = getattr(current, name)
            if value - baseline >= rise and value >= baseline * ratio:
                found.append(Alert(current.week, name.replace("_", " "), value, baseline, current.rules_versions))
    return found
