"""Request-scoped secret carrier for agent runs."""

from __future__ import annotations

from typing import Any

# Reserved sub-key of RunnableConfig.context that holds caller-provided
# per-request secrets. Values under this key are never prompt material.
SECRETS_CONTEXT_KEY = "secrets"

# Reserved sub-key holding the secrets resolved for the currently activated
# skill. Skill activation writes it; sandbox tools read it.
ACTIVE_SECRETS_CONTEXT_KEY = "__active_skill_secrets"

_SLASH_SECRET_SOURCE_KEY = "__slash_skill_secret_source"
_SECRETS_BINDING_AUDIT_KEY = "__skill_secrets_binding_audit"

REDACTED_CONTEXT_KEYS = frozenset(
    {
        SECRETS_CONTEXT_KEY,
        ACTIVE_SECRETS_CONTEXT_KEY,
        _SLASH_SECRET_SOURCE_KEY,
        _SECRETS_BINDING_AUDIT_KEY,
    }
)


def _string_pairs(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if isinstance(key, str) and isinstance(value, str)}


def extract_request_secrets(context: Any) -> dict[str, str]:
    """Return caller-supplied request secrets from a run context."""
    if not isinstance(context, dict):
        return {}
    return _string_pairs(context.get(SECRETS_CONTEXT_KEY))


def read_active_secrets(context: Any) -> dict[str, str]:
    """Return the secrets resolved for the currently active skill."""
    if not isinstance(context, dict):
        return {}
    return _string_pairs(context.get(ACTIVE_SECRETS_CONTEXT_KEY))


def redact_secret_context_keys(context: Any) -> Any:
    """Return a shallow context copy with secret-bearing keys removed."""
    if not isinstance(context, dict):
        return context
    return {key: value for key, value in context.items() if key not in REDACTED_CONTEXT_KEYS}


def redact_config_secrets(config: Any) -> Any:
    """Return a run config safe to persist or echo back to clients."""
    if not isinstance(config, dict):
        return config
    context = config.get("context")
    if not isinstance(context, dict):
        return config
    redacted = dict(config)
    redacted["context"] = redact_secret_context_keys(context)
    return redacted
