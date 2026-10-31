"""Run cases against a source of responses and collect per-check results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Union

from .case import Case, Response
from .graders import CheckResult, run_checks

Responder = Callable[[Case], Response]


@dataclass(frozen=True)
class CaseResult:
    case: Case
    checks: List[CheckResult]
    answered: bool

    @property
    def passed(self) -> bool:
        return self.answered and all(check.passed for check in self.checks)


def run_cases(cases: Iterable[Case], source: Union[Dict[str, Response], Responder]) -> List[CaseResult]:
    """`source` is either recorded responses keyed by case id, or a callable that produces one."""
    results = []
    for case in cases:
        if callable(source):
            response = source(case)
        else:
            response = source.get(case.id)
        if response is None:
            # A missing answer is a failure, never a silent skip.
            results.append(CaseResult(case, [], answered=False))
            continue
        results.append(CaseResult(case, run_checks(response, case.checks), answered=True))
    return results
