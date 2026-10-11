"""Prove the reusable package has no application or adapter import dependency."""

from __future__ import annotations

import ast
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path

import vassilflow_core


def test_core_never_imports_application_or_optional_adapters():
    package = Path(vassilflow_core.__file__).parent
    forbidden = {
        "vassilflow",
        "app",
        "fastapi",
        "kubernetes",
        "markitdown",
        "langchain_openai",
        "langchain_anthropic",
        "langchain_mcp_adapters",
        "agent_sandbox",
        "sqlalchemy",
    }
    violations = []
    for path in package.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            violations.extend((str(path), name) for name in names if name.split(".")[0] in forbidden)
    assert not violations


def test_installed_distribution_has_only_core_runtime_requirements():
    requirements = importlib.metadata.requires("vassilflow-core")
    mandatory = [requirement for requirement in requirements if "extra ==" not in requirement]
    names = {requirement.split("<")[0].split(">")[0].split(";")[0].strip() for requirement in mandatory}
    assert names == {"langchain", "langchain-core", "langgraph", "pydantic"}
    assert Path(vassilflow_core.__file__).with_name("py.typed").is_file()


def test_import_from_empty_directory_has_no_application_side_effects(tmp_path):
    # CI runs this with only the built core wheel installed; no checkout imports.
    source = """
import json, pathlib, sys, threading
before = {thread.ident for thread in threading.enumerate()}
import vassilflow_core
for name in vassilflow_core.__all__:
    getattr(vassilflow_core, name)
forbidden = ('vassilflow', 'app', 'fastapi', 'kubernetes', 'markitdown',
             'langchain_openai', 'langchain_anthropic', 'agent_sandbox')
assert not any(name.split('.')[0] in forbidden for name in sys.modules)
assert not list(pathlib.Path.cwd().iterdir())
assert {thread.ident for thread in threading.enumerate()} == before
print(json.dumps({'version': vassilflow_core.__version__}))
"""
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["LANGSMITH_TRACING"] = "false"
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["version"] == "0.1.1"
