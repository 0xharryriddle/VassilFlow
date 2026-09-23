#!/usr/bin/env python3
"""Count tracked first-party core backend LOC with a stable, explicit scope.

Production scope: backend/app, backend/packages/harness/vassilflow, and
docker/provisioner Python/Go source present in the current worktree (tracked and
non-ignored untracked files). Tests are counted separately. Blank lines and
full-line Python/Go comments are excluded; inline comments and docstrings remain
counted. Generated/vendor/dependency/docs files are out of scope.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOTS = (
    "backend/app/",
    "backend/packages/harness/vassilflow/",
    "docker/provisioner/",
)
SOURCE_SUFFIXES = {".py", ".go"}
TEST_ROOT = "backend/tests/"


def source_paths(ref: str | None = None) -> list[str]:
    command = (
        ["git", "ls-tree", "-r", "--name-only", "-z", ref]
        if ref
        else ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    )
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def is_production_source(path: str) -> bool:
    candidate = Path(path)
    return (
        path.startswith(ROOTS)
        and candidate.suffix in SOURCE_SUFFIXES
        and "/tests/" not in path
        and not {"generated", "vendor", "__pycache__"}.intersection(candidate.parts)
        and not candidate.name.startswith("test_")
    )


def is_test_source(path: str) -> bool:
    candidate = Path(path)
    return path.startswith(TEST_ROOT) and candidate.suffix == ".py"


def counts_for(path: str, root: Path, ref: str | None = None) -> tuple[int, int]:
    if ref:
        result = subprocess.run(
            ["git", "show", f"{ref}:{path}"],
            check=True,
            capture_output=True,
            cwd=root,
        )
        text = result.stdout.decode("utf-8", errors="replace")
    else:
        text = (root / path).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    physical = len(lines)
    countable = sum(
        1
        for line in lines
        if line.strip() and not line.lstrip().startswith(("#", "//"))
    )
    return countable, physical


def summarize(paths: list[str], root: Path, ref: str | None = None) -> dict[str, object]:
    files = [
        path
        for path in paths
        if is_production_source(path) and (ref is not None or (root / path).is_file())
    ]
    tests = [
        path
        for path in paths
        if is_test_source(path) and (ref is not None or (root / path).is_file())
    ]
    prod_counts = {path: counts_for(path, root, ref) for path in files}
    test_counts = {path: counts_for(path, root, ref) for path in tests}
    groups = {
        "gateway_app": "backend/app/",
        "harness": "backend/packages/harness/vassilflow/",
        "provisioner": "docker/provisioner/",
    }
    return {
        "scope": {
            "production_roots": list(ROOTS),
            "production_suffixes": sorted(SOURCE_SUFFIXES),
            "tests_root": TEST_ROOT,
            "count_rule": "tracked source; exclude blank lines and full-line # or // comments; retain inline comments and docstrings",
            "exclude": ["generated code", "vendored code", "dependencies", "documentation"],
        },
        "production": {
            "files": len(files),
            "counted_lines": sum(value[0] for value in prod_counts.values()),
            "physical_lines": sum(value[1] for value in prod_counts.values()),
            "groups": {
                name: {
                    "files": sum(path.startswith(prefix) for path in files),
                    "counted_lines": sum(
                        prod_counts[path][0] for path in files if path.startswith(prefix)
                    ),
                }
                for name, prefix in groups.items()
            },
        },
        "tests": {
            "files": len(tests),
            "counted_lines": sum(value[0] for value in test_counts.values()),
            "physical_lines": sum(value[1] for value in test_counts.values()),
        },
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ref",
        help="count files from a Git ref instead of the current working tree",
    )
    args = parser.parse_args()
    try:
        report = summarize(source_paths(args.ref), root, args.ref)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"core LOC inventory failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
