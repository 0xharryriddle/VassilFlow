# VassilFlow Baseline Readiness

## Purpose

Before the first clean VassilFlow baseline commit, the DeerFlow-derived foundation should be proven runnable as-is. Rebranding should happen after this point, in separate commits, so a broken rename can be distinguished from an upstream foundation issue.

## Local Setup Completed

The following local-only files were generated for runtime verification and must remain uncommitted:

- `config.yaml`
- `.env`
- `frontend/.env`
- `extensions_config.json`
- `backend/.venv/`
- `frontend/node_modules/`
- `backend/.deer-flow/`
- `backend/.deer-flow/local-admin-credentials.txt`

The active local `config.yaml` was reduced from the full example into a minimal working configuration:

- LLM provider: `deerflow.models.openai_codex_provider:CodexChatModel`
- Model: `gpt-5.4`
- Auth source: local Codex CLI auth (`~/.codex/auth.json`)
- Web search: DuckDuckGo, no API key
- Web fetch: Jina AI Reader, no API key
- Image search: DuckDuckGo Images, no API key
- Sandbox: `deerflow.sandbox.local:LocalSandboxProvider`
- Host bash: disabled

This proves the gateway can load a real model provider without committing secret material.

The local `.env` files were also normalized:

- Root `.env` keeps only safe active defaults for tracing, docs, and frontend-to-gateway wiring.
- `frontend/.env` keeps only safe SSR gateway wiring.
- Root `.env` sets `CODEX_AUTH_PATH=/root/.codex/auth.json` for the Docker gateway when `docker-compose.cli-auth.yaml` mounts local Codex CLI auth.
- All LLM, search, channel, GitHub, and database secrets are commented out until intentionally enabled.
- No placeholder value such as `your-api-key` is active.

## Keys To Fill When Switching Providers

The current Codex CLI baseline does not require a direct LLM API key. It uses local Codex CLI auth.

Fill one of these only if you change `config.yaml` to that provider:

```text
OpenAI / OpenAI Responses API: OPENAI_API_KEY
Anthropic API key mode:        ANTHROPIC_API_KEY
Claude Code OAuth mode:        CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_AUTH_TOKEN
Google Gemini:                 GEMINI_API_KEY
DeepSeek:                      DEEPSEEK_API_KEY
Volcengine Doubao:             VOLCENGINE_API_KEY
Moonshot Kimi:                 MOONSHOT_API_KEY
OpenRouter:                    OPENROUTER_API_KEY
Novita:                        NOVITA_API_KEY
MiniMax:                       MINIMAX_API_KEY
StepFun:                       STEPFUN_API_KEY
Xiaomi MiMo:                   MIMO_API_KEY
vLLM local gateway:            VLLM_API_KEY if your gateway requires one
```

Optional web/search keys:

```text
Tavily:       TAVILY_API_KEY
Serper:       SERPER_API_KEY
Brave:        BRAVE_SEARCH_API_KEY
InfoQuest:    INFOQUEST_API_KEY
Exa:          EXA_API_KEY
Firecrawl:    FIRECRAWL_API_KEY
GroundRoute:  GROUNDROUTE_API_KEY
fastCRW:      CRW_API_KEY
Jina:         JINA_API_KEY, optional for the current Jina Reader setup
```

Optional integrations:

```text
GitHub MCP/tools:  GITHUB_TOKEN
Slack:             SLACK_BOT_TOKEN, SLACK_APP_TOKEN
Telegram:          TELEGRAM_BOT_TOKEN
Discord:           DISCORD_BOT_TOKEN
Feishu/Lark:       FEISHU_APP_ID, FEISHU_APP_SECRET
DingTalk:          DINGTALK_CLIENT_ID, DINGTALK_CLIENT_SECRET
WeCom:             WECOM_BOT_ID, WECOM_BOT_SECRET
Postgres:          DATABASE_URL
```

## Verified Commands

Backend dependencies:

```powershell
cd backend
uv sync
```

Result: completed successfully.

Frontend dependencies:

```powershell
cd frontend
pnpm.cmd install
```

Result: completed successfully.

Backend boundary smoke:

```powershell
cd backend
uv run pytest tests/test_harness_boundary.py tests/test_vassilflow_boundary_contract.py -q
```

Result: `5 passed, 1 warning`.

Frontend typecheck:

```powershell
cd frontend
pnpm.cmd typecheck
```

Result: completed successfully.

Local env verification:

```powershell
cd backend
$env:PYTHONIOENCODING='utf-8'
uv run python ../scripts/doctor.py
```

Result: model/config/auth checks passed; only `nginx` remained missing for full-stack local mode.

Gateway import smoke:

```powershell
cd backend
$env:PYTHONIOENCODING='utf-8'
uv run python -c "from app.gateway.app import app; print(app.title); print(len(app.routes))"
```

Result: gateway app imported; title was `DeerFlow API Gateway`; route count was `99`.

Gateway health smoke:

```powershell
cd backend
$env:PYTHONPATH='.'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONUTF8='1'
uv run uvicorn app.gateway.app:app --host 127.0.0.1 --port 8001
```

Then:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8001/health
```

Result: `200` with `{"status":"healthy","service":"deer-flow-gateway"}`.

Docker full-stack init:

```powershell
cmd /c scripts\run-with-git-bash.cmd ./scripts/docker.sh init
```

Result: completed successfully in local sandbox mode.

Docker full-stack start:

```powershell
cd docker
$env:DEER_FLOW_ROOT=(Resolve-Path ..).Path
$env:HOME=$HOME
docker compose -p deer-flow-dev -f docker-compose-dev.yaml -f docker-compose.cli-auth.yaml up --build -d --remove-orphans frontend gateway nginx
```

Result: `deer-flow-nginx`, `deer-flow-gateway`, and `deer-flow-frontend` are running.

Docker UI smoke:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri http://localhost:2026
Invoke-WebRequest -UseBasicParsing -Uri http://localhost:2026/health
```

Result: UI returned `200`; gateway health returned `200` with `{"status":"healthy","service":"deer-flow-gateway"}`.

Docker Codex auth smoke:

```powershell
docker exec deer-flow-gateway sh -lc 'test -f /root/.codex/auth.json && echo mounted || echo missing'
```

Result: `mounted`.

Local admin bootstrap:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri http://localhost:2026/api/v1/auth/setup-status
Invoke-WebRequest -UseBasicParsing -Uri http://localhost:2026/api/v1/auth/login/local -Method Post
Invoke-WebRequest -UseBasicParsing -Uri http://localhost:2026/api/models
```

Result: setup status is `{"needs_setup":false}`; local login returned `200`; authenticated `/api/models` returned `200` and listed the Codex CLI model.

Local dev admin credentials are stored in the ignored file:

```text
backend/.deer-flow/local-admin-credentials.txt
```

Agent API smoke:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri http://localhost:2026/api/runs/wait -Method Post
```

Request shape:

```json
{
  "assistant_id": "lead_agent",
  "input": {
    "messages": [
      {
        "role": "user",
        "content": "Reply with exactly OK. Do not use tools."
      }
    ]
  },
  "context": {
    "thinking_enabled": false,
    "subagent_enabled": false
  },
  "stream_mode": ["values"]
}
```

Result: authenticated request with `X-CSRF-Token` returned `200`; the final AI message content was `OK`; model metadata reported `gpt-5.4`.

Browser UI smoke:

```text
http://localhost:2026/workspace/chats/new
```

Result: Chrome headless loaded the login page, submitted the local admin form, reached `/workspace/chats/new`, sent a prompt through the visible chat composer, created a LangGraph thread, opened `/runs/stream`, and received the final assistant message `UI_DONE_260626`.

## Current Doctor Status

`doctor` passes all model/config/auth checks with the Codex CLI provider, but host-native full-stack mode still reports one system dependency error:

```text
nginx not found
```

This matters only for host-native `make dev`, because local full-stack startup uses Nginx as the reverse proxy on port `2026`. Docker full-stack mode is now verified and does not depend on host `nginx`.

## Remaining Before Full UI Baseline

The Docker path is the current verified baseline:

1. Open `http://localhost:2026`.
2. Log in with the local admin credentials in `backend/.deer-flow/local-admin-credentials.txt`.
3. Optionally repeat one basic agent request from the UI if you want a manual look before the clean baseline commit.

The host-native path remains optional:

1. Install or expose `nginx` on PATH.
2. Run `make doctor` until it is clean.
3. Run `make dev`.
4. Verify `http://localhost:2026`.

Backend-only has already been verified through `http://127.0.0.1:8001/health`.

## Rebranding Order

Do not rename everything at once. The safe order is:

1. Commit the runnable DeerFlow-derived foundation with VassilFlow research, plans, and contracts.
2. Add `vassilflow` facade modules and contract tests while leaving DeerFlow internals intact.
3. Add environment/config aliases such as `VASSILFLOW_*` while keeping `DEER_FLOW_*` backward-compatible.
4. Rename visible product strings in docs/UI.
5. Rename internal Python package/module paths only after compatibility tests cover imports, config loading, tools, sandbox providers, and gateway startup.
6. Rename repository-level scripts/workspace files last.

Package/module renames are high-risk because `config.yaml`, tool provider paths, tests, frontend API clients, Docker scripts, and persisted state all reference `deerflow` names today.
