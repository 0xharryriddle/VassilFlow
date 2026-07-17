"""Regression tests for config-upgrade schema merging."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from shutil import which

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_UPGRADE_SCRIPT = REPO_ROOT / "scripts" / "config-upgrade.sh"
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


@pytest.mark.skipif(BASH_EXECUTABLE is None, reason="bash is required for config-upgrade tests")
def test_config_upgrade_preserves_vassilflow_runtime_defaults(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "config_version: '16'",
                "database:",
                "  backend: sqlite",
                "  sqlite_dir: .vassilflow/data",
                "channel_connections:",
                "  wechat:",
                "    state_dir: ./.vassilflow/wechat/state",
                "memory:",
                "  storage_path: .vassilflow/memory.json",
                "checkpointer:",
                "  type: sqlite",
                "  connection_string: ./.vassilflow/checkpoints.db",
                "",
            ]
        ),
        encoding="utf-8",
    )

    env = {**os.environ, "VASSILFLOW_CONFIG_PATH": _bash_path(config_path)}
    result = subprocess.run(
        [BASH_EXECUTABLE, str(CONFIG_UPGRADE_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    upgraded = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert "version 16 -> 20" in result.stdout
    assert "Applied" not in result.stdout
    assert (tmp_path / "config.yaml.bak").exists()
    assert upgraded["config_version"] == 20
    assert upgraded["database"]["sqlite_dir"] == ".vassilflow/data"
    assert upgraded["channel_connections"]["wechat"]["state_dir"] == "./.vassilflow/wechat/state"
    assert upgraded["memory"]["storage_path"] == ".vassilflow/memory.json"
    assert upgraded["checkpointer"]["connection_string"] == "./.vassilflow/checkpoints.db"
    assert upgraded["tool_progress"]["enabled"] is False
    upgraded_tool_names = {tool["name"] for tool in upgraded["tools"]}
    assert {
        "office_inspect",
        "office_generate",
        "office_edit",
        "office_render",
    }.issubset(upgraded_tool_names)


@pytest.mark.skipif(BASH_EXECUTABLE is None, reason="bash is required for config-upgrade tests")
def test_config_upgrade_adds_office_tools_without_expanding_existing_file_permissions(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """config_version: 18
tools:
  - name: read_file
    group: file:read
    use: vassilflow.sandbox.tools:read_file_tool
  - name: custom_search
    group: web
    use: example.tools:search
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [BASH_EXECUTABLE, str(CONFIG_UPGRADE_SCRIPT)],
        cwd=REPO_ROOT,
        env={**os.environ, "VASSILFLOW_CONFIG_PATH": _bash_path(config_path)},
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    upgraded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    tools = {tool["name"]: tool for tool in upgraded["tools"]}

    assert "tools: added office_inspect" in result.stdout
    assert tools["custom_search"]["use"] == "example.tools:search"
    assert tools["office_inspect"]["group"] == "file:read"
    assert "office_edit" not in tools
    assert "office_generate" not in tools
    assert "office_render" not in tools


@pytest.mark.skipif(BASH_EXECUTABLE is None, reason="bash is required for config-upgrade tests")
def test_config_upgrade_adds_generate_edit_and_render_with_existing_write_permission(
    tmp_path: Path,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """config_version: 18
tools:
  - name: write_file
    group: file:write
    use: vassilflow.sandbox.tools:write_file_tool
""",
        encoding="utf-8",
    )

    subprocess.run(
        [BASH_EXECUTABLE, str(CONFIG_UPGRADE_SCRIPT)],
        cwd=REPO_ROOT,
        env={**os.environ, "VASSILFLOW_CONFIG_PATH": _bash_path(config_path)},
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    upgraded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    tools = {tool["name"]: tool for tool in upgraded["tools"]}

    assert tools["office_edit"]["group"] == "file:write"
    assert tools["office_generate"]["group"] == "file:write"
    assert tools["office_render"]["group"] == "file:write"


@pytest.mark.skipif(BASH_EXECUTABLE is None, reason="bash is required for config-upgrade tests")
def test_config_upgrade_preserves_intentionally_empty_tool_list(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("config_version: 18\ntools: []\n", encoding="utf-8")

    subprocess.run(
        [BASH_EXECUTABLE, str(CONFIG_UPGRADE_SCRIPT)],
        cwd=REPO_ROOT,
        env={**os.environ, "VASSILFLOW_CONFIG_PATH": _bash_path(config_path)},
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    upgraded = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert upgraded["tools"] == []
