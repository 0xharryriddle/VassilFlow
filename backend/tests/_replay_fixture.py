"""Shared config + gateway-drive helpers for the record/replay e2e.

Record (``scripts/record_gateway.py`` + ``scripts/build_fixture_from_jsonl.py``)
and replay (``tests/test_replay_golden.py``)
MUST drive the gateway through an identical, prompt-affecting config — otherwise
the system prompt differs and the recorded input hashes never match on replay.
Centralising the config builder + drive loop here makes that identity hold by
construction; only the ``models[].use`` block differs (real model vs
``ReplayChatModel``).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

# mode -> (thinking_enabled, is_plan_mode, subagent_enabled). Mirrors the
# frontend mapping in core/threads/hooks.ts.
MODE_CONTEXT: dict[str, tuple[bool, bool, bool]] = {
    "flash": (False, False, False),
    "thinking": (True, False, False),
    "pro": (True, True, False),
    # thinking_enabled mirrors the frontend `context.mode !== "flash"` (hooks.ts),
    # so ultra is thinking-enabled too.
    "ultra": (True, True, True),
}

# The replay model block: same model NAME as recording (so nothing in the prompt
# shifts), only ``use`` swapped to the deterministic replay provider.
REPLAY_MODEL_BLOCK = """\
  - name: scenario-model
    display_name: Scenario Model
    use: replay_provider:ReplayChatModel
    model: replay
    supports_thinking: true"""


def real_model_block(model: str) -> str:
    return f"""\
  - name: scenario-model
    display_name: Scenario Model
    use: langchain_openai:ChatOpenAI
    model: {model}
    api_key: $OPENAI_API_KEY
    base_url: $OPENAI_API_BASE"""


def build_config_yaml(
    *,
    model_block: str,
    home: Path,
    skills_path: Path | None = None,
    title_enabled: bool = True,
    suggestions_enabled: bool = True,
) -> str:
    """Full gateway config. Only ``model_block`` varies between record/replay.

    Everything that shapes the system prompt is pinned so record, replay, and CI
    produce byte-identical prompts regardless of the machine:
    - sandbox / tool_groups / tools — fixed here
    - skills — pointed at an empty ``<home>/skills`` so filesystem skills (incl.
      gitignored custom skills present only on a dev box) never leak into the
      prompt. Pair with an empty ``extensions_config.json`` (no MCP) via
      :func:`prepare_hermetic_extras`.
    - memory / summarization — disabled (background, non-deterministic timing)
    """
    resolved_skills_path = skills_path or (home / "skills")
    suggestions = (
        ""
        if suggestions_enabled
        else """\
suggestions:
  enabled: false
"""
    )
    return f"""\
log_level: warning
models:
{model_block}
sandbox:
  use: vassilflow.sandbox.local:LocalSandboxProvider
skills:
  path: {resolved_skills_path}
  container_path: /mnt/skills
tool_groups:
  - name: file:read
  - name: file:write
tools:
  - name: ls
    group: file:read
    use: vassilflow.sandbox.tools:ls_tool
  - name: read_file
    group: file:read
    use: vassilflow.sandbox.tools:read_file_tool
  - name: write_file
    group: file:write
    use: vassilflow.sandbox.tools:write_file_tool
# Memory + summarization make background / debounced model calls whose timing is
# non-deterministic; disable them so record and replay see the same model-call
# set. (Title stays — it is an in-graph, deterministic call we record.)
title:
  enabled: {str(title_enabled).lower()}
  model_name: scenario-model
{suggestions.rstrip()}
memory:
  enabled: false
  injection_enabled: false
summarization:
  enabled: false
agents_api:
  enabled: true
database:
  backend: sqlite
  sqlite_dir: {home / "db"}
"""


def prepare_hermetic_extras(home: Path) -> Path:
    """Create the empty skills tree + an empty extensions_config.json so the
    system prompt has no environment-dependent skills/MCP content.

    Returns the extensions-config path; the caller must point
    ``VASSILFLOW_EXTENSIONS_CONFIG_PATH`` at it. Call before starting the gateway.
    """
    (home / "skills" / "public").mkdir(parents=True, exist_ok=True)
    (home / "skills" / "custom").mkdir(parents=True, exist_ok=True)
    extensions = home / "extensions_config.json"
    extensions.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    return extensions


def sse_event_shapes(
    resp,
    *,
    on_event: Callable[[str | None, Any], None] | None = None,
) -> list[dict]:
    """Reduce an SSE stream to (event name, sorted top-level data keys).

    Snapshots the *shape* of the stream, not volatile values, so the golden is
    stable across runs while still catching event-sequence / payload-shape drift.
    """
    events: list[dict] = []
    current: str | None = None
    for line in resp.iter_lines():
        if line.startswith("event:"):
            current = line[len("event:") :].strip()
        elif line.startswith("data:"):
            raw = line[len("data:") :].strip()
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = {"_raw": raw[:200]}
            if on_event is not None:
                on_event(current, data)
            events.append({"event": current, "keys": sorted(data.keys()) if isinstance(data, dict) else None})
    return events


def drive_gateway(
    app,
    *,
    prompt: str,
    context: dict,
    assistant_id: str = "lead_agent",
    on_event: Callable[[str | None, Any], None] | None = None,
    on_thread_created: Callable[[str], None] | None = None,
    client: Any | None = None,
) -> list[dict]:
    """Register -> create thread -> POST /runs/stream; return SSE event shapes.

    This is the exact wire path the React frontend uses (LangGraph SDK), driven
    in-process via Starlette's TestClient with the real auth flow.
    """
    if client is None:
        from starlette.testclient import TestClient

        with TestClient(app) as owned_client:
            return _drive_gateway_with_client(
                owned_client,
                prompt=prompt,
                context=context,
                assistant_id=assistant_id,
                on_event=on_event,
                on_thread_created=on_thread_created,
            )
    return _drive_gateway_with_client(
        client,
        prompt=prompt,
        context=context,
        assistant_id=assistant_id,
        on_event=on_event,
        on_thread_created=on_thread_created,
    )


def _drive_gateway_with_client(
    client: Any,
    *,
    prompt: str,
    context: dict,
    assistant_id: str,
    on_event: Callable[[str | None, Any], None] | None,
    on_thread_created: Callable[[str], None] | None,
) -> list[dict]:
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": f"e2e-{uuid.uuid4().hex[:8]}@example.com", "password": "very-strong-password-123"},
    )
    assert reg.status_code == 201, reg.text
    csrf = client.cookies.get("csrf_token")
    assert csrf, "register must set csrf_token cookie"

    thread_id = str(uuid.uuid4())
    create_body: dict[str, Any] = {"thread_id": thread_id, "metadata": {}}
    if assistant_id != "lead_agent":
        create_body["assistant_id"] = assistant_id
    created = client.post(
        "/api/threads",
        json=create_body,
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 200, created.text
    if on_thread_created is not None:
        on_thread_created(thread_id)

    body = {
        "assistant_id": assistant_id,
        "input": {"messages": [{"role": "user", "content": prompt}]},
        "config": {"recursion_limit": 50},
        "context": context,
        "stream_mode": ["values"],
    }
    with client.stream(
        "POST",
        f"/api/threads/{thread_id}/runs/stream",
        json=body,
        headers={"X-CSRF-Token": csrf},
    ) as resp:
        assert resp.status_code == 200, resp.read().decode()
        return sse_event_shapes(resp, on_event=on_event)
