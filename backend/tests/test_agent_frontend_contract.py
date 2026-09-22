"""Cross-tier contract checks for server-owned Agent product metadata."""

from __future__ import annotations

import json
import re
from pathlib import Path

from vassilflow.config.builtin_agents import list_builtin_agents


def test_builtin_chat_extensions_have_frontend_registrations() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    manifest_path = repository_root / "frontend" / "src" / "components" / "workspace" / "agents" / "agent-chat-extensions.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert isinstance(manifest, list)
    assert all(isinstance(key, str) and re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", key) for key in manifest)
    assert len(manifest) == len(set(manifest))

    registered = set(manifest)
    missing = {definition.chat_extension for definition in list_builtin_agents() if definition.chat_extension is not None and definition.chat_extension not in registered}
    assert not missing
