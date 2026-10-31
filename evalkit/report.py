"""Summaries and run-to-run comparison."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List

from .runner import CaseResult


@dataclass(frozen=True)
class RunReport:
    total: int
    passed: int
    by_category: Dict[str, "tuple[int, int]"]
    failures: List[CaseResult]

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


def summarize(results: List[CaseResult]) -> RunReport:
    by_category: "OrderedDict[str, list]" = OrderedDict()
    for result in results:
        bucket = by_category.setdefault(result.case.category, [0, 0])
        bucket[0] += result.passed
        bucket[1] += 1
    return RunReport(
        total=len(results),
        passed=sum(result.passed for result in results),
        by_category={name: (passed, total) for name, (passed, total) in by_category.items()},
        failures=[result for result in results if not result.passed],
    )


def compare(before: List[CaseResult], after: List[CaseResult]) -> Dict[str, List[str]]:
    """Which cases a change fixed, which it broke, and which still fail.

    A change that raises the pass rate can still hide a regression; the regressions list is the one to read first.
    """
    was = {result.case.id: result.passed for result in before}
    now = {result.case.id: result.passed for result in after}
    ids = list(now)
    return {
        "fixed": [i for i in ids if now[i] and not was.get(i, False)],
        "regressed": [i for i in ids if not now[i] and was.get(i, False)],
        "still_failing": [i for i in ids if not now[i] and not was.get(i, True)],
    }
