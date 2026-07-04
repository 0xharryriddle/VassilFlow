"""Regression coverage for the Gateway-owned LangGraph API runtime."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_root_makefile_no_longer_exposes_transition_gateway_targets():
    makefile = _read("Makefile")

    assert "dev-pro" not in makefile
    assert "start-pro" not in makefile
    assert "dev-daemon-pro" not in makefile
    assert "start-daemon-pro" not in makefile
    assert "docker-start-pro" not in makefile
    assert "up-pro" not in makefile
    assert not re.search(r"serve\.sh .*--gateway", makefile)
    assert "docker.sh start --gateway" not in makefile
    assert "deploy.sh --gateway" not in makefile


def test_service_launchers_always_use_gateway_runtime():
    operational_files = {
        "scripts/serve.sh": _read("scripts/serve.sh"),
        "scripts/docker.sh": _read("scripts/docker.sh"),
        "scripts/deploy.sh": _read("scripts/deploy.sh"),
        "docker/docker-compose-dev.yaml": _read("docker/docker-compose-dev.yaml"),
        "docker/docker-compose.yaml": _read("docker/docker-compose.yaml"),
    }

    for path, content in operational_files.items():
        assert "start --gateway" not in content, path
        assert "deploy.sh --gateway" not in content, path
        assert "langgraph dev" not in content, path
        assert "LANGGRAPH_UPSTREAM" not in content, path
        assert "LANGGRAPH_REWRITE" not in content, path


def test_local_dev_gateway_reload_excludes_runtime_state_with_absolute_dirs():
    serve_sh = _read("scripts/serve.sh")

    assert "sync_vassilflow_env" not in serve_sh
    assert "DEER_FLOW" not in serve_sh
    assert 'export VASSILFLOW_PROJECT_ROOT="$REPO_ROOT"' in serve_sh
    assert 'BACKEND_RUNTIME_HOME="$REPO_ROOT/backend/.vassilflow"' in serve_sh
    assert 'export VASSILFLOW_HOME="$BACKEND_RUNTIME_HOME"' in serve_sh
    assert "export VASSILFLOW_HOME" in serve_sh
    assert "VASSILFLOW_ROOTS=" in serve_sh
    assert "DEERFLOW_ROOTS=" not in serve_sh
    assert "_is_vassilflow_pid()" in serve_sh
    assert "_is_deerflow_pid()" not in serve_sh
    assert "VASSILFLOW_DAEMON_ROOT" in serve_sh
    assert "DEERFLOW_DAEMON_ROOT" not in serve_sh
    # Every absolute reload-exclude must be pre-created, including backend/sandbox
    # (#3459 / #3454) — see test_uvicorn_reload_exclude.py for the mechanism.
    assert 'mkdir -p "$VASSILFLOW_HOME" "$REPO_ROOT/backend/sandbox"' in serve_sh
    assert "--reload-exclude='$VASSILFLOW_HOME'" in serve_sh
    assert "--reload-exclude='sandbox/'" not in serve_sh
    assert "--reload-exclude='.deer-flow/'" not in serve_sh


def test_shell_launchers_use_vassilflow_env_only():
    scripts = {
        "scripts/deploy.sh": _read("scripts/deploy.sh"),
        "scripts/docker.sh": _read("scripts/docker.sh"),
        "scripts/config-upgrade.sh": _read("scripts/config-upgrade.sh"),
    }

    for path, content in scripts.items():
        assert "vassilflow_alias_for()" not in content, path
        assert "sync_vassilflow_env()" not in content, path
        assert "DEER_FLOW" not in content, path
        assert "DEERFLOW" not in content, path

    deploy_sh = scripts["scripts/deploy.sh"]
    config_upgrade_sh = scripts["scripts/config-upgrade.sh"]
    assert 'if [ -z "${VASSILFLOW_HOME:-}" ]; then' in deploy_sh
    assert 'mkdir -p "$VASSILFLOW_HOME"' in deploy_sh
    assert 'if [ -z "${VASSILFLOW_CONFIG_PATH:-}" ]; then' in deploy_sh
    assert '[ -f "$VASSILFLOW_CONFIG_PATH" ] || { echo "local"; return; }' in deploy_sh
    assert 'export VASSILFLOW_HOME="${VASSILFLOW_HOME:-$DEFAULT_RUNTIME_HOME}"' in deploy_sh
    assert 'export VASSILFLOW_CONFIG_PATH="${VASSILFLOW_CONFIG_PATH:-$VASSILFLOW_HOME/config.yaml}"' in deploy_sh
    assert 'export VASSILFLOW_INTERNAL_AUTH_TOKEN="${VASSILFLOW_INTERNAL_AUTH_TOKEN:-placeholder}"' in deploy_sh
    assert 'if [ -z "${VASSILFLOW_DOCKER_SOCKET:-}" ]; then' in deploy_sh
    assert 'CONFIG="$VASSILFLOW_CONFIG_PATH"' in config_upgrade_sh

    docker_sh = scripts["scripts/docker.sh"]
    assert 'local docker_socket="${VASSILFLOW_DOCKER_SOCKET:-/var/run/docker.sock}"' in docker_sh
    assert 'export VASSILFLOW_DOCKER_SOCKET="$docker_socket"' in docker_sh
    assert 'if [ -z "${VASSILFLOW_RUNTIME_HOME:-}" ]; then' in docker_sh
    assert 'VASSILFLOW_RUNTIME_HOME="$(default_runtime_home)"' in docker_sh
    assert 'if [ -z "${VASSILFLOW_CONTAINER_HOME:-}" ]; then' in docker_sh
    assert 'VASSILFLOW_CONTAINER_HOME="$(container_runtime_home_for "$VASSILFLOW_RUNTIME_HOME")"' in docker_sh
    assert 'if [ -z "${VASSILFLOW_ROOT:-}" ]; then' in docker_sh


def test_compose_files_expose_vassilflow_runtime_env_only():
    prod = _read("docker/docker-compose.yaml")
    dev = _read("docker/docker-compose-dev.yaml")
    dood = _read("docker/docker-compose.dood.yaml")

    assert "DEER_FLOW" not in prod
    assert "DEER_FLOW" not in dev
    assert "DEER_FLOW" not in dood
    assert "${VASSILFLOW_CONFIG_PATH:-../config.yaml}" in prod
    assert "${VASSILFLOW_EXTENSIONS_CONFIG_PATH:-../extensions_config.json}" in prod
    assert "${VASSILFLOW_HOME:-../backend/.vassilflow}" in prod
    assert ":/app/backend/.vassilflow" in prod
    assert "VASSILFLOW_PROJECT_ROOT=/app" in prod
    assert "VASSILFLOW_HOME=/app/backend/.vassilflow" in prod
    assert "VASSILFLOW_INTERNAL_AUTH_TOKEN=${VASSILFLOW_INTERNAL_AUTH_TOKEN:-}" in prod
    assert "VASSILFLOW_HOST_BASE_DIR=${VASSILFLOW_HOME:-../backend/.vassilflow}" in prod
    assert "VASSILFLOW_HOST_SKILLS_PATH=${VASSILFLOW_REPO_ROOT:-..}/skills" in prod
    assert "VASSILFLOW_INTERNAL_GATEWAY_BASE_URL=http://gateway:8001" in prod

    assert "${VASSILFLOW_ROOT:-..}/skills" in dev
    assert "VASSILFLOW_INTERNAL_GATEWAY_BASE_URL=http://gateway:8001" in dev
    assert "VASSILFLOW_PROJECT_ROOT=/app" in dev
    assert "VASSILFLOW_HOME=${VASSILFLOW_CONTAINER_HOME:-/app/backend/.vassilflow}" in dev
    assert "VASSILFLOW_HOST_BASE_DIR=${VASSILFLOW_RUNTIME_HOME:-${VASSILFLOW_ROOT:-..}/backend/.vassilflow}" in dev

    assert "${VASSILFLOW_DOCKER_SOCKET:-/var/run/docker.sock}" in dood


def test_backend_container_only_exposes_gateway_port():
    dockerfile = _read("backend/Dockerfile")

    assert not re.search(r"^EXPOSE\s+.*\b2024\b", dockerfile, re.M)
    assert "langgraph: 2024" not in dockerfile
    assert re.search(r"^EXPOSE\s+8001\b", dockerfile, re.M)


def test_root_makefile_clean_does_not_reference_langgraph_server_cache():
    makefile = _read("Makefile")

    assert ".langgraph_api" not in makefile


def test_root_makefile_does_not_expose_legacy_runtime_migration():
    makefile = _read("Makefile")

    assert "runtime-migrate" not in makefile
    assert "backend/.deer-flow" not in makefile


def test_nginx_routes_official_langgraph_prefix_to_gateway_api():
    for path in ("docker/nginx/nginx.local.conf", "docker/nginx/nginx.conf"):
        content = _read(path)

        assert "/api/langgraph-compat" not in content
        assert "proxy_pass http://langgraph" not in content
        assert "rewrite ^/api/langgraph/(.*) /api/$1 break;" in content
        assert "proxy_pass http://gateway" in content or "proxy_pass http://$gateway_upstream" in content


def test_nginx_defers_cors_to_gateway_allowlist():
    for path in ("docker/nginx/nginx.local.conf", "docker/nginx/nginx.conf"):
        content = _read(path)

        assert "Access-Control-Allow-Origin" not in content
        assert "Access-Control-Allow-Methods" not in content
        assert "Access-Control-Allow-Headers" not in content
        assert "Access-Control-Allow-Credentials" not in content
        assert "proxy_hide_header 'Access-Control-Allow-" not in content
        assert "if ($request_method = 'OPTIONS')" not in content


def test_gateway_cors_configuration_uses_gateway_allowlist():
    gateway_config = _read("backend/app/gateway/config.py")
    gateway_app = _read("backend/app/gateway/app.py")
    csrf_middleware = _read("backend/app/gateway/csrf_middleware.py")

    assert not re.search(r"(?<!GATEWAY_)[\"']CORS_ORIGINS[\"']", gateway_config)
    assert "cors_origins" not in gateway_config
    assert "get_configured_cors_origins" in gateway_app
    assert "GATEWAY_CORS_ORIGINS" in csrf_middleware


def test_frontend_rewrites_langgraph_prefix_to_gateway():
    next_config = _read("frontend/next.config.js")
    api_client = _read("frontend/src/core/api/api-client.ts")

    assert "DEER_FLOW_INTERNAL_LANGGRAPH_BASE_URL" not in next_config
    assert "http://127.0.0.1:2024" not in next_config
    assert "langgraph-compat" not in api_client


def test_smoke_test_docs_do_not_expect_standalone_langgraph_server():
    smoke_files = {
        ".agent/skills/smoke-test/SKILL.md": _read(".agent/skills/smoke-test/SKILL.md"),
        ".agent/skills/smoke-test/references/SOP.md": _read(".agent/skills/smoke-test/references/SOP.md"),
        ".agent/skills/smoke-test/references/troubleshooting.md": _read(".agent/skills/smoke-test/references/troubleshooting.md"),
        ".agent/skills/smoke-test/scripts/check_local_env.sh": _read(".agent/skills/smoke-test/scripts/check_local_env.sh"),
        ".agent/skills/smoke-test/scripts/deploy_local.sh": _read(".agent/skills/smoke-test/scripts/deploy_local.sh"),
        ".agent/skills/smoke-test/scripts/health_check.sh": _read(".agent/skills/smoke-test/scripts/health_check.sh"),
        ".agent/skills/smoke-test/templates/report.local.template.md": _read(".agent/skills/smoke-test/templates/report.local.template.md"),
        ".agent/skills/smoke-test/templates/report.docker.template.md": _read(".agent/skills/smoke-test/templates/report.docker.template.md"),
    }

    for path, content in smoke_files.items():
        assert "localhost:2024" not in content, path
        assert "127.0.0.1:2024" not in content, path
        assert "deer-flow-langgraph" not in content, path
        assert "langgraph.log" not in content, path
        assert "LangGraph service" not in content, path
        assert "langgraph dev" not in content, path


def test_gateway_runtime_docs_do_not_reference_transition_modes():
    docs = {
        "backend/docs/AUTH_UPGRADE.md": _read("backend/docs/AUTH_UPGRADE.md"),
        "backend/docs/AUTH_TEST_DOCKER_GAP.md": _read("backend/docs/AUTH_TEST_DOCKER_GAP.md"),
    }

    for path, content in docs.items():
        assert "make dev-pro" not in content, path
        assert "./scripts/deploy.sh --gateway" not in content, path
        assert "docker compose --profile gateway" not in content, path
        assert "`/api/langgraph/*` → LangGraph" not in content, path


def test_agent_instruction_docs_do_not_reference_standalone_langgraph_server():
    """Agent/Copilot instruction docs must describe only the Gateway-embedded
    runtime — no standalone LangGraph service, port 2024, or langgraph.log."""
    content = _read(".github/copilot-instructions.md")

    assert "langgraph.log" not in content
    assert "localhost:2024" not in content
    assert "127.0.0.1:2024" not in content
    assert "Starts LangGraph" not in content
