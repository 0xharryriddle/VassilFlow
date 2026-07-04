"""Regression tests for VassilFlow Docker naming defaults."""

from __future__ import annotations

import subprocess
from pathlib import Path
from shutil import which

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKER_DIR = REPO_ROOT / "docker"
DOCKER_SCRIPT = REPO_ROOT / "scripts" / "docker.sh"
BASH_CANDIDATES = [
    Path(r"C:\Program Files\Git\bin\bash.exe"),
    Path(which("bash")) if which("bash") else None,
]
BASH_EXECUTABLE = next(
    (str(path) for path in BASH_CANDIDATES if path is not None and path.exists() and "WindowsApps" not in str(path)),
    None,
)


def _load_compose(name: str) -> dict:
    return yaml.safe_load((DOCKER_DIR / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("compose_file", "expected_network"),
    [
        ("docker-compose-dev.yaml", "vassilflow-dev"),
        ("docker-compose.yaml", "vassilflow"),
    ],
)
def test_compose_container_and_network_names_use_vassilflow(compose_file: str, expected_network: str):
    compose = _load_compose(compose_file)

    assert expected_network in compose["networks"]
    assert all("deer-flow" not in network for network in compose["networks"])

    for service in compose["services"].values():
        container_name = service.get("container_name")
        if container_name:
            assert container_name.startswith("vassilflow-")
            assert "deer-flow" not in container_name
        assert service.get("networks") in ([expected_network], None)


@pytest.mark.parametrize("compose_file", ["docker-compose-dev.yaml", "docker-compose.yaml"])
def test_compose_provisioner_defaults_use_vassilflow_labels(compose_file: str):
    compose = _load_compose(compose_file)
    environment = compose["services"]["provisioner"]["environment"]

    assert "K8S_NAMESPACE=${VASSILFLOW_K8S_NAMESPACE:-vassilflow}" in environment
    assert "SANDBOX_APP_LABEL=${VASSILFLOW_SANDBOX_APP_LABEL:-vassilflow-sandbox}" in environment
    assert "USERDATA_PVC_SUBPATH_ROOT=${VASSILFLOW_USERDATA_PVC_SUBPATH_ROOT:-vassilflow}" in environment


@pytest.mark.skipif(BASH_EXECUTABLE is None, reason="bash is required for docker.sh naming tests")
def test_docker_script_defaults_to_vassilflow_project_and_sandbox_prefix():
    command = f'export VASSILFLOW_DOCKER_CLI_AUTH=0 DEER_FLOW_DOCKER_CLI_AUTH=0; source \'{DOCKER_SCRIPT}\' >/dev/null && printf \'%s\\n%s\\n%s\\n\' "$COMPOSE_PROJECT_NAME" "$COMPOSE_CMD" "$SANDBOX_CONTAINER_PREFIX"'

    output = subprocess.check_output(
        [BASH_EXECUTABLE, "-lc", command],
        text=True,
        encoding="utf-8",
    ).splitlines()

    assert output[0] == "vassilflow-dev"
    assert "docker compose -p vassilflow-dev" in output[1]
    assert "docker-compose.cli-auth.yaml" not in output[1]
    assert output[2] == "vassilflow-sandbox"


@pytest.mark.skipif(BASH_EXECUTABLE is None, reason="bash is required for docker.sh naming tests")
def test_docker_script_excludes_container_paths_from_msys_conversion():
    command = f'source \'{DOCKER_SCRIPT}\' >/dev/null && printf \'%s\\n%s\\n%s\\n\' "$MSYS_NO_PATHCONV" "$MSYS2_ARG_CONV_EXCL" "$MSYS2_ENV_CONV_EXCL"'

    output = subprocess.check_output(
        [BASH_EXECUTABLE, "-lc", command],
        text=True,
        encoding="utf-8",
    ).splitlines()

    assert output[0] == "1"
    assert output[1] == "*"
    assert "VASSILFLOW_CONTAINER_HOME" in output[2]
    assert "CODEX_AUTH_PATH" in output[2]


@pytest.mark.skipif(BASH_EXECUTABLE is None, reason="bash is required for docker.sh naming tests")
def test_docker_script_can_opt_into_cli_auth_overlay():
    command = f"export VASSILFLOW_DOCKER_CLI_AUTH=1 HOME=/tmp; source '{DOCKER_SCRIPT}' >/dev/null && printf '%s\\n' \"$COMPOSE_CMD\""

    output = subprocess.check_output(
        [BASH_EXECUTABLE, "-lc", command],
        text=True,
        encoding="utf-8",
    )

    assert "docker-compose-dev.yaml" in output
    assert "docker-compose.cli-auth.yaml" in output


def test_scripts_do_not_keep_legacy_docker_names():
    docker_script = (REPO_ROOT / "scripts" / "docker.sh").read_text(encoding="utf-8")
    deploy_script = (REPO_ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")

    assert "deer-flow-dev" not in docker_script
    assert "deer-flow-sandbox" not in docker_script
    assert "deer-flow" not in deploy_script
