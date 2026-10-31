"""Command line: print weekly health metrics and alerts for an interaction log."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Optional

from .metrics import alerts, parse_events, weekly_metrics


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="monitor", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    report = sub.add_parser("report", help="weekly metrics and alerts")
    report.add_argument("--logs", required=True)
    report.add_argument("--fail-on-alert", action="store_true")
    args = parser.parse_args(argv)

    metrics = weekly_metrics(parse_events(Path(args.logs)))
    print(f"{'week':<10}{'events':>7}{'corrected':>11}{'tool errors':>13}{'median turns':>14}{'p95 ms':>9}  instructions")
    for m in metrics:
        print(
            f"{m.week:<10}{m.events:>7}{m.correction_rate:>11.0%}{m.tool_error_rate:>13.0%}"
            f"{m.median_turns:>14g}{m.p95_latency_ms:>9}  {', '.join(m.rules_versions)}"
        )
    found = alerts(metrics)
    print()
    print("Alerts:" if found else "No alerts.")
    for alert in found:
        print(f"  {alert.describe()}")
    return 1 if found and args.fail_on_alert else 0


if __name__ == "__main__":
    raise SystemExit(main())
