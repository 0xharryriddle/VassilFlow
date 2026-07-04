"""Regression tests for the runtime home migration helper."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from shutil import which

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_SCRIPT = REPO_ROOT / "scripts" / "migrate-runtime-home.sh"
BASH_CANDIDATES = [
    Path(r"C:\Program Files\Git\bin\bash.exe"),
    Path(which("bash")) if which("bash") else None,
]
BASH_EXECUTABLE = next(
    (str(path) for path in BASH_CANDIDATES if path is not None and path.exists() and "WindowsApps" not in str(path)),
    None,
)


def _bash_path(path: Path) -> str:
    if BASH_EXECUTABLE is None:
        raise RuntimeError("bash is required")

    return subprocess.check_output(
        [BASH_EXECUTABLE, "-lc", 'cygpath -u "$PATH_TO_CONVERT" 2>/dev/null || printf "%s" "$PATH_TO_CONVERT"'],
        env={**os.environ, "PATH_TO_CONVERT": str(path)},
        text=True,
        encoding="utf-8",
    ).strip()


def _run_migration(source: Path, target: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    if BASH_EXECUTABLE is None:
        raise RuntimeError("bash is required")

    return subprocess.run(
        [
            BASH_EXECUTABLE,
            str(MIGRATION_SCRIPT),
            "--source",
            _bash_path(source),
            "--target",
            _bash_path(target),
            *extra_args,
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )


def _run_migration_with_env(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    if BASH_EXECUTABLE is None:
        raise RuntimeError("bash is required")

    return subprocess.run(
        [BASH_EXECUTABLE, str(MIGRATION_SCRIPT)],
        cwd=REPO_ROOT,
        env={**os.environ, **env},
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )


@pytest.mark.skipif(BASH_EXECUTABLE is None, reason="bash is required for runtime migration tests")
def test_runtime_home_migration_copies_legacy_data_without_removing_source(tmp_path: Path):
    script_content = MIGRATION_SCRIPT.read_text(encoding="utf-8")
    assert "Copy legacy runtime state" in script_content
    assert "Copy legacy DeerFlow runtime state" not in script_content

    source = tmp_path / ".deer-flow"
    target = tmp_path / ".vassilflow"
    (source / "data").mkdir(parents=True)
    (source / "data" / "vassilflow.db").write_text("sqlite-placeholder", encoding="utf-8")
    (source / "threads" / "t1").mkdir(parents=True)
    (source / "threads" / "t1" / "note.txt").write_text("hello", encoding="utf-8")

    result = _run_migration(source, target)

    assert "Copied legacy runtime home" in result.stdout
    assert (source / "data" / "vassilflow.db").read_text(encoding="utf-8") == "sqlite-placeholder"
    assert (target / "data" / "vassilflow.db").read_text(encoding="utf-8") == "sqlite-placeholder"
    assert (target / "threads" / "t1" / "note.txt").read_text(encoding="utf-8") == "hello"


@pytest.mark.skipif(BASH_EXECUTABLE is None, reason="bash is required for runtime migration tests")
def test_runtime_home_migration_skips_existing_nonempty_target(tmp_path: Path):
    source = tmp_path / ".deer-flow"
    target = tmp_path / ".vassilflow"
    source.mkdir()
    target.mkdir()
    (source / "memory.json").write_text('{"legacy": true}', encoding="utf-8")
    (target / "memory.json").write_text('{"current": true}', encoding="utf-8")

    result = _run_migration(source, target)

    assert "already has data" in result.stdout
    assert (target / "memory.json").read_text(encoding="utf-8") == '{"current": true}'


@pytest.mark.skipif(BASH_EXECUTABLE is None, reason="bash is required for runtime migration tests")
def test_runtime_home_migration_dry_run_does_not_copy(tmp_path: Path):
    source = tmp_path / ".deer-flow"
    target = tmp_path / ".vassilflow"
    source.mkdir()
    (source / "memory.json").write_text("{}", encoding="utf-8")

    result = _run_migration(source, target, "--dry-run")

    assert "Would copy legacy runtime home" in result.stdout
    assert not target.exists()


@pytest.mark.skipif(BASH_EXECUTABLE is None, reason="bash is required for runtime migration tests")
def test_runtime_home_migration_uses_env_defaults(tmp_path: Path):
    source = tmp_path / "custom-legacy"
    target = tmp_path / "custom-current"
    source.mkdir()
    (source / "memory.json").write_text('{"legacy": true}', encoding="utf-8")

    result = _run_migration_with_env(
        {
            "VASSILFLOW_MIGRATION_SOURCE": _bash_path(source),
            "VASSILFLOW_HOME": _bash_path(target),
        }
    )

    assert "Copied legacy runtime home" in result.stdout
    assert (target / "memory.json").read_text(encoding="utf-8") == '{"legacy": true}'
