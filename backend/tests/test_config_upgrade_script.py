"""Regression tests for config-upgrade migrations."""

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
@pytest.mark.parametrize("config_env_var", ["VASSILFLOW_CONFIG_PATH", "DEER_FLOW_CONFIG_PATH"])
def test_config_upgrade_migrates_legacy_runtime_defaults(tmp_path: Path, config_env_var: str):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "config_version: '16'",
                "database:",
                "  backend: sqlite",
                "  sqlite_dir: .deer-flow/data",
                "channel_connections:",
                "  wechat:",
                "    state_dir: ./.deer-flow/wechat/state",
                "memory:",
                "  storage_path: .deer-flow/memory.json",
                "checkpointer:",
                "  type: sqlite",
                "  connection_string: ./.deer-flow/checkpoints.db",
                "",
            ]
        ),
        encoding="utf-8",
    )

    env = {**os.environ, config_env_var: _bash_path(config_path)}
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

    assert "version 16 -> 17" in result.stdout
    assert "database.sqlite_dir: .deer-flow/data -> .vassilflow/data" in result.stdout
    assert (tmp_path / "config.yaml.bak").exists()
    assert upgraded["config_version"] == 17
    assert upgraded["database"]["sqlite_dir"] == ".vassilflow/data"
    assert upgraded["channel_connections"]["wechat"]["state_dir"] == "./.vassilflow/wechat/state"
    assert upgraded["memory"]["storage_path"] == ".vassilflow/memory.json"
    assert upgraded["checkpointer"]["connection_string"] == "./.vassilflow/checkpoints.db"
