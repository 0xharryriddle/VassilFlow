# Backend Setup Notes

For a fresh clone or full-stack setup, start with the repository-level guide:

- [../../docs/SETUP.md](../../docs/SETUP.md)

This page only covers backend-specific checks after the root setup is complete.

## Backend Configuration Location

The backend expects `config.yaml` in the repository root by default:

```text
VassilFlow/config.yaml
```

You can override that location with:

- `VASSILFLOW_PROJECT_ROOT`: points to the repository root
- `VASSILFLOW_CONFIG_PATH`: points to one exact config file
- `VASSILFLOW_HOME`: moves runtime state away from `.vassilflow/`
- `VASSILFLOW_SKILLS_PATH`: moves the skills directory

All VassilFlow-owned environment variables use the `VASSILFLOW_*` namespace.

- **Runtime variables**: Use `VASSILFLOW_*` variables.
- **Runtime data**: State defaults to `.vassilflow` under the project root.

`config.yaml`, `.env`, and runtime state are local files and should not be
committed.

## Backend-Only Install

From the repository root:

```bash
cd backend
make install
```

Run only the Gateway API:

```bash
cd backend
make dev
```

Direct Gateway URL:

```text
http://localhost:8001
```

The normal product entrypoint is still the root command:

```bash
make dev
```

That starts Gateway, frontend, and nginx together at `http://localhost:2026`.

## Backend Config Smoke Test

After `make setup`, run:

```bash
cd backend
uv run python -c "from vassilflow.config import get_app_config; print(get_app_config().models[0].name)"
```

If this fails, run from the repository root:

```bash
make doctor
```

## Sandbox Image

If `config.yaml` uses the container sandbox provider, pre-pull the sandbox image
from the repository root:

```bash
make setup-sandbox
```

Skipping this is allowed, but the first agent run may pause while Docker pulls
the image.

## See Also

- [Configuration Guide](CONFIGURATION.md)
- [Architecture Overview](ARCHITECTURE.md)
- [API Reference](API.md)
