"""Check an installed core wheel and copied domain template outside the checkout.

Run with an environment containing only vassilflow-core[test]. This script never
calls a live model. It installs the copied template into that same disposable
environment, so do not use an environment containing another domain-assistant.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run(arguments: list[str], *, cwd: Path, env: dict[str, str]) -> str:
    result = subprocess.run(
        [sys.executable, *arguments],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    if result.returncode:
        raise RuntimeError(
            f"Command failed: {arguments!r}\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--template",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "templates" / "rag-agent",
    )
    args = parser.parse_args()
    template = args.template.resolve()
    if not (template / "pyproject.toml").is_file():
        parser.error("template must contain pyproject.toml")

    # Fail if the environment accidentally contains the full application stack.
    installed = {
        distribution.metadata["Name"].lower().replace("_", "-")
        for distribution in importlib.metadata.distributions()
    }
    forbidden = {
        "vassilflow-harness",
        "fastapi",
        "kubernetes",
        "markitdown",
        "agent-sandbox",
    }
    if installed & forbidden:
        raise RuntimeError(
            f"Use a core-only environment; found {sorted(installed & forbidden)}"
        )
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["LANGSMITH_TRACING"] = "false"
    environment["PYTHONUTF8"] = "1"

    with tempfile.TemporaryDirectory(prefix="vassilflow-domain-") as directory:
        root = Path(directory)
        project = root / "domain-project"
        empty = root / "empty"
        empty.mkdir()
        shutil.copytree(
            template,
            project,
            ignore=shutil.ignore_patterns(
                ".venv",
                "__pycache__",
                ".pytest_cache",
                ".ruff_cache",
                ".data",
                "*.egg-info",
            ),
        )
        run(
            ["-m", "pip", "install", "--no-deps", str(project)],
            cwd=empty,
            env=environment,
        )
        smoke = run(["-m", "domain_assistant.cli", "demo"], cwd=empty, env=environment)
        payload = json.loads(smoke)
        if not payload["rag"]["sources"] or not payload["agent"]["sources"]:
            raise RuntimeError(
                "Demo did not return RAG evidence and delegated-agent output"
            )
        tests = run(
            [
                "-m",
                "pytest",
                str(project / "tests"),
                "--confcutdir",
                str(project),
                "-q",
            ],
            cwd=empty,
            env=environment,
        )
        print(smoke)
        print(tests)
        print("Installed core and copied domain template passed outside the checkout.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
