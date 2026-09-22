"""Regression coverage for package imports in a fresh Python process."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_vassilflow_and_tool_loader_import_without_circular_dependencies() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            ("import vassilflow; from vassilflow.tools import get_available_tools; assert callable(get_available_tools)"),
        ],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_core_runtime_has_no_static_domain_imports() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    core_files = {
        backend_dir / "app" / "gateway" / "agent_catalog.py",
        backend_dir / "app" / "gateway" / "agent_runtime_readiness.py",
        backend_dir / "app" / "gateway" / "capability_inputs.py",
        backend_dir / "app" / "gateway" / "capability_readiness.py",
        backend_dir / "app" / "gateway" / "readiness.py",
        backend_dir / "app" / "gateway" / "services.py",
        backend_dir / "app" / "gateway" / "routers" / "thread_runs.py",
        backend_dir / "packages" / "harness" / "vassilflow" / "client.py",
        backend_dir / "packages" / "harness" / "vassilflow" / "config" / "agent_contract.py",
        backend_dir / "packages" / "harness" / "vassilflow" / "config" / "builtin_agents.py",
    }
    harness_root = backend_dir / "packages" / "harness" / "vassilflow"
    for package_name in (
        "actions",
        "agents",
        "capabilities",
        "persistence",
        "runtime",
    ):
        core_files.update((harness_root / package_name).rglob("*.py"))

    violations = {str(path.relative_to(backend_dir)): sorted(module for module in _imported_modules(path) if module.startswith("vassilflow.community.")) for path in sorted(core_files)}

    assert not {path: modules for path, modules in violations.items() if modules}
