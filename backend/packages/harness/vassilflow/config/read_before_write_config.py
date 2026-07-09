"""Configuration for the read-before-write file gate middleware."""

from pydantic import BaseModel, Field


class ReadBeforeWriteConfig(BaseModel):
    """Deterministic version gate on file-modifying tools.

    When enabled, ``write_file`` and ``str_replace`` are blocked for existing
    files unless the file was read at its current version earlier in the
    conversation. This forces the agent to inspect the current state before
    changing it.
    """

    enabled: bool = Field(
        default=True,
        description="Whether to block writes to existing files that were not read at their current version",
    )
