#!/usr/bin/env bash
#
# Copy legacy VassilFlow runtime state from backend/.deer-flow to
# backend/.vassilflow without overwriting an existing target.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SOURCE="$REPO_ROOT/backend/.deer-flow"
TARGET="$REPO_ROOT/backend/.vassilflow"
DRY_RUN=false
QUIET=false

usage() {
    cat <<'EOF'
Usage: migrate-runtime-home.sh [options]

Options:
  --source PATH   Legacy runtime directory to copy from
  --target PATH   VassilFlow runtime directory to copy to
  --dry-run       Print the action without copying
  --quiet         Suppress non-error output
  -h, --help      Show this help
EOF
}

log() {
    if ! $QUIET; then
        printf '%s\n' "$*"
    fi
}

is_empty_dir() {
    [ -d "$1" ] && [ -z "$(find "$1" -mindepth 1 -maxdepth 1 -print -quit)" ]
}

while [ $# -gt 0 ]; do
    case "$1" in
        --source)
            [ -n "${2:-}" ] || { echo "Missing value for --source" >&2; exit 1; }
            SOURCE="$2"
            shift 2
            ;;
        --target)
            [ -n "${2:-}" ] || { echo "Missing value for --target" >&2; exit 1; }
            TARGET="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --quiet)
            QUIET=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [ ! -d "$SOURCE" ]; then
    log "No legacy runtime home found at $SOURCE."
    exit 0
fi

if [ -e "$TARGET" ] && [ ! -d "$TARGET" ]; then
    echo "Target runtime path exists but is not a directory: $TARGET" >&2
    exit 1
fi

if [ -d "$TARGET" ] && ! is_empty_dir "$TARGET"; then
    log "VassilFlow runtime home already has data at $TARGET; leaving legacy data untouched."
    exit 0
fi

if $DRY_RUN; then
    log "Would copy legacy runtime home:"
    log "  from: $SOURCE"
    log "  to:   $TARGET"
    exit 0
fi

mkdir -p "$TARGET"
cp -a "$SOURCE"/. "$TARGET"/
log "Copied legacy runtime home:"
log "  from: $SOURCE"
log "  to:   $TARGET"
