"""Command line: run a case file against recorded responses, compare two runs, gate on a pass rate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from .case import load_cases, load_responses
from .report import compare, summarize
from .runner import run_cases


def _print_report(label: str, report) -> None:
    print(f"{label}: {report.passed}/{report.total} passed ({report.pass_rate:.0%})")
    for category, (passed, total) in report.by_category.items():
        print(f"  {category:<20} {passed}/{total}")
    for result in report.failures:
        reasons = "; ".join(check.detail for check in result.checks if not check.passed) or "no answer recorded"
        print(f"  FAIL {result.case.id}: {reasons}")


def _run(args) -> int:
    cases = load_cases(Path(args.cases))
    results = run_cases(cases, load_responses(Path(args.responses)))
    report = summarize(results)
    if args.json:
        print(
            json.dumps(
                {
                    "total": report.total,
                    "passed": report.passed,
                    "by_category": {k: {"passed": p, "total": t} for k, (p, t) in report.by_category.items()},
                    "cases": [
                        {
                            "id": r.case.id,
                            "category": r.case.category,
                            "prompt": r.case.prompt,
                            "passed": r.passed,
                            "checks": [{"check": c.check, "passed": c.passed, "detail": c.detail} for c in r.checks],
                        }
                        for r in results
                    ],
                },
                indent=2,
            )
        )
    else:
        _print_report(Path(args.responses).stem, report)
    if args.gate is not None and report.pass_rate < args.gate:
        print(f"GATE FAILED: pass rate {report.pass_rate:.0%} is below {args.gate:.0%}", file=sys.stderr)
        return 1
    return 0


def _diff(args) -> int:
    cases = load_cases(Path(args.cases))
    before = run_cases(cases, load_responses(Path(args.before)))
    after = run_cases(cases, load_responses(Path(args.after)))
    delta = compare(before, after)
    print(f"{Path(args.before).stem} -> {Path(args.after).stem}")
    print(f"  pass rate {summarize(before).pass_rate:.0%} -> {summarize(after).pass_rate:.0%}")
    for key in ("regressed", "fixed", "still_failing"):
        print(f"  {key}: {', '.join(delta[key]) or '-'}")
    return 1 if delta["regressed"] and args.fail_on_regression else 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="evalkit", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="grade recorded responses")
    run.add_argument("--cases", required=True)
    run.add_argument("--responses", required=True)
    run.add_argument("--gate", type=float, help="fail (exit 1) when the pass rate is below this, e.g. 0.9")
    run.add_argument("--json", action="store_true", help="print machine-readable results")
    run.set_defaults(func=_run)

    diff = sub.add_parser("diff", help="compare two runs on the same cases")
    diff.add_argument("--cases", required=True)
    diff.add_argument("--before", required=True)
    diff.add_argument("--after", required=True)
    diff.add_argument("--fail-on-regression", action="store_true")
    diff.set_defaults(func=_diff)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
