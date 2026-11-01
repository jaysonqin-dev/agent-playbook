"""Command line: grade recorded responses, compare two runs, gate on a pass rate, or record a live model run."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from .case import load_cases, load_responses
from .live import DEFAULT_BASE_URL, DEFAULT_KEY_ENV, LiveError, run_live
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


def _live(args) -> int:
    api_key = os.environ.get(args.api_key_env, "")
    if not api_key:
        print(
            f"error: environment variable {args.api_key_env} is not set. "
            f"Export your API key first (export {args.api_key_env}=...). "
            "The key is read from the environment only.",
            file=sys.stderr,
        )
        return 2
    cases = load_cases(Path(args.cases))
    if args.only:
        wanted = [item.strip() for item in args.only.split(",") if item.strip()]
        unknown = sorted(set(wanted) - {case.id for case in cases})
        if unknown:
            print(f"error: --only names unknown case ids: {', '.join(unknown)}", file=sys.stderr)
            return 2
        cases = [case for case in cases if case.id in wanted]
    instructions = Path(args.instructions).read_text(encoding="utf-8")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out.open("w", encoding="utf-8") as handle:

        def save(row) -> None:
            nonlocal written
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            written += 1
            meta = row["meta"]
            flag = " (truncated)" if meta["truncated"] else ""
            print(f"{row['id']}: {meta['steps']} model call(s), {len(row['tool_calls'])} tool call(s){flag}")

        try:
            run_live(
                cases,
                instructions=instructions,
                model=args.model,
                base_url=args.base_url,
                api_key=api_key,
                max_steps=args.max_steps,
                temperature=args.temperature,
                timeout=args.timeout,
                on_row=save,
            )
        except LiveError as error:
            print(f"error: {error} ({written}/{len(cases)} cases saved to {out})", file=sys.stderr)
            return 1
    print(f"wrote {written} transcript(s) to {out}")
    print(f"grade it: python3 -m evalkit run --cases {args.cases} --responses {out}")
    return 0


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

    live = sub.add_parser("live", help="run the cases against a real model and record a transcript file")
    live.add_argument("--cases", required=True)
    live.add_argument("--instructions", required=True, help="file with the system prompt")
    live.add_argument("--out", required=True, help="transcript file to write (.jsonl)")
    live.add_argument("--model", required=True)
    live.add_argument("--base-url", default=DEFAULT_BASE_URL, help="OpenAI-compatible endpoint; /chat/completions is appended")
    live.add_argument("--api-key-env", default=DEFAULT_KEY_ENV, help="environment variable that holds the API key")
    live.add_argument("--max-steps", type=int, default=6, help="model calls allowed per case")
    live.add_argument("--temperature", type=float, default=0.0)
    live.add_argument("--only", help="comma-separated case ids to run, e.g. md1,nm4")
    live.add_argument("--timeout", type=float, default=60.0, help="seconds per request")
    live.set_defaults(func=_live)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
