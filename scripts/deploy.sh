#!/usr/bin/env bash
#
# deploy.sh - Build, start, or stop VassilFlow production services
#
# Commands:
#   deploy.sh                    — build + start
#   deploy.sh build              — build all images (mode-agnostic)
#   deploy.sh start              — start from pre-built images
#   deploy.sh down               — stop and remove containers
#
# Sandbox mode (local / aio / provisioner) is auto-detected from config.yaml.
#
# Examples:
#   deploy.sh                    # build + start
#   deploy.sh build              # build all images
#   deploy.sh start              # start pre-built images
#   deploy.sh down               # stop and remove containers
#
# Must be run from the repo root directory.

set -e

case "${1:-}" in
    build|start|down)
        CMD="$1"
        if [ -n "${2:-}" ]; then
            echo "Unknown argument: $2"
            echo "Usage: deploy.sh [build|start|down]"
            exit 1
        fi
        ;;
    "")
        CMD=""
        ;;
    *)
        echo "Unknown argument: $1"
        echo "Usage: deploy.sh [build|start|down]"
        exit 1
        ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DOCKER_DIR="$REPO_ROOT/docker"
COMPOSE_PROJECT_NAME="${VASSILFLOW_DOCKER_PROJECT:-${DEER_FLOW_DOCKER_PROJECT:-vassilflow}}"
LEGACY_COMPOSE_PROJECT_NAME="deer-flow"
COMPOSE_CMD=(docker compose -p "$COMPOSE_PROJECT_NAME" -f "$DOCKER_DIR/docker-compose.yaml")
DEFAULT_RUNTIME_HOME="$REPO_ROOT/backend/.vassilflow"
LEGACY_RUNTIME_HOME="$REPO_ROOT/backend/.deer-flow"

# ── Colors ────────────────────────────────────────────────────────────────────

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

vassilflow_alias_for() {
    case "$1" in
        DEER_FLOW_*) printf 'VASSILFLOW_%s\n' "${1#DEER_FLOW_}" ;;
        DEERFLOW_*) printf 'VASSILFLOW_%s\n' "${1#DEERFLOW_}" ;;
        *) return 1 ;;
    esac
}

sync_vassilflow_env() {
    local legacy="$1"
    local alias
    alias="$(vassilflow_alias_for "$legacy" 2>/dev/null || true)"
    [ -n "$alias" ] || return 0

    if [ -n "${!alias+x}" ]; then
        export "$legacy=${!alias}"
    elif [ -n "${!legacy+x}" ]; then
        export "$alias=${!legacy}"
    fi
}

sync_vassilflow_envs() {
    sync_vassilflow_env DEER_FLOW_HOME
    sync_vassilflow_env DEER_FLOW_REPO_ROOT
    sync_vassilflow_env DEER_FLOW_DOCKER_PROJECT
    sync_vassilflow_env DEER_FLOW_CONFIG_PATH
    sync_vassilflow_env DEER_FLOW_EXTENSIONS_CONFIG_PATH
    sync_vassilflow_env DEER_FLOW_INTERNAL_AUTH_TOKEN
    sync_vassilflow_env DEER_FLOW_CHANNELS_LANGGRAPH_URL
    sync_vassilflow_env DEER_FLOW_CHANNELS_GATEWAY_URL
    sync_vassilflow_env DEER_FLOW_DOCKER_SOCKET
}

compose_project_has_containers() {
    local project_name="$1"
    docker compose -p "$project_name" -f "$DOCKER_DIR/docker-compose.yaml" ps -q 2>/dev/null | grep -q .
}

down_compose_project() {
    local project_name="$1"
    docker compose -p "$project_name" -f "$DOCKER_DIR/docker-compose.yaml" down --remove-orphans >/dev/null 2>&1 || true
}

stop_legacy_stack_if_running() {
    if [ "$COMPOSE_PROJECT_NAME" = "$LEGACY_COMPOSE_PROJECT_NAME" ]; then
        return 0
    fi

    if compose_project_has_containers "$LEGACY_COMPOSE_PROJECT_NAME"; then
        echo -e "${YELLOW}Stopping legacy Docker project '$LEGACY_COMPOSE_PROJECT_NAME' before starting '$COMPOSE_PROJECT_NAME'.${NC}"
        down_compose_project "$LEGACY_COMPOSE_PROJECT_NAME"
        echo ""
    fi
}

default_runtime_home() {
    if [ ! -e "$DEFAULT_RUNTIME_HOME" ] && [ -e "$LEGACY_RUNTIME_HOME" ]; then
        printf '%s\n' "$LEGACY_RUNTIME_HOME"
    else
        printf '%s\n' "$DEFAULT_RUNTIME_HOME"
    fi
}

sync_vassilflow_envs

# ── VASSILFLOW_HOME / DEER_FLOW_HOME ─────────────────────────────────────────

if [ -z "${VASSILFLOW_HOME:-}" ]; then
    export VASSILFLOW_HOME
    VASSILFLOW_HOME="$(default_runtime_home)"
fi
sync_vassilflow_env DEER_FLOW_HOME
echo -e "${BLUE}VASSILFLOW_HOME=$VASSILFLOW_HOME${NC}"
mkdir -p "$VASSILFLOW_HOME"

# ── VASSILFLOW_REPO_ROOT (for skills host path in DooD) ──────────────────────

if [ -z "${VASSILFLOW_REPO_ROOT:-}" ]; then
    export VASSILFLOW_REPO_ROOT="$REPO_ROOT"
fi
sync_vassilflow_env DEER_FLOW_REPO_ROOT

# ── config.yaml ───────────────────────────────────────────────────────────────

if [ -z "${VASSILFLOW_CONFIG_PATH:-}" ]; then
    export VASSILFLOW_CONFIG_PATH="$REPO_ROOT/config.yaml"
fi
sync_vassilflow_env DEER_FLOW_CONFIG_PATH

if  [ "$CMD" != "down" ] && [ ! -f "$VASSILFLOW_CONFIG_PATH" ]; then
    # Try to seed from repo (config.example.yaml is the canonical template)
    if [ -f "$REPO_ROOT/config.example.yaml" ]; then
        cp "$REPO_ROOT/config.example.yaml" "$VASSILFLOW_CONFIG_PATH"
        echo -e "${GREEN}✓ Seeded config.example.yaml → $VASSILFLOW_CONFIG_PATH${NC}"
        echo -e "${YELLOW}⚠ config.yaml was seeded from the example template.${NC}"
        echo "  Run 'make setup' to generate a minimal config, or edit $VASSILFLOW_CONFIG_PATH manually before use."
    else
        echo -e "${RED}✗ No config.yaml found.${NC}"
        echo "  Run 'make setup' from the repo root (recommended),"
        echo "  or 'make config' for the full template, then set the required model API keys."
        exit 1
    fi
else
    echo -e "${GREEN}✓ config.yaml: $VASSILFLOW_CONFIG_PATH${NC}"
fi

# ── extensions_config.json ───────────────────────────────────────────────────

if [ -z "${VASSILFLOW_EXTENSIONS_CONFIG_PATH:-}" ]; then
    export VASSILFLOW_EXTENSIONS_CONFIG_PATH="$REPO_ROOT/extensions_config.json"
fi
sync_vassilflow_env DEER_FLOW_EXTENSIONS_CONFIG_PATH

if [ ! -f "$VASSILFLOW_EXTENSIONS_CONFIG_PATH" ]; then
    if [ -f "$REPO_ROOT/extensions_config.json" ]; then
        cp "$REPO_ROOT/extensions_config.json" "$VASSILFLOW_EXTENSIONS_CONFIG_PATH"
        echo -e "${GREEN}✓ Seeded extensions_config.json → $VASSILFLOW_EXTENSIONS_CONFIG_PATH${NC}"
    else
        # Create a minimal empty config so the gateway doesn't fail on startup
        echo '{"mcpServers":{},"skills":{}}' > "$VASSILFLOW_EXTENSIONS_CONFIG_PATH"
        echo -e "${YELLOW}⚠ extensions_config.json not found, created empty config at $VASSILFLOW_EXTENSIONS_CONFIG_PATH${NC}"
    fi
else
    echo -e "${GREEN}✓ extensions_config.json: $VASSILFLOW_EXTENSIONS_CONFIG_PATH${NC}"
fi


# ── BETTER_AUTH_SECRET ───────────────────────────────────────────────────────
# Required by Next.js in production. Generated once and persisted so auth
# sessions survive container restarts.

_secret_file="$VASSILFLOW_HOME/.better-auth-secret"
if [ -z "$BETTER_AUTH_SECRET" ]; then
    if [ -f "$_secret_file" ]; then
        export BETTER_AUTH_SECRET
        BETTER_AUTH_SECRET="$(cat "$_secret_file")"
        echo -e "${GREEN}✓ BETTER_AUTH_SECRET loaded from $_secret_file${NC}"
    else
        export BETTER_AUTH_SECRET
        if command -v python3 > /dev/null 2>&1 && \
            BETTER_AUTH_SECRET="$(python3 -c 'import sys; sys.version_info >= (3, 6) or sys.exit(1); import secrets; print(secrets.token_hex(32))' 2>/dev/null)"; then
            true
        elif command -v python > /dev/null 2>&1 && \
            BETTER_AUTH_SECRET="$(python -c 'import sys; sys.version_info >= (3, 6) or sys.exit(1); import secrets; print(secrets.token_hex(32))' 2>/dev/null)"; then
            true
        elif command -v openssl > /dev/null 2>&1 && \
            BETTER_AUTH_SECRET="$(openssl rand -hex 32)"; then
            true
        else
            echo -e "${RED}✗ Cannot generate BETTER_AUTH_SECRET: python3, python, and openssl are all unavailable.${NC}" >&2
            echo -e "${RED}  Set BETTER_AUTH_SECRET manually before running make up.${NC}" >&2
            exit 1
        fi
        echo "$BETTER_AUTH_SECRET" > "$_secret_file"
        chmod 600 "$_secret_file"
        echo -e "${GREEN}✓ BETTER_AUTH_SECRET generated → $_secret_file${NC}"
    fi
fi

# ── VASSILFLOW_INTERNAL_AUTH_TOKEN ───────────────────────────────────────────
# Shared by all Gateway workers so channel workers can call internal Gateway
# APIs even when the request is handled by a different Uvicorn worker.

_internal_auth_token_file="$VASSILFLOW_HOME/.internal-auth-token"
sync_vassilflow_env DEER_FLOW_INTERNAL_AUTH_TOKEN
if  [ "$CMD" != "down" ] && [ -z "${VASSILFLOW_INTERNAL_AUTH_TOKEN:-}" ]; then
    if [ -f "$_internal_auth_token_file" ]; then
        export VASSILFLOW_INTERNAL_AUTH_TOKEN
        VASSILFLOW_INTERNAL_AUTH_TOKEN="$(cat "$_internal_auth_token_file")"
        sync_vassilflow_env DEER_FLOW_INTERNAL_AUTH_TOKEN
        echo -e "${GREEN}✓ VASSILFLOW_INTERNAL_AUTH_TOKEN loaded from $_internal_auth_token_file${NC}"
    else
        export VASSILFLOW_INTERNAL_AUTH_TOKEN
        if command -v python3 > /dev/null 2>&1 && \
            VASSILFLOW_INTERNAL_AUTH_TOKEN="$(python3 -c 'import sys; sys.version_info >= (3, 6) or sys.exit(1); import secrets; print(secrets.token_urlsafe(32))' 2>/dev/null)"; then
            true
        elif command -v python > /dev/null 2>&1 && \
            VASSILFLOW_INTERNAL_AUTH_TOKEN="$(python -c 'import sys; sys.version_info >= (3, 6) or sys.exit(1); import secrets; print(secrets.token_urlsafe(32))' 2>/dev/null)"; then
            true
        elif command -v openssl > /dev/null 2>&1 && \
            VASSILFLOW_INTERNAL_AUTH_TOKEN="$(openssl rand -hex 32)"; then
            true
        else
            echo -e "${RED}✗ Cannot generate VASSILFLOW_INTERNAL_AUTH_TOKEN: python3, python, and openssl are all unavailable.${NC}" >&2
            echo -e "${RED}  Set VASSILFLOW_INTERNAL_AUTH_TOKEN manually before running make up.${NC}" >&2
            exit 1
        fi
        sync_vassilflow_env DEER_FLOW_INTERNAL_AUTH_TOKEN
        echo "$VASSILFLOW_INTERNAL_AUTH_TOKEN" > "$_internal_auth_token_file"
        chmod 600 "$_internal_auth_token_file"
        echo -e "${GREEN}✓ VASSILFLOW_INTERNAL_AUTH_TOKEN generated → $_internal_auth_token_file${NC}"
    fi
fi

# ── detect_sandbox_mode ───────────────────────────────────────────────────────

detect_sandbox_mode() {
    local sandbox_use=""
    local provisioner_url=""

    [ -f "$VASSILFLOW_CONFIG_PATH" ] || { echo "local"; return; }

    sandbox_use=$(awk '
        /^[[:space:]]*sandbox:[[:space:]]*$/ { in_sandbox=1; next }
        in_sandbox && /^[^[:space:]#]/ { in_sandbox=0 }
        in_sandbox && /^[[:space:]]*use:[[:space:]]*/ {
            line=$0; sub(/^[[:space:]]*use:[[:space:]]*/, "", line); print line; exit
        }
    ' "$VASSILFLOW_CONFIG_PATH")

    provisioner_url=$(awk '
        /^[[:space:]]*sandbox:[[:space:]]*$/ { in_sandbox=1; next }
        in_sandbox && /^[^[:space:]#]/ { in_sandbox=0 }
        in_sandbox && /^[[:space:]]*provisioner_url:[[:space:]]*/ {
            line=$0; sub(/^[[:space:]]*provisioner_url:[[:space:]]*/, "", line); print line; exit
        }
    ' "$VASSILFLOW_CONFIG_PATH")

    if [[ "$sandbox_use" == *"vassilflow.community.aio_sandbox:AioSandboxProvider"* || "$sandbox_use" == *"deerflow.community.aio_sandbox:AioSandboxProvider"* ]]; then
        if [ -n "$provisioner_url" ]; then
            echo "provisioner"
        else
            echo "aio"
        fi
    else
        echo "local"
    fi
}

# ── down ──────────────────────────────────────────────────────────────────────

if [ "$CMD" = "down" ]; then
    # Set minimal env var defaults so docker compose can parse the file without
    # warning about unset variables that appear in volume specs.
    sync_vassilflow_envs
    export VASSILFLOW_HOME="${VASSILFLOW_HOME:-$(default_runtime_home)}"
    export VASSILFLOW_CONFIG_PATH="${VASSILFLOW_CONFIG_PATH:-$VASSILFLOW_HOME/config.yaml}"
    export VASSILFLOW_EXTENSIONS_CONFIG_PATH="${VASSILFLOW_EXTENSIONS_CONFIG_PATH:-$VASSILFLOW_HOME/extensions_config.json}"
    export VASSILFLOW_REPO_ROOT="${VASSILFLOW_REPO_ROOT:-$REPO_ROOT}"
    export BETTER_AUTH_SECRET="${BETTER_AUTH_SECRET:-placeholder}"
    export VASSILFLOW_INTERNAL_AUTH_TOKEN="${VASSILFLOW_INTERNAL_AUTH_TOKEN:-placeholder}"
    sync_vassilflow_envs
    "${COMPOSE_CMD[@]}" down --remove-orphans
    if [ "$COMPOSE_PROJECT_NAME" != "$LEGACY_COMPOSE_PROJECT_NAME" ]; then
        down_compose_project "$LEGACY_COMPOSE_PROJECT_NAME"
    fi
    exit 0
fi

# ── build ────────────────────────────────────────────────────────────────────
# Build produces mode-agnostic images. No --gateway or sandbox detection needed.

if [ "$CMD" = "build" ]; then
    echo "=========================================="
    echo "  VassilFlow — Building Images"
    echo "=========================================="
    echo ""

    "${COMPOSE_CMD[@]}" build

    echo ""
    echo "=========================================="
    echo "  ✓ Images built successfully"
    echo "=========================================="
    echo ""
    echo "  Next: deploy.sh start"
    echo ""
    exit 0
fi

# ── Banner ────────────────────────────────────────────────────────────────────

echo "=========================================="
echo "  VassilFlow Production Deployment"
echo "=========================================="
echo ""

# ── Detect runtime configuration ────────────────────────────────────────────
# Only needed for start / up — determines whether provisioner is launched.

sandbox_mode="$(detect_sandbox_mode)"
echo -e "${BLUE}Sandbox mode: $sandbox_mode${NC}"

echo -e "${BLUE}Runtime: Gateway embedded agent runtime${NC}"

services="frontend gateway nginx"

if [ "$sandbox_mode" = "provisioner" ]; then
    services="$services provisioner"
fi

# ── VASSILFLOW_DOCKER_SOCKET (aio / pure-DooD mode only) ─────────────────────
# Only aio mode (AioSandboxProvider without provisioner_url) needs the host
# Docker socket. It is mounted via the opt-in docker-compose.dood.yaml overlay,
# appended here, so the default (local) and provisioner modes never expose the
# host daemon. Mounting the socket = root-equivalent host control; see SECURITY.md.

sync_vassilflow_env DEER_FLOW_DOCKER_SOCKET
if [ -z "${VASSILFLOW_DOCKER_SOCKET:-}" ]; then
    export VASSILFLOW_DOCKER_SOCKET="/var/run/docker.sock"
fi
sync_vassilflow_env DEER_FLOW_DOCKER_SOCKET

if [ "$sandbox_mode" = "aio" ]; then
    if [ ! -S "$VASSILFLOW_DOCKER_SOCKET" ]; then
        echo -e "${RED}⚠ Docker socket not found at $VASSILFLOW_DOCKER_SOCKET${NC}"
        echo "  AioSandboxProvider (DooD) will not work."
        exit 1
    fi
    echo -e "${GREEN}✓ Docker socket: $VASSILFLOW_DOCKER_SOCKET${NC}"
    echo -e "${YELLOW}  Mounting host Docker socket into gateway (DooD = host root-equivalent). See SECURITY.md.${NC}"
    COMPOSE_CMD+=(-f "$DOCKER_DIR/docker-compose.dood.yaml")
fi

echo ""

# ── Start / Up ───────────────────────────────────────────────────────────────

stop_legacy_stack_if_running

if [ "$CMD" = "start" ]; then
    echo "Starting containers (no rebuild)..."
    echo ""
    # shellcheck disable=SC2086
    "${COMPOSE_CMD[@]}" up -d --remove-orphans $services
else
    # Default: build + start
    echo "Building images and starting containers..."
    echo ""
    # shellcheck disable=SC2086
    "${COMPOSE_CMD[@]}" up --build -d --remove-orphans $services
fi

echo ""
echo "=========================================="
echo "  VassilFlow is running!"
echo "=========================================="
echo ""
echo "  🌐 Application: http://localhost:${PORT:-2026}"
echo "  📡 API Gateway: http://localhost:${PORT:-2026}/api/*"
echo "  🤖 Runtime:     Gateway embedded"
echo "  API:            /api/langgraph/* → Gateway"
echo ""
echo "  Manage:"
echo "    make down        — stop and remove containers"
echo "    make docker-logs — view logs"
echo ""
