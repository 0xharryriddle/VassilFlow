"""Operator-surface tests for durable projection repair."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_projection_repair_cli_is_read_only_and_identity_free(
    tmp_path: Path,
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    user_id = "private-user"
    env = {
        **os.environ,
        "VASSILFLOW_HOME": str(tmp_path / "runtime"),
    }

    result = subprocess.run(
        [
            sys.executable,
            "scripts/projection_repair.py",
            "--user-id",
            user_id,
            "inspect",
        ],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert user_id not in result.stdout
    assert user_id not in result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema"] == ("vassilflow.projection_repair.operations.v1")
    assert payload["command"] == "inspect"
    assert payload["summary"] == {
        "failed_checks": 0,
        "active_actions": 0,
        "indeterminate_actions": 0,
        "lifecycle_pending": 0,
        "limit_reached": False,
        "repairable_actions": 0,
        "stale_actions": 0,
        "user_scopes": 1,
    }
    assert not (tmp_path / "runtime").exists()
