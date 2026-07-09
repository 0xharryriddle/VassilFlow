# VassilFlow Setup Guide

This guide is for a fresh clone on a new machine. It covers the tools you need,
the files that must be created locally, and the commands to start VassilFlow.

## 1. Install Prerequisites

Required for every setup:

- Git
- GNU Make
- Python 3.12 or newer
- uv
- Node.js 22 or newer
- pnpm 10.26.2 or newer

Recommended:

- Docker Desktop or Docker Engine, especially for first-time setup and safer
  sandbox execution
- nginx, only if you run the non-Docker local service stack
- Git Bash on Windows for local development commands

Useful checks:

```bash
python --version
uv --version
node --version
pnpm --version
make --version
docker --version
```

If pnpm is missing but Node.js includes Corepack:

```bash
corepack enable
corepack prepare pnpm@10.26.2 --activate
```

If `make` is missing on Windows, install GNU Make through a package manager
such as Chocolatey, Scoop, MSYS2, or your normal developer toolchain. You can
also use the direct script fallbacks in [Without GNU Make](#6-without-gnu-make).

## 2. Clone the Repository

```bash
git clone https://github.com/linhlln1104/VassilFlow.git
cd VassilFlow
```

Run the dependency check before installing project packages:

```bash
make check
```

`make check` verifies Node.js, pnpm, uv, and nginx. If you plan to run only the
Docker stack, nginx on the host is less important, but the local stack needs it.

Without Make:

```bash
python scripts/check.py
```

## 3. Create Local Configuration

Use the interactive wizard on a new machine:

```bash
make setup
```

Without Make:

```bash
cd backend
uv run python ../scripts/setup_wizard.py
cd ..
```

The wizard creates or updates:

- `config.yaml`: local runtime configuration, ignored by git
- `.env`: local secrets and environment values, ignored by git
- `frontend/.env`: frontend-local environment file, ignored by git

You need one working model provider before real agent runs can complete. The
wizard can write API keys for hosted providers into `.env`, or you can configure
CLI-backed providers such as Codex CLI or Claude Code if you already have their
local auth set up.

Optional web tools need their own keys only when enabled:

- `SERPER_API_KEY` for Serper search/image search
- `TAVILY_API_KEY` for Tavily search
- `JINA_API_KEY` for Jina fetch
- `INFOQUEST_API_KEY` for InfoQuest tools
- `FIRECRAWL_API_KEY` for Firecrawl

Verify the result:

```bash
make doctor
```

Without Make:

```bash
cd backend
uv run python ../scripts/doctor.py
cd ..
```

If you prefer manual configuration, copy the reference files and edit them:

```bash
cp .env.example .env
cp frontend/.env.example frontend/.env
cp config.example.yaml config.yaml
```

Then edit `config.yaml` and uncomment only the environment variables you use in
`.env`. `config.example.yaml` is a full reference; the wizard-generated
`config.yaml` is intentionally smaller.

## 4. Choose a Run Mode

### Docker Development, Recommended

This is the easiest path on a new machine because dependencies run in
containers and the sandbox image is handled explicitly.

```bash
make docker-init
make docker-start
```

Without Make:

```bash
bash ./scripts/docker.sh init
bash ./scripts/docker.sh start
```

Open:

```text
http://localhost:2026
```

Stop:

```bash
make docker-stop
```

Without Make:

```bash
bash ./scripts/docker.sh stop
```

Logs:

```bash
make docker-logs
make docker-logs-gateway
make docker-logs-frontend
```

### Local Development

Use this when you want hot reload directly on the host.

```bash
make install
make dev
```

Without Make:

```bash
cd backend
uv sync
cd ../frontend
pnpm install
cd ..
bash ./scripts/serve.sh --dev
```

Open:

```text
http://localhost:2026
```

Stop:

```bash
make stop
```

Without Make:

```bash
bash ./scripts/serve.sh --stop
```

On Windows, run these commands from Git Bash. The service scripts are
bash-based.

### Production Docker

For a persistent single-machine deployment:

```bash
make up
```

Without Make:

```bash
bash ./scripts/deploy.sh
```

Open:

```text
http://localhost:2026
```

Stop:

```bash
make down
```

Without Make:

```bash
bash ./scripts/deploy.sh down
```

## 5. Validate a Fresh Machine

After startup, confirm the basics:

1. Open `http://localhost:2026`.
2. Start a new chat.
3. Send a short prompt such as `Say hello and tell me which model is active.`
4. If search is configured, ask a simple web question.
5. If file tools are enabled, ask the agent to create a small text file and
   inspect the workspace change panel.

From the terminal, you can also run:

```bash
make doctor
```

When reporting a setup problem, generate a redacted bundle:

```bash
make support-bundle
```

The bundle is written under `.vassilflow/support-bundles/`.

## 6. Without GNU Make

GNU Make is the recommended command surface because it keeps setup commands
short and consistent. If a new machine does not have `make`, use these direct
commands from the repository root.

| Make command | Direct command |
| --- | --- |
| `make check` | `python scripts/check.py` |
| `make setup` | `cd backend && uv run python ../scripts/setup_wizard.py` |
| `make doctor` | `cd backend && uv run python ../scripts/doctor.py` |
| `make install` | `cd backend && uv sync`, then `cd ../frontend && pnpm install` |
| `make dev` | `bash ./scripts/serve.sh --dev` |
| `make stop` | `bash ./scripts/serve.sh --stop` |
| `make docker-init` | `bash ./scripts/docker.sh init` |
| `make docker-start` | `bash ./scripts/docker.sh start` |
| `make docker-stop` | `bash ./scripts/docker.sh stop` |
| `make up` | `bash ./scripts/deploy.sh` |
| `make down` | `bash ./scripts/deploy.sh down` |

On Windows, run the bash commands from Git Bash.

## 7. Local Files and State

These files are intentionally local and ignored by git:

- `.env`
- `frontend/.env`
- `config.yaml`
- `.vassilflow/`
- runtime databases such as `vassilflow.db`

Runtime path overrides:

- `VASSILFLOW_PROJECT_ROOT`: project root when starting from another directory
- `VASSILFLOW_CONFIG_PATH`: explicit config file path
- `VASSILFLOW_HOME`: runtime state directory
- `VASSILFLOW_SKILLS_PATH`: skills directory
- `VASSILFLOW_EXTENSIONS_CONFIG_PATH`: extensions config path

## 8. Common Fixes

`make check` says pnpm is missing:

```bash
corepack enable
corepack prepare pnpm@10.26.2 --activate
```

Docker cannot access the Docker daemon on Linux:

```bash
sudo usermod -aG docker "$USER"
```

Then log out and back in before retrying.

The app starts but the agent cannot answer:

- Run `make doctor`.
- Check that `config.yaml` has at least one model entry.
- Check that the matching API key exists in `.env` or in your shell.
- If using a CLI-backed provider, confirm that the CLI works outside
  VassilFlow first.

Search tools fail:

- Confirm the selected search/fetch tool is enabled in `config.yaml`.
- Confirm its API key is present in `.env`.
- Restart the service after changing `.env`.

Config file not found:

- Keep `config.yaml` in the repository root.
- Or set `VASSILFLOW_CONFIG_PATH` to the exact file path.
- Or set `VASSILFLOW_PROJECT_ROOT` before starting services.

## 9. Next Documents

- [README.md](../README.md): product overview and run modes
- [backend/docs/CONFIGURATION.md](../backend/docs/CONFIGURATION.md): full configuration reference
- [backend/docs/MCP_SERVER.md](../backend/docs/MCP_SERVER.md): MCP server setup
- [backend/docs/IM_CHANNEL_CONNECTIONS.md](../backend/docs/IM_CHANNEL_CONNECTIONS.md): messaging app connections
- [CONTRIBUTING.md](../CONTRIBUTING.md): development workflow
