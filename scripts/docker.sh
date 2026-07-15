#!/usr/bin/env bash
set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DOCKER_DIR="$PROJECT_ROOT/docker"

# Docker Compose command with project name.
COMPOSE_PROJECT_NAME="${VASSILFLOW_DOCKER_DEV_PROJECT:-vassilflow-dev}"
COMPOSE_FILE="$DOCKER_DIR/docker-compose-dev.yaml"
COMPOSE_CMD="docker compose -p $COMPOSE_PROJECT_NAME -f docker-compose-dev.yaml"
SANDBOX_CONTAINER_PREFIX="${VASSILFLOW_SANDBOX_CONTAINER_PREFIX:-vassilflow-sandbox}"
DEFAULT_RUNTIME_HOME="$PROJECT_ROOT/backend/.vassilflow"

configure_msys_docker_path_conversion() {
    # Git Bash converts /app and /root-style values for Windows executables.
    # These values are Linux container paths and must reach Docker unchanged.
    local excluded_vars="VASSILFLOW_CONTAINER_HOME;VASSILFLOW_HOME;CODEX_AUTH_PATH"
    export MSYS_NO_PATHCONV="${MSYS_NO_PATHCONV:-1}"
    export MSYS2_ARG_CONV_EXCL="${MSYS2_ARG_CONV_EXCL:-*}"
    if [ -n "${MSYS2_ENV_CONV_EXCL:-}" ]; then
        case ";$MSYS2_ENV_CONV_EXCL;" in
            *";VASSILFLOW_CONTAINER_HOME;"*) ;;
            *) export MSYS2_ENV_CONV_EXCL="$MSYS2_ENV_CONV_EXCL;$excluded_vars" ;;
        esac
    else
        export MSYS2_ENV_CONV_EXCL="$excluded_vars"
    fi
}

configure_msys_docker_path_conversion

load_env_var_from_dotenv_if_unset() {
    local var="$1"
    local env_file="$PROJECT_ROOT/.env"
    local line
    local value

    if [ -n "${!var+x}" ] || [ ! -f "$env_file" ]; then
        return
    fi

    line="$(grep -E "^[[:space:]]*${var}=" "$env_file" | tail -n 1 || true)"
    if [ -z "$line" ]; then
        return
    fi

    value="${line#*=}"
    value="${value%%#*}"
    value="$(printf '%s' "$value" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
    value="${value%$'\r'}"
    export "${var}=${value}"
}

load_docker_control_env_from_dotenv() {
    load_env_var_from_dotenv_if_unset VASSILFLOW_DOCKER_CLI_AUTH
}

is_truthy() {
    case "${1:-}" in
        1|true|TRUE|yes|YES|on|ON) return 0 ;;
        *) return 1 ;;
    esac
}

ensure_home_for_cli_auth_overlay() {
    if [ -n "${HOME:-}" ]; then
        return 0
    fi
    if [ -n "${USERPROFILE:-}" ] && command -v cygpath >/dev/null 2>&1; then
        export HOME
        HOME="$(cygpath -u "$USERPROFILE")"
        return 0
    fi

    echo -e "${YELLOW}VASSILFLOW_DOCKER_CLI_AUTH is enabled, but HOME is not set for the compose auth overlay.${NC}"
    echo "Set HOME to your user directory or disable VASSILFLOW_DOCKER_CLI_AUTH."
    exit 1
}

enable_cli_auth_overlay_if_requested() {
    load_docker_control_env_from_dotenv
    if is_truthy "${VASSILFLOW_DOCKER_CLI_AUTH:-}"; then
        ensure_home_for_cli_auth_overlay
        COMPOSE_CMD="$COMPOSE_CMD -f docker-compose.cli-auth.yaml"
    fi
}

default_runtime_home() {
    printf '%s\n' "$DEFAULT_RUNTIME_HOME"
}

container_runtime_home_for() {
    printf '%s\n' "/app/backend/.vassilflow"
}

enable_cli_auth_overlay_if_requested

load_proxy_env_from_dotenv() {
    local env_file="$PROJECT_ROOT/.env"
    local var
    local line
    local value

    if [ ! -f "$env_file" ]; then
        return
    fi

    for var in HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY http_proxy https_proxy all_proxy no_proxy; do
        if [ -z "${!var+x}" ]; then
            line="$(grep -E "^[[:space:]]*${var}=" "$env_file" | tail -n 1 || true)"
            if [ -n "$line" ]; then
                value="${line#*=}"
                value="${value%\"}"
                value="${value#\"}"
                value="${value%\'}"
                value="${value#\'}"
                value="${value%$'\r'}"
                export "${var}=${value}"
            fi
        fi
    done
}

detect_sandbox_mode() {
    local config_file="$PROJECT_ROOT/config.yaml"
    local sandbox_use=""
    local provisioner_url=""

    if [ ! -f "$config_file" ]; then
        echo "local"
        return
    fi

    sandbox_use=$(awk '
        /^[[:space:]]*sandbox:[[:space:]]*$/ { in_sandbox=1; next }
        in_sandbox && /^[^[:space:]#]/ { in_sandbox=0 }
        in_sandbox && /^[[:space:]]*use:[[:space:]]*/ {
            line=$0
            sub(/^[[:space:]]*use:[[:space:]]*/, "", line)
            print line
            exit
        }
    ' "$config_file")

    provisioner_url=$(awk '
        /^[[:space:]]*sandbox:[[:space:]]*$/ { in_sandbox=1; next }
        in_sandbox && /^[^[:space:]#]/ { in_sandbox=0 }
        in_sandbox && /^[[:space:]]*provisioner_url:[[:space:]]*/ {
            line=$0
            sub(/^[[:space:]]*provisioner_url:[[:space:]]*/, "", line)
            print line
            exit
        }
    ' "$config_file")

    if [[ "$sandbox_use" == *"vassilflow.sandbox.local:LocalSandboxProvider"* ]]; then
        echo "local"
    elif [[ "$sandbox_use" == *"vassilflow.community.aio_sandbox:AioSandboxProvider"* ]]; then
        if [ -n "$provisioner_url" ]; then
            echo "provisioner"
        else
            echo "aio"
        fi
    else
        echo "local"
    fi
}

# Cleanup function for Ctrl+C
cleanup() {
    echo ""
    echo -e "${YELLOW}Operation interrupted by user${NC}"
    exit 130
}

# Set up trap for Ctrl+C
trap cleanup INT TERM

docker_available() {
    # Check that the docker CLI exists
    if ! command -v docker >/dev/null 2>&1; then
        return 1
    fi

    # Check that the Docker daemon is reachable
    if ! docker info >/dev/null 2>&1; then
        return 1
    fi

    return 0
}

# Initialize: pre-pull the sandbox image so first Pod startup is fast
init() {
    echo "=========================================="
    echo "  VassilFlow Init — Pull Sandbox Image"
    echo "=========================================="
    echo ""

    SANDBOX_IMAGE="enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest"

    # Detect sandbox mode from config.yaml
    local sandbox_mode
    sandbox_mode="$(detect_sandbox_mode)"

    # Skip image pull for local sandbox mode (no container image needed)
    if [ "$sandbox_mode" = "local" ]; then
        echo -e "${GREEN}Detected local sandbox mode — no Docker image required.${NC}"
        echo ""

        if docker_available; then
            echo -e "${GREEN}✓ Docker environment is ready.${NC}"
            echo ""
            echo -e "${YELLOW}Next step: make docker-start${NC}"
        else
            echo -e "${YELLOW}Docker does not appear to be installed, or the Docker daemon is not reachable.${NC}"
            echo "Local sandbox mode itself does not require Docker, but Docker-based workflows (e.g., docker-start) will fail until Docker is available."
            echo ""
            echo -e "${YELLOW}Install and start Docker, then run: make docker-init && make docker-start${NC}"
        fi

        return 0
    fi

    if ! docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "^${SANDBOX_IMAGE}$"; then
        echo -e "${BLUE}Pulling sandbox image: $SANDBOX_IMAGE ...${NC}"
        echo ""

        if ! docker pull "$SANDBOX_IMAGE" 2>&1; then
            echo ""
            echo -e "${YELLOW}⚠ Failed to pull sandbox image.${NC}"
            echo ""
            echo "This is expected if:"
            echo "  1. You are using local sandbox mode (default — no image needed)"
            echo "  2. You are behind a corporate proxy or firewall"
            echo "  3. The registry requires authentication"
            echo ""
            echo -e "${GREEN}The Docker development environment can still be started.${NC}"
            echo "If you need AIO sandbox (container-based execution):"
            echo "  - Ensure you have network access to the registry"
            echo "  - Or configure a custom sandbox image in config.yaml"
            echo ""
            echo -e "${YELLOW}Next step: make docker-start${NC}"
            return 0
        fi
    else
        echo -e "${GREEN}Sandbox image already exists locally: $SANDBOX_IMAGE${NC}"
    fi

    echo ""
    echo -e "${GREEN}✓ Sandbox image is ready.${NC}"
    echo ""
    echo -e "${YELLOW}Next step: make docker-start${NC}"
}

# Start Docker development environment
start() {
    local sandbox_mode
    local services

    if [ "$#" -gt 0 ]; then
        echo -e "${YELLOW}Unknown option for start: $1${NC}"
        echo "Usage: $0 start"
        exit 1
    fi

    echo "=========================================="
    echo "  Starting VassilFlow Docker Development"
    echo "=========================================="
    echo ""

    sandbox_mode="$(detect_sandbox_mode)"

    services="frontend gateway office-renderer office-renderer-proxy nginx"
    if [ "$sandbox_mode" = "provisioner" ]; then
        services="frontend gateway office-renderer office-renderer-proxy provisioner nginx"
    fi

    # Only aio mode (AioSandboxProvider without provisioner_url) needs the host
    # Docker socket. Mount it via the opt-in docker-compose.dood.yaml overlay so
    # the default (local) and provisioner modes never expose the host daemon.
    # Mounting the socket = root-equivalent host control; see SECURITY.md.
    if [ "$sandbox_mode" = "aio" ]; then
        local docker_socket="${VASSILFLOW_DOCKER_SOCKET:-/var/run/docker.sock}"
        export VASSILFLOW_DOCKER_SOCKET="$docker_socket"
        if [ ! -S "$docker_socket" ]; then
            echo -e "${YELLOW}⚠ Docker socket not found at $docker_socket — AioSandboxProvider (DooD) will not work.${NC}"
            exit 1
        fi
        echo -e "${YELLOW}Mounting host Docker socket into gateway (DooD = host root-equivalent). See SECURITY.md.${NC}"
        COMPOSE_CMD="$COMPOSE_CMD -f $DOCKER_DIR/docker-compose.dood.yaml"
    fi

    echo -e "${BLUE}Runtime: Gateway embedded agent runtime${NC}"
    echo -e "${BLUE}Detected sandbox mode: $sandbox_mode${NC}"
    if [ "$sandbox_mode" = "provisioner" ]; then
        echo -e "${BLUE}Provisioner enabled (Kubernetes mode).${NC}"
    else
        echo -e "${BLUE}Provisioner disabled (not required for this sandbox mode).${NC}"
    fi
    echo ""
    

    if [ -z "${VASSILFLOW_RUNTIME_HOME:-}" ]; then
        export VASSILFLOW_RUNTIME_HOME
        VASSILFLOW_RUNTIME_HOME="$(default_runtime_home)"
    fi

    if [ -z "${VASSILFLOW_CONTAINER_HOME:-}" ]; then
        export VASSILFLOW_CONTAINER_HOME
        VASSILFLOW_CONTAINER_HOME="$(container_runtime_home_for "$VASSILFLOW_RUNTIME_HOME")"
    fi

    # Set repo root for provisioner if not already set
    if [ -z "${VASSILFLOW_ROOT:-}" ]; then
        export VASSILFLOW_ROOT="$PROJECT_ROOT"
        echo -e "${BLUE}Setting VASSILFLOW_ROOT=$VASSILFLOW_ROOT${NC}"
        echo ""
    fi
    
    # Ensure config.yaml exists before starting.
    if [ ! -f "$PROJECT_ROOT/config.yaml" ]; then
        if [ -f "$PROJECT_ROOT/config.example.yaml" ]; then
            cp "$PROJECT_ROOT/config.example.yaml" "$PROJECT_ROOT/config.yaml"
            echo ""
            echo -e "${YELLOW}============================================================${NC}"
            echo -e "${YELLOW}  config.yaml has been created from config.example.yaml.${NC}"
            echo -e "${YELLOW}  Please edit config.yaml to set your API keys and model   ${NC}"
            echo -e "${YELLOW}  configuration before starting VassilFlow.                  ${NC}"
            echo -e "${YELLOW}============================================================${NC}"
            echo ""
            echo -e "${YELLOW}  Recommended: run 'make setup' before starting Docker.    ${NC}"
            echo -e "${YELLOW}  Edit the file:  $PROJECT_ROOT/config.yaml${NC}"
            echo -e "${YELLOW}  Then run:        make docker-start${NC}"
            echo ""
            exit 0
        else
            echo -e "${YELLOW}✗ config.yaml not found and no config.example.yaml to copy from.${NC}"
            exit 1
        fi
    fi

    # Ensure extensions_config.json exists as a file before mounting.
    # Docker creates a directory when bind-mounting a non-existent host path.
    if [ ! -f "$PROJECT_ROOT/extensions_config.json" ]; then
        if [ -f "$PROJECT_ROOT/extensions_config.example.json" ]; then
            cp "$PROJECT_ROOT/extensions_config.example.json" "$PROJECT_ROOT/extensions_config.json"
            echo -e "${BLUE}Created extensions_config.json from example${NC}"
        else
            echo "{}" > "$PROJECT_ROOT/extensions_config.json"
            echo -e "${BLUE}Created empty extensions_config.json${NC}"
        fi
    fi

    load_proxy_env_from_dotenv

    echo "Building and starting containers..."
    cd "$DOCKER_DIR" && $COMPOSE_CMD up --build -d --remove-orphans $services
    echo ""
    echo "=========================================="
    echo "  VassilFlow Docker is starting!"
    echo "=========================================="
    echo ""
    echo "  🌐 Application: http://localhost:2026"
    echo "  📡 API Gateway: http://localhost:2026/api/*"
    echo "  🤖 Runtime:     Gateway embedded"
    echo "  API:            /api/langgraph/* → Gateway"
    echo ""
    echo "  📋 View logs: make docker-logs"
    echo "  🛑 Stop:      make docker-stop"
    echo ""
}

# View Docker development logs
logs() {
    local service=""
    
    case "$1" in
        --frontend)
            service="frontend"
            echo -e "${BLUE}Viewing frontend logs...${NC}"
            ;;
        --gateway)
            service="gateway"
            echo -e "${BLUE}Viewing gateway logs...${NC}"
            ;;
        --nginx)
            service="nginx"
            echo -e "${BLUE}Viewing nginx logs...${NC}"
            ;;
        --provisioner)
            service="provisioner"
            echo -e "${BLUE}Viewing provisioner logs...${NC}"
            ;;
        "")
            echo -e "${BLUE}Viewing all logs...${NC}"
            ;;
        *)
            echo -e "${YELLOW}Unknown option: $1${NC}"
            echo "Usage: $0 logs [--frontend|--gateway|--nginx|--provisioner]"
            exit 1
            ;;
    esac
    
    cd "$DOCKER_DIR" && $COMPOSE_CMD logs -f $service
}

# Stop Docker development environment
stop() {
    # VASSILFLOW_ROOT is referenced in docker-compose-dev.yaml; set it before
    # running compose down to suppress "variable is not set" warnings.
    if [ -z "${VASSILFLOW_ROOT:-}" ]; then
        export VASSILFLOW_ROOT="$PROJECT_ROOT"
    fi
    if [ -z "${VASSILFLOW_RUNTIME_HOME:-}" ]; then
        export VASSILFLOW_RUNTIME_HOME
        VASSILFLOW_RUNTIME_HOME="$(default_runtime_home)"
    fi
    if [ -z "${VASSILFLOW_CONTAINER_HOME:-}" ]; then
        export VASSILFLOW_CONTAINER_HOME
        VASSILFLOW_CONTAINER_HOME="$(container_runtime_home_for "$VASSILFLOW_RUNTIME_HOME")"
    fi
    echo "Stopping Docker development services..."
    cd "$DOCKER_DIR" && $COMPOSE_CMD down --remove-orphans
    echo "Cleaning up sandbox containers..."
    "$SCRIPT_DIR/cleanup-containers.sh" "$SANDBOX_CONTAINER_PREFIX" 2>/dev/null || true
    echo -e "${GREEN}✓ Docker services stopped${NC}"
}

# Restart Docker development environment
restart() {
    echo "========================================"
    echo "  Restarting VassilFlow Docker Services"
    echo "========================================"
    echo ""
    echo -e "${BLUE}Restarting containers...${NC}"
    cd "$DOCKER_DIR" && $COMPOSE_CMD restart
    echo ""
    echo -e "${GREEN}✓ Docker services restarted${NC}"
    echo ""
    echo "  🌐 Application: http://localhost:2026"
    echo "  📋 View logs: make docker-logs"
    echo ""
}

# Show help
help() {
    echo "VassilFlow Docker Management Script"
    echo ""
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  init              - Pull the sandbox image (speeds up first Pod startup)"
    echo "  start             - Start Docker services (auto-detects sandbox mode from config.yaml)"
    echo "  restart           - Restart all running Docker services"
    echo "  logs [option] - View Docker development logs"
    echo "                  --frontend   View frontend logs only"
    echo "                  --gateway    View gateway logs only"
    echo "                  --nginx      View nginx logs only"
    echo "                  --provisioner View provisioner logs only"
    echo "  stop          - Stop Docker development services"
    echo "  help          - Show this help message"
    echo ""
}

main() {
    # Main command dispatcher
    case "$1" in
        init)
            init
            ;;
        start)
            shift
            start "$@"
            ;;
        restart)
            restart
            ;;
        logs)
            logs "$2"
            ;;
        stop)
            stop
            ;;
        help|--help|-h|"")
            help
            ;;
        *)
            echo -e "${YELLOW}Unknown command: $1${NC}"
            echo ""
            help
            exit 1
            ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
