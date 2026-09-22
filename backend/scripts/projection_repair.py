"""Inspect and explicitly repair durable domain projections."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from app.gateway.domain_repair import (  # noqa: E402
    aggregate_repair_inspection,
    aggregate_repair_results,
    discover_repair_user_ids,
    inspect_user_repairs,
    repair_user_projections,
)

_REPORT_SCHEMA = "vassilflow.projection_repair.operations.v1"


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=("Inspect lifecycle projections and reconcile only Actions backed by canonical domain evidence."))
    parser.add_argument(
        "--user-id",
        help=("Limit the operation to one user scope. The identifier is never included in command output."),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        choices=range(1, 501),
        metavar="1..500",
        help="Maximum unresolved records inspected per user and repair kind.",
    )
    parser.add_argument(
        "--stale-after-seconds",
        type=int,
        default=300,
        choices=range(60, 86_401),
        metavar="60..86400",
        help="Minimum age before a running Action can be reconciled.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "inspect",
        help="Read aggregate repair state without changing data.",
    )
    repair = subparsers.add_parser(
        "repair",
        help="Plan repair by default; apply only with --apply.",
    )
    repair.add_argument(
        "--apply",
        action="store_true",
        help="Replay handlers and append evidence-backed Action outcomes.",
    )
    return parser


def _base_report(command: str) -> dict[str, Any]:
    return {
        "schema": _REPORT_SCHEMA,
        "generated_at": _timestamp(),
        "command": command,
    }


def _inspect(
    user_ids: tuple[str, ...],
    *,
    stale_after: timedelta,
    limit: int,
) -> dict[str, Any]:
    inspections = tuple(
        inspect_user_repairs(
            user_id,
            stale_after=stale_after,
            limit=limit,
        )
        for user_id in user_ids
    )
    report = _base_report("inspect")
    report["summary"] = aggregate_repair_inspection(inspections)
    return report


async def _apply(
    user_ids: tuple[str, ...],
    *,
    stale_after: timedelta,
    limit: int,
) -> dict[str, Any]:
    results = []
    for user_id in user_ids:
        results.append(
            await repair_user_projections(
                user_id,
                stale_after=stale_after,
                limit=limit,
            )
        )
    report = _base_report("repair_apply")
    report["summary"] = aggregate_repair_results(tuple(results))
    return report


def main() -> int:
    args = _parser().parse_args()
    try:
        user_ids = discover_repair_user_ids(user_id=args.user_id)
        stale_after = timedelta(seconds=args.stale_after_seconds)
        if args.command == "inspect" or not args.apply:
            report = _inspect(
                user_ids,
                stale_after=stale_after,
                limit=args.limit,
            )
            if args.command == "repair":
                report["command"] = "repair_plan"
            exit_code = 0
        else:
            report = asyncio.run(
                _apply(
                    user_ids,
                    stale_after=stale_after,
                    limit=args.limit,
                )
            )
            summary = report["summary"]
            exit_code = 2 if (summary["failed"] or summary["lifecycle_pending"] or summary["actions_indeterminate"] or summary["limit_reached"]) else 0
    except (RuntimeError, ValueError):
        report = _base_report(args.command)
        report["error"] = "Projection repair failed validation."
        exit_code = 2
    except Exception:
        report = _base_report(args.command)
        report["error"] = "Projection repair failed."
        exit_code = 2

    print(json.dumps(report, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
