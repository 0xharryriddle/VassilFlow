"""Environment-variable policy for sandbox command execution."""

from __future__ import annotations

import fnmatch
import os

# Case-insensitive wildcard patterns for secret-looking variable names. Benign
# system vars such as PATH, HOME, SHELL, LANG, PWD, TMPDIR, VIRTUAL_ENV, and
# PYTHONPATH contain none of these tokens and are preserved.
_SECRET_NAME_PATTERNS: tuple[str, ...] = (
    "*KEY*",
    "*SECRET*",
    "*TOKEN*",
    "*PASSWORD*",
    "*PASSWD*",
    "*CREDENTIAL*",
    "*DSN*",
)

_BLOCKED_EXACT_NAMES: frozenset[str] = frozenset(
    {
        "DATABASE_URL",
        "DATABASE_URI",
        "REDIS_URL",
        "MONGODB_URI",
        "MONGO_URL",
        "AMQP_URL",
        "RABBITMQ_URL",
        "POSTGRES_URL",
        "POSTGRESQL_URL",
        "MYSQL_URL",
        "CLICKHOUSE_URL",
        "CONNECTION_STRING",
        "CONN_STR",
        "GH_PAT",
        "GITHUB_PAT",
    }
)


def is_blocked_env_name(name: str) -> bool:
    """Return True when ``name`` looks like a credential."""
    upper = name.upper()
    if upper in _BLOCKED_EXACT_NAMES:
        return True
    return any(fnmatch.fnmatchcase(upper, pattern) for pattern in _SECRET_NAME_PATTERNS)


def build_sandbox_env(injected: dict[str, str] | None = None) -> dict[str, str]:
    """Build a subprocess environment with host credentials scrubbed."""
    env = {key: value for key, value in os.environ.items() if not is_blocked_env_name(key)}
    if injected:
        env.update(injected)
    return env
