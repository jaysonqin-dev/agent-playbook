"""Writes monitoring/sample_logs.jsonl: SYNTHETIC interaction logs for the demo report.

Six weeks, about 45 events a week. Weeks 1-3 are steady. Instructions v14 go live in week 4 and make
the agent over-eager with tools (more tool errors and corrections); v15 fixes it in week 5. This is
made-up data to show what the report and alert look like. It says nothing about any real agent.

    python3 monitoring/make_sample_logs.py --seed 2 > monitoring/sample_logs.jsonl
"""

import argparse
import json
import random
from datetime import datetime, timedelta, timezone

CATEGORIES = ["metric_question", "status_check", "draft_message", "export", "out_of_scope"]
# (weeks 1-based) -> (rules_version, correction rate, tool error rate)
PLAN = {1: ("v12", 0.14, 0.04), 2: ("v12", 0.12, 0.04), 3: ("v13", 0.11, 0.03), 4: ("v14", 0.24, 0.16), 5: ("v15", 0.10, 0.04), 6: ("v15", 0.09, 0.03)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=2)
    rng = random.Random(parser.parse_args().seed)
    start = datetime(2026, 3, 2, 8, 0, tzinfo=timezone.utc)  # a Monday
    session = 0
    for week, (version, correction, tool_error) in PLAN.items():
        for _ in range(rng.randint(42, 48)):
            session += 1
            when = start + timedelta(weeks=week - 1, days=rng.randint(0, 4), hours=rng.randint(0, 9), minutes=rng.randint(0, 59))
            category = rng.choice(CATEGORIES)
            tools = [] if category == "out_of_scope" else ["inventory_query"] + (["export_report"] if category == "export" else [])
            event = {
                "ts": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "session": f"s{session:04d}",
                "category": category,
                "tools": tools,
                "tool_errors": 1 if tools and rng.random() < tool_error * 1.2 else 0,
                "corrected": rng.random() < correction,
                "turns": rng.choice([1, 1, 2, 2, 3, 4]),
                "latency_ms": int(rng.lognormvariate(8.0, 0.35)),
                "rules_version": version,
            }
            print(json.dumps(event))


if __name__ == "__main__":
    main()
