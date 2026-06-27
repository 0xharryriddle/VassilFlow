"""Unified database backend configuration.

Controls BOTH the LangGraph checkpointer and the VassilFlow application
persistence layer (runs, threads metadata, users, etc.). The user
configures one backend; the system handles physical separation details.

SQLite mode: checkpointer and app share a single .db file
({sqlite_dir}/vassilflow.db for new installs, preserving an existing
{sqlite_dir}/deerflow.db during migration) with WAL journal mode enabled on
every connection. WAL allows concurrent readers and a single writer without
blocking, making a unified file safe for both workloads. Writers
that contend for the lock wait via the default 5-second sqlite3
busy timeout rather than failing immediately.

Postgres mode: both use the same database URL but maintain independent
connection pools with different lifecycles.

Memory mode: checkpointer uses MemorySaver, app uses in-memory stores.
No database is initialized.

Sensitive values (postgres_url) should use $VAR syntax in config.yaml
to reference environment variables from .env:

    database:
      backend: postgres
      postgres_url: $DATABASE_URL

The $VAR resolution is handled by AppConfig.resolve_env_variables()
before this config is instantiated -- DatabaseConfig itself does not
need to do any environment variable processing.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field

from vassilflow.config.runtime_paths import DEFAULT_RUNTIME_HOME_NAME, LEGACY_RUNTIME_HOME_NAME, project_root

DEFAULT_SQLITE_DIR = f"{DEFAULT_RUNTIME_HOME_NAME}/data"
LEGACY_SQLITE_DIR = f"{LEGACY_RUNTIME_HOME_NAME}/data"
DEFAULT_SQLITE_FILENAME = "vassilflow.db"
LEGACY_SQLITE_FILENAME = "deerflow.db"


def default_sqlite_dir() -> str:
    """Return the default SQLite directory, preserving existing legacy state."""
    root = project_root()
    current_home = root / DEFAULT_RUNTIME_HOME_NAME
    legacy_home = root / LEGACY_RUNTIME_HOME_NAME

    if current_home.exists():
        return DEFAULT_SQLITE_DIR
    if legacy_home.exists():
        return LEGACY_SQLITE_DIR
    return DEFAULT_SQLITE_DIR


class DatabaseConfig(BaseModel):
    backend: Literal["memory", "sqlite", "postgres"] = Field(
        default="memory",
        description=("Storage backend for both checkpointer and application data. 'memory' for development (no persistence across restarts), 'sqlite' for single-node deployment, 'postgres' for production multi-node deployment."),
    )
    sqlite_dir: str = Field(
        default_factory=default_sqlite_dir,
        description=(
            "Directory for the SQLite database file. Both checkpointer and "
            "application data share {sqlite_dir}/vassilflow.db; an existing "
            "{sqlite_dir}/deerflow.db is preserved during migration when "
            "vassilflow.db is absent."
        ),
    )
    postgres_url: str = Field(
        default="",
        description=(
            "PostgreSQL connection URL, shared by checkpointer and app. "
            "Use $DATABASE_URL in config.yaml to reference .env. "
            "Example: postgresql://user:pass@host:5432/vassilflow "
            "(the +asyncpg driver suffix is added automatically where needed)."
        ),
    )
    echo_sql: bool = Field(
        default=False,
        description="Echo all SQL statements to log (debug only).",
    )
    pool_size: int = Field(
        default=5,
        description="Connection pool size for the app ORM engine (postgres only).",
    )

    # -- Derived helpers (not user-configured) --

    @property
    def _resolved_sqlite_dir(self) -> str:
        """Resolve sqlite_dir to an absolute path (relative to CWD)."""
        from pathlib import Path

        return str(Path(self.sqlite_dir).resolve())

    @property
    def sqlite_path(self) -> str:
        """Unified SQLite file path shared by checkpointer and app."""
        current_path = os.path.join(self._resolved_sqlite_dir, DEFAULT_SQLITE_FILENAME)
        legacy_path = os.path.join(self._resolved_sqlite_dir, LEGACY_SQLITE_FILENAME)
        if not os.path.exists(current_path) and os.path.exists(legacy_path):
            return legacy_path
        return current_path

    # Backward-compatible aliases
    @property
    def checkpointer_sqlite_path(self) -> str:
        """SQLite file path for the LangGraph checkpointer (alias for sqlite_path)."""
        return self.sqlite_path

    @property
    def app_sqlite_path(self) -> str:
        """SQLite file path for application ORM data (alias for sqlite_path)."""
        return self.sqlite_path

    @property
    def app_sqlalchemy_url(self) -> str:
        """SQLAlchemy async URL for the application ORM engine."""
        if self.backend == "sqlite":
            return f"sqlite+aiosqlite:///{self.sqlite_path}"
        if self.backend == "postgres":
            url = self.postgres_url
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return url
        raise ValueError(f"No SQLAlchemy URL for backend={self.backend!r}")
