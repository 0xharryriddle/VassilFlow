# Apple Container Support

VassilFlow supports Apple Container as the preferred container runtime on macOS, with automatic fallback to Docker.

## Overview

VassilFlow automatically detects and uses Apple Container on macOS when available, falling back to Docker when:
- Apple Container is not installed
- Running on non-macOS platforms

This provides better performance on Apple Silicon Macs while maintaining compatibility across all platforms.

## Benefits

### On Apple Silicon Macs with Apple Container:
- **Better Performance**: Native ARM64 execution without Rosetta 2 translation
- **Lower Resource Usage**: Lighter weight than Docker Desktop
- **Native Integration**: Uses macOS Virtualization.framework

### Fallback to Docker:
- Full backward compatibility
- Works on all platforms (macOS, Linux, Windows)
- No configuration changes needed

## Requirements

### For Apple Container (macOS only):
- macOS 15.0 or later
- Apple Silicon (M1/M2/M3/M4)
- Apple Container CLI installed

### Installation:
```bash
# Download from GitHub releases
# https://github.com/apple/container/releases

# Verify installation
container --version

# Start the service
container system start
```

### For Docker (all platforms):
- Docker Desktop or Docker Engine

## How It Works

### Automatic Detection

The `AioSandboxProvider` automatically detects the available container runtime:

1. On macOS: Try `container --version`
   - Success → Use Apple Container
   - Failure → Fall back to Docker

2. On other platforms: Use Docker directly

### Runtime Differences

Both runtimes use nearly identical command syntax:

**Container Startup:**
```bash
# Apple Container
container run --rm -d -p 8080:8080 -v /host:/container -e KEY=value image

# Docker
docker run --rm -d -p 8080:8080 -v /host:/container -e KEY=value image
```

**Container Cleanup:**
```bash
# Apple Container (with --rm flag)
container stop <id>  # Auto-removes due to --rm

# Docker (with --rm flag)
docker stop <id>     # Auto-removes due to --rm
```

### Implementation Details

The public VassilFlow import is `vassilflow.community.aio_sandbox:AioSandboxProvider`; the implementation lives in `backend/packages/harness/vassilflow/community/aio_sandbox/aio_sandbox_provider.py`:

- `_detect_container_runtime()`: Detects available runtime at startup
- `_start_container()`: Uses detected runtime, skips Docker-specific options for Apple Container
- `_stop_container()`: Uses appropriate stop command for the runtime

## Configuration

No configuration changes are needed! The system works automatically.

However, you can verify the runtime in use by checking the logs:

```
INFO:vassilflow.community.aio_sandbox.aio_sandbox_provider:Detected Apple Container: container version 0.1.0
INFO:vassilflow.community.aio_sandbox.aio_sandbox_provider:Starting sandbox container using container: ...
```

Or for Docker:
```
INFO:vassilflow.community.aio_sandbox.aio_sandbox_provider:Apple Container not available, falling back to Docker
INFO:vassilflow.community.aio_sandbox.aio_sandbox_provider:Starting sandbox container using docker: ...
```

## Container Images

Both runtimes use OCI-compatible images. The default image works with both:

```yaml
sandbox:
  use: vassilflow.community.aio_sandbox:AioSandboxProvider
  image: enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest  # Default image
```

Make sure your images are available for the appropriate architecture:
- ARM64 for Apple Container on Apple Silicon
- AMD64 for Docker on Intel Macs
- Multi-arch images work on both

### Pre-pulling Images (Recommended)

**Important**: Container images are typically large (500MB+) and are pulled on first use, which can cause a long wait time without clear feedback.

**Best Practice**: Pre-pull the image during setup:

```bash
# From project root
make setup-sandbox
```

This command will:
1. Read the configured image from `config.yaml` (or use default)
2. Detect available runtime (Apple Container or Docker)
3. Pull the image with progress indication
4. Verify the image is ready for use

**Manual pre-pull**:

```bash
# Using Apple Container
container image pull enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest

# Using Docker
docker pull enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest
```

If you skip pre-pulling, the image will be automatically pulled on first agent execution, which may take several minutes depending on your network speed.

## Cleanup Scripts

The project includes a unified cleanup script that handles both runtimes:

**Script:** `scripts/cleanup-containers.sh`

**Usage:**
```bash
# Clean up all VassilFlow sandbox containers
./scripts/cleanup-containers.sh vassilflow-sandbox

# Legacy transition prefix, if old containers are still running
./scripts/cleanup-containers.sh deer-flow-sandbox

# Custom prefix
./scripts/cleanup-containers.sh my-prefix
```

**Makefile Integration:**

All cleanup commands in `Makefile` automatically handle both runtimes:
```bash
make stop   # Stops all services and cleans up containers
make clean  # Full cleanup including logs
```

## Testing

Test the container runtime detection:

```bash
# User-facing runtime check: detects the runtime and pre-pulls the image.
make setup-sandbox

# Maintainer regression tests.
cd backend
uv run python -m pytest tests/test_aio_sandbox_provider.py tests/test_docker_sandbox_mode_detection.py -q
```

These checks will:
1. Detect the available runtime
2. Pull or validate the configured sandbox image
3. Verify provider and Docker-mode detection logic

## Troubleshooting

### Apple Container not detected on macOS

1. Check if installed:
   ```bash
   which container
   container --version
   ```

2. Check if service is running:
   ```bash
   container system start
   ```

3. Check logs for detection:
   ```bash
   # Look for detection message in application logs
   grep "container runtime" logs/*.log
   ```

### Containers not cleaning up

1. Manually check running containers:
   ```bash
   # Apple Container
   container list

   # Docker
   docker ps
   ```

2. Run cleanup script manually:
   ```bash
   ./scripts/cleanup-containers.sh vassilflow-sandbox
   ./scripts/cleanup-containers.sh deer-flow-sandbox  # legacy transition prefix
   ```

### Performance issues

- Apple Container should be faster on Apple Silicon
- If experiencing issues, you can force Docker by temporarily renaming the `container` command:
   ```bash
   # Temporary workaround - not recommended for permanent use
   sudo mv /opt/homebrew/bin/container /opt/homebrew/bin/container.bak
   ```

## References

- [Apple Container GitHub](https://github.com/apple/container)
- [Apple Container Documentation](https://github.com/apple/container/blob/main/docs/)
- [OCI Image Spec](https://github.com/opencontainers/image-spec)
