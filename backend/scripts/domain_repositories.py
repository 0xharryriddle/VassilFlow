"""Inventory and explicitly migrate domain-owned repositories."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Any

from vassilflow.persistence.project_repository import (
    ProjectRepositoryError,
    ProjectRepositoryRegistry,
)
from vassilflow.persistence.repository_registry import (
    build_domain_repository_registry,
)

_REPORT_SCHEMA = "vassilflow.repository.operations.v1"


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _registry(user_id: str | None) -> ProjectRepositoryRegistry:
    return build_domain_repository_registry(user_id=user_id)


def _base_report(
    *,
    command: str,
    registry: ProjectRepositoryRegistry,
) -> dict[str, Any]:
    return {
        "schema": _REPORT_SCHEMA,
        "generated_at": _timestamp(),
        "command": command,
        "repositories": [repository.descriptor.model_dump(mode="json") for repository in registry.repositories],
    }


def _inventory(
    registry: ProjectRepositoryRegistry,
) -> tuple[dict[str, Any], int]:
    inventories = registry.inventory()
    report = _base_report(command="inventory", registry=registry)
    report["inventories"] = [inventory.model_dump(mode="json", by_alias=True) for inventory in inventories]
    return report, (2 if any(inventory.status == "blocked" for inventory in inventories) else 0)


def _migrate(
    registry: ProjectRepositoryRegistry,
    *,
    apply: bool,
) -> tuple[dict[str, Any], int]:
    inventories = registry.inventory()
    plans = registry.migration_plan(inventories)
    report = _base_report(
        command="migrate_apply" if apply else "migrate_plan",
        registry=registry,
    )
    report["inventories"] = [inventory.model_dump(mode="json", by_alias=True) for inventory in inventories]
    report["plans"] = [plan.model_dump(mode="json") for plan in plans]

    blocked = any(inventory.status == "blocked" for inventory in inventories)
    if apply and not blocked:
        report["results"] = [result.model_dump(mode="json") for result in registry.apply_migrations(plans)]
        post_inventories = registry.inventory()
        report["post_inventories"] = [inventory.model_dump(mode="json", by_alias=True) for inventory in post_inventories]
        unresolved = any(inventory.status != "current" for inventory in post_inventories)
    else:
        report["results"] = []
        unresolved = False
    return report, 2 if blocked or unresolved else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=("Inspect project repository schemas and apply only migrations registered by their owning domains."))
    parser.add_argument(
        "--user-id",
        help=("Limit the operation to one user scope. The identifier is never included in command output."),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "inventory",
        help="Read schema inventory without changing repository data.",
    )
    migrate = subparsers.add_parser(
        "migrate",
        help="Plan repository migrations; no data changes by default.",
    )
    migrate.add_argument(
        "--apply",
        action="store_true",
        help="Apply the exact migration plan returned by each repository.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        registry = _registry(args.user_id)
        if args.command == "inventory":
            report, exit_code = _inventory(registry)
        else:
            report, exit_code = _migrate(
                registry,
                apply=args.apply,
            )
    except (ProjectRepositoryError, ValueError):
        report = {
            "schema": _REPORT_SCHEMA,
            "generated_at": _timestamp(),
            "command": args.command,
            "error": "Repository operation failed validation.",
        }
        exit_code = 2
    except Exception:
        report = {
            "schema": _REPORT_SCHEMA,
            "generated_at": _timestamp(),
            "command": args.command,
            "error": "Repository operation failed.",
        }
        exit_code = 2

    print(json.dumps(report, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
